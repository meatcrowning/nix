"""MOSS token inspection and generation-bound, portable token feature maps."""
import asyncio
from pathlib import Path
import sys
import threading

import torch
from aiohttp import web
import nodes
from server import PromptServer
from comfy.patcher_extension import WrappersMP
from comfy_extras.nodes_custom_sampler import SamplerCustom

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import moss_data
from moss_capture import CaptureWindow, map_shape

_tokenizer = None
_token_lock = threading.Lock()


def tokenize(text, tokenizer=None):
    global _tokenizer
    with _token_lock:
        if tokenizer is None:
            if _tokenizer is None:
                from comfy.text_encoders.moss_image import MOSSImageTokenizer
                _tokenizer = MOSSImageTokenizer()
            tokenizer = _tokenizer
        rows = tokenizer.tokenize_with_weights(text)['qwen35_9b']
        ids = [t[0] for row in rows for t in row]
        raw = tokenizer.qwen35_9b.tokenizer
        pieces = raw.convert_ids_to_tokens(ids)
        special = set(raw.all_special_ids)
        # Qwen uses GPT-2's byte alphabet; transformers' newer tokenizer
        # wrappers no longer expose byte_decoder themselves.
        alphabet = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
        missing = [b for b in range(256) if b not in alphabet]
        decoder = dict(zip(map(chr, alphabet + list(range(256, 256 + len(missing)))), alphabet + missing))
        parts = [p.encode() if i in special else bytes(decoder[c] for c in p)
                 for i, p in zip(ids, pieces)]
        full = b''.join(parts)
        trimmed = text if text.startswith('<|im_start|>') else text.strip()
        body = trimmed.encode()
        prefix = (0 if text.startswith('<|im_start|>') else len(b'<|im_start|>user\n')) if body else -1
        if body and full[prefix:prefix + len(body)] != body:
            raise ValueError('MOSS tokenizer text alignment changed')
        leading = len(text) - len(text.lstrip())
        byte_positions = [0]
        for char in trimmed:
            byte_positions.append(byte_positions[-1] + len(char.encode()))
        byte_offsets = set(byte_positions)
        utf16_positions = [0]
        for char in text:
            utf16_positions.append(utf16_positions[-1] + (2 if ord(char) > 0xffff else 1))
        import bisect
        cursor, tokens, boundaries = 0, [], set()
        for index, (identity, part) in enumerate(zip(ids, parts)):
            end = cursor + len(part)
            visible = prefix >= 0 and cursor < prefix + len(body) and end > prefix
            start_char = leading + max(0, bisect.bisect_right(byte_positions, max(0, cursor - prefix)) - 1) if visible else -1
            end_char = leading + bisect.bisect_left(byte_positions, min(len(body), end - prefix)) if visible else -1
            tokens.append(dict(id=identity, index=index, text=part.decode('utf-8', errors='replace'),
                               start=start_char, end=end_char, visible=visible))
            if visible and cursor > prefix and cursor - prefix in byte_offsets:
                boundaries.add(start_char)
            cursor = end
        return dict(count=len(ids), tokens=tokens, boundaries=sorted(boundaries),
                    utf16_boundaries=[utf16_positions[p] for p in sorted(boundaries)],
                    template_tokens=sum(not t['visible'] for t in tokens))


@PromptServer.instance.routes.post('/painter/moss/tokenize')
async def tokenize_request(request):
    doc = await request.json()
    text = doc.get('text', '')
    if not isinstance(text, str) or len(text) > 100000:
        raise web.HTTPBadRequest(text='Prompt is too long')
    result = await asyncio.to_thread(tokenize, text)
    return web.json_response(result)


class PainterMossSampler:
    @classmethod
    def INPUT_TYPES(cls):
        spec = SamplerCustom.INPUT_TYPES()
        spec['required'].update(clip=('CLIP',), text=('STRING',))
        return spec

    RETURN_TYPES = ('LATENT', 'LATENT', 'PAINTER_MOSS_MAPS')
    FUNCTION = 'sample'
    CATEGORY = 'painter'

    def sample(self, clip, text, **inputs):
        sampler = nodes.NODE_CLASS_MAPPINGS['PainterSamplerCustom']
        if getattr(sampler, 'PAINTER_STEP_OBSERVER_VERSION', 0) < 1:
            raise RuntimeError('MOSS heatmaps require the updated Painter sampler callback; '
                               'apply the Painter backend configuration and restart the backend.')
        metadata = tokenize(text, clip.tokenizer)
        if metadata['count'] > 4096:
            return nodes.NODE_CLASS_MAPPINGS['PainterSamplerCustom']().sample(**inputs) + ([],)
        model = inputs['model'].clone()
        if model.model_options.get('transformer_options', {}).get('optimized_attention_override'):
            return nodes.NODE_CLASS_MAPPINGS['PainterSamplerCustom']().sample(**inputs) + ([],)
        steps = max(1, len(inputs['sigmas']) - 1)
        state = {}
        capture = CaptureWindow(steps)

        def forward(executor, x, timestep, context, transformer_options={}, **kw):
            state['shape'] = x.shape[-2:]
            if 0 in transformer_options.get('cond_or_uncond', []):
                capture.begin()
            return executor(x, timestep, context, transformer_options, **kw)

        def attention(original, q, k, v, heads, **kw):
            out = original(q, k, v, heads, **kw)
            options = kw.get('transformer_options', {})
            branches = options.get('cond_or_uncond', [])
            # Existing output features: sparse capture in the middle third.
            # No rivalry between tokens: adjectives and nouns may overlap.
            if options.get('block_index') not in (4, 8) or 0 not in branches or not capture.wanted:
                return out
            h, w = state['shape']
            n = h * w
            batch = out.shape[0] // len(branches)
            features = out.chunk(len(branches))[branches.index(0)].float()
            if features.shape[1] != n + metadata['count']:
                raise ValueError('MOSS conditioning/token alignment changed')
            maps = features[:, n:] @ features[:, :n].transpose(1, 2)
            maps = maps.reshape(batch, metadata['count'], h, w)
            maps = torch.nn.functional.interpolate(maps, size=map_shape(h, w, metadata['count']), mode='bilinear', align_corners=False)
            if capture.pending is None:
                capture.pending = maps
            else:
                capture.pending.add_(maps)
            return out

        model.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, 'painter_moss', forward)
        model.model_options['transformer_options']['optimized_attention_override'] = attention
        model.model_options['painter_step_observer'] = capture.finish
        inputs['model'] = model
        sampled = nodes.NODE_CLASS_MAPPINGS['PainterSamplerCustom']().sample(**inputs)
        maps = capture.maps
        packets = []
        if maps is not None:
            maps = maps / (2 * len(capture.captured))
            # Smooth raw associations, before each token's contrast stretch.
            padded = torch.nn.functional.pad(maps, (0, 0, 1, 1), mode='replicate')
            maps = (padded[:, :, :-2] + 2*padded[:, :, 1:-1] + padded[:, :, 2:]) / 4
            padded = torch.nn.functional.pad(maps, (1, 1, 0, 0), mode='replicate')
            maps = (padded[:, :, :, :-2] + 2*padded[:, :, :, 1:-1] + padded[:, :, :, 2:]) / 4
            h, w = maps.shape[-2:]
            maps = maps.flatten(2)
            lo = torch.quantile(maps, .05, dim=-1, keepdim=True)
            hi = torch.quantile(maps, .99, dim=-1, keepdim=True)
            normalized = ((maps - lo) / (hi - lo).clamp_min(1e-12)).clamp(0, 1)
            for item in normalized:
                doc = dict(version=2, prompt=text, tokens=metadata['tokens'], width=w, height=h,
                           method='attention output similarity', captured_calls=len(capture.captured),
                           capture=dict(version=3, block_indices=[4, 8], sampler_steps=capture.captured,
                                        layer_reduction='mean raw associations', resolution_cap=128,
                                        smoothing='separable binomial [1,2,1]/4; edge padding; before token quantiles',
                                        step_index_base=0, total_steps=steps,
                                        evaluation='last positive evaluation before sampler callback',
                                        normalization='per-token 5th–99th percentile, clipped to uint8',
                                        latent_shape=list(state['shape']),
                                        attribution='feature similarity, not attention probability or causal attribution'))
                packets.append(moss_data.encode(doc, (item * 255).byte().cpu().numpy().tobytes()))
        return sampled + (packets,)


class PainterMossSaveImage(nodes.SaveImage):
    @classmethod
    def INPUT_TYPES(cls):
        spec = super().INPUT_TYPES()
        spec['required']['heatmaps'] = ('PAINTER_MOSS_MAPS',)
        return spec

    def save_images(self, images, heatmaps, filename_prefix='painter', prompt=None, extra_pnginfo=None):
        # Preserve Comfy's naming and metadata, then attach one bounded private
        # chunk. Ordinary metadata/gallery scans skip this binary payload.
        result = super().save_images(images, filename_prefix, prompt, extra_pnginfo)
        import struct, zlib
        for entry, packet in zip(result['ui']['images'], heatmaps):
            path = Path(self.output_dir) / entry['subfolder'] / entry['filename']
            data = path.read_bytes()
            chunk = struct.pack('>I', len(packet)) + moss_data.CHUNK + packet
            chunk += struct.pack('>I', zlib.crc32(moss_data.CHUNK + packet) & 0xffffffff)
            path.write_bytes(data[:-12] + chunk + data[-12:])
        return result


NODE_CLASS_MAPPINGS = {'PainterMossSampler': PainterMossSampler, 'PainterMossSaveImage': PainterMossSaveImage}

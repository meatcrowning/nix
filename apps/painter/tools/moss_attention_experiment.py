"""Experimental sampler node; load ONLY in an isolated ComfyUI test backend.

Captures positive-branch attention or existing attention-output similarities.
This is not full ConceptAttention: it adds no separate concept tokens. Load in
a scratch backend and replace KSampler with MossAttentionExperiment, passing
the same prompt text/CLIP plus comma-separated words, layers and a step stride.
Outputs NPZ maps and timing/hash JSON beside scratch images; bands are thirds
of the positive forward-call sequence. This installs no Painter feature.
"""
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import torch
import folder_paths
import nodes
from comfy.patcher_extension import WrappersMP


class MossAttentionExperiment(nodes.KSampler):
    @classmethod
    def INPUT_TYPES(cls):
        spec = super().INPUT_TYPES()
        spec['required'] = dict(spec['required'], clip=('CLIP',),
                                text=('STRING',), words=('STRING',),
                                capture=('BOOLEAN', {'default': True}),
                                label=('STRING', {'default': 'experiment'}))
        spec['optional'] = dict(method=(['raw', 'output'],),
                                layers=('STRING', {'default': '4,12,20,28,36'}),
                                stride=('INT', {'default': 1, 'min': 1, 'max': 30}))
        return spec

    FUNCTION = 'run'
    CATEGORY = 'testing'

    def run(self, clip, text, words, capture, label, method="raw",
            layers="4,12,20,28,36", stride=1, **inputs):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', label):
            raise ValueError('Use a plain experiment label')
        tokenizer = clip.tokenizer.qwen35_9b.tokenizer
        token_rows = clip.tokenize(text)['qwen35_9b']
        assert len(token_rows) == 1
        ids = [t[0] for t in token_rows[0]]
        spans = {}
        for word in words.split(','):
            word = word.strip()
            needle = tokenizer.encode(' ' + word, add_special_tokens=False)
            matches = [i for i in range(len(ids) - len(needle) + 1)
                       if ids[i:i + len(needle)] == needle]
            if len(matches) != 1:
                raise ValueError(f'Expected one token span for {word}: {matches}')
            spans[word] = list(range(matches[0], matches[0] + len(needle)))
        model = inputs['model'].clone()
        sums, counts, state = {}, {}, {}
        capture_events = []
        selected_layers = {int(i) for i in layers.split(",")}
        state["step"] = -1
        steps = inputs["steps"]

        def forward(executor, x, timestep, context, transformer_options={}, **kw):
            state['shape'] = x.shape[-2:]
            if 0 in transformer_options.get('cond_or_uncond', []):
                state['step'] += 1
            # Step bands avoid a device-to-host synchronization per forward.
            state['band'] = min(2, state['step'] * 3 // steps)
            return executor(x, timestep, context, transformer_options, **kw)

        def accumulate(key, maps):
            if key not in sums:
                sums[key] = maps.clone()
                counts[key] = 1
            else:
                sums[key].add_(maps)
                counts[key] += 1

        def observe(original, q, k, v, heads, **kw):
            options = kw.get('transformer_options', {})
            layer = options.get('block_index')
            branches = options.get('cond_or_uncond', [])
            selected = (layer in selected_layers and 0 in branches
                        and state['step'] % stride == 0)
            if not selected:
                return original(q, k, v, heads, **kw)
            h, w = state['shape']
            n = h * w
            assert q.shape[1] == n + len(ids), (q.shape, n, len(ids))
            assert q.shape[0] == len(branches), 'experiment requires batch size 1'
            b = branches.index(0)
            key = f'layer{layer}_band{state["band"]}'
            out = None
            if method == 'output':
                out = original(q, k, v, heads, **kw)
            start, end = (torch.cuda.Event(enable_timing=True) for _ in range(2))
            start.record()
            if method == 'raw':
                d = q.shape[-1] // heads
                qh = q[b].reshape(-1, heads, d).transpose(0, 1).float()
                kh = k[b].reshape(-1, heads, d).transpose(0, 1).float()
                chunks = []
                for offset in range(0, n, 128):
                    probs = (qh[:, offset:min(n, offset + 128)] @ kh.transpose(-1, -2) / d**0.5).softmax(-1)
                    text_probs = probs[..., n:].mean(0)
                    chunks.append(torch.stack([text_probs[:, indices].sum(-1)
                                               for indices in spans.values()]))
                maps = torch.cat(chunks, dim=1).reshape(len(spans), h, w)
                accumulate(key, maps)
            else:
                features = out[b].float()
                image_features = features[:n]
                concepts = torch.stack([features[[n + i for i in indices]].mean(0)
                                        for indices in spans.values()])
                dot = concepts @ image_features.T
                cosine = torch.nn.functional.normalize(concepts, dim=-1) @ torch.nn.functional.normalize(image_features, dim=-1).T
                accumulate('dot_' + key, dot.reshape(len(spans), h, w))
                accumulate('cosine_' + key, cosine.reshape(len(spans), h, w))
            end.record()
            capture_events.append((start, end))
            return out if out is not None else original(q, k, v, heads, **kw)

        if capture:
            model.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL, 'moss_probe', forward)
            model.model_options['transformer_options']['optimized_attention_override'] = observe
        inputs['model'] = model
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        result = self.sample(**inputs)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        latent = result[0]['samples'].detach().cpu().contiguous()
        root = Path(folder_paths.get_output_directory())
        np.savez_compressed(root / (label + '.npz'), **{k: (sums[k] / counts[k]).cpu().numpy() for k in sums})
        report = dict(label=label, prompt=text, spans=spans, counts=counts,
                      sampler_seconds=elapsed, method=method, layers=sorted(selected_layers),
                      band_definition="positive forward-call thirds",
                      stride=stride, capture_cuda_seconds=sum(a.elapsed_time(b) for a, b in capture_events) / 1000,
                      peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                      latent_sha256=hashlib.sha256(latent.view(torch.uint8).numpy().tobytes()).hexdigest())
        (root / (label + '.json')).write_text(json.dumps(report, indent=2))
        print('MOSS_EXPERIMENT ' + json.dumps(report), flush=True)
        return result


NODE_CLASS_MAPPINGS = {'MossAttentionExperiment': MossAttentionExperiment}

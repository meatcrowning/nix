"""Experimental sampler node; load ONLY in an isolated ComfyUI test backend.

Captures positive-branch attention at five MOSS layers, without installing a
Painter feature. Outputs NPZ maps and timing/hash JSON beside scratch images.
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
        return spec

    FUNCTION = 'run'
    CATEGORY = 'testing'

    def run(self, clip, text, words, capture, label, **inputs):
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
        capture_seconds = 0.0

        def forward(executor, x, timestep, context, transformer_options={}, **kw):
            state['shape'] = x.shape[-2:]
            state['band'] = min(2, int(float(timestep[0]) * 3))
            return executor(x, timestep, context, transformer_options, **kw)

        def observe(original, q, k, v, heads, **kw):
            nonlocal capture_seconds
            options = kw.get('transformer_options', {})
            layer = options.get('block_index')
            branches = options.get('cond_or_uncond', [])
            if layer in (4, 12, 20, 28, 36) and 0 in branches:
                torch.cuda.synchronize()
                started = time.perf_counter()
                h, w = state['shape']
                n = h * w
                assert q.shape[1] == n + len(ids), (q.shape, n, len(ids))
                assert q.shape[0] == len(branches), 'experiment requires batch size 1'
                b = branches.index(0)
                d = q.shape[-1] // heads
                qh = q[b].reshape(-1, heads, d).transpose(0, 1).float()
                kh = k[b].reshape(-1, heads, d).transpose(0, 1).float()
                chunks = []
                for start in range(0, n, 128):
                    probs = (qh[:, start:min(n, start + 128)] @ kh.transpose(-1, -2) / d**0.5).softmax(-1)
                    text_probs = probs[..., n:].mean(0)
                    chunks.append(torch.stack([text_probs[:, indices].sum(-1)
                                               for indices in spans.values()]))
                maps = torch.cat(chunks, dim=1).reshape(len(spans), h, w).cpu().numpy()
                key = f'layer{layer}_band{state["band"]}'
                if key not in sums:
                    sums[key] = maps.copy()
                    counts[key] = 1
                else:
                    sums[key] += maps
                    counts[key] += 1
                torch.cuda.synchronize()
                capture_seconds += time.perf_counter() - started
            return original(q, k, v, heads, **kw)

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
        np.savez_compressed(root / (label + '.npz'), **{k: sums[k] / counts[k] for k in sums})
        report = dict(label=label, prompt=text, spans=spans, counts=counts,
                      sampler_seconds=elapsed, capture_seconds=capture_seconds,
                      peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                      latent_sha256=hashlib.sha256(latent.view(torch.uint8).numpy().tobytes()).hexdigest())
        (root / (label + '.json')).write_text(json.dumps(report, indent=2))
        print('MOSS_EXPERIMENT ' + json.dumps(report), flush=True)
        return result


NODE_CLASS_MAPPINGS = {'MossAttentionExperiment': MossAttentionExperiment}

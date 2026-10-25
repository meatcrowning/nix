"""Raw 64x64 feature-map ablation; load only in an isolated Comfy backend.

Requires PainterSamplerCustom for real sampler-step callbacks. Never changes
model features. Keeps individual captures, so analysis can test time/layer
ensembles without rerunning generation or losing raw strength/consistency.
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
from comfy_extras.nodes_custom_sampler import SamplerCustom


class MossQualityExperiment:
    @classmethod
    def INPUT_TYPES(cls):
        spec = SamplerCustom.INPUT_TYPES()
        spec['required'].update(clip=('CLIP',), text=('STRING',), words=('STRING',),
                                capture=('BOOLEAN',), label=('STRING',),
                                layers=('STRING',), stride=('INT', {'min': 1, 'max': 30}))
        return spec

    RETURN_TYPES = ('LATENT', 'LATENT')
    FUNCTION = 'run'
    CATEGORY = 'testing'

    def run(self, clip, text, words, capture, label, layers, stride, **inputs):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', label):
            raise ValueError('Use a plain experiment label')
        tokenizer = clip.tokenizer.qwen35_9b.tokenizer
        rows = clip.tokenize(text)['qwen35_9b']
        assert len(rows) == 1
        ids = [t[0] for t in rows[0]]
        spans = {}
        for word in words.split(','):
            word = word.strip()
            needle = tokenizer.encode(' '+word, add_special_tokens=False)
            matches = [i for i in range(len(ids)-len(needle)+1) if ids[i:i+len(needle)] == needle]
            if len(matches) != 1:
                raise ValueError(f'Expected one token span for {word}: {matches}')
            spans[word] = list(range(matches[0], matches[0]+len(needle)))
        model = inputs['model'].clone()
        if model.model_options.get('transformer_options', {}).get('optimized_attention_override'):
            raise ValueError('An attention override is already installed')
        steps = len(inputs['sigmas'])-1
        state = dict(step=0, pending={})
        samples, events = {}, []
        selected_layers = {int(i) for i in layers.split(',')}

        def forward(executor, x, timestep, context, transformer_options={}, **kw):
            state['shape'] = x.shape[-2:]
            if 0 in transformer_options.get('cond_or_uncond', []):
                state['pending'] = {}
            return executor(x, timestep, context, transformer_options, **kw)

        def finish(step):
            assert step == state['step']
            # Transfer small maps only at a sampled callback. Retain float32;
            # display normalization belongs to the subsequent analysis.
            for key, value in state['pending'].items():
                samples[f'{key}_step{step}'] = value.cpu().numpy()
            state['pending'] = {}
            state['step'] = step+1

        def observe(original, q, k, v, heads, **kw):
            out = original(q, k, v, heads, **kw)
            options = kw.get('transformer_options', {})
            branches = options.get('cond_or_uncond', [])
            layer = options.get('block_index')
            if layer not in selected_layers or 0 not in branches or (state['step']-steps//3) % stride:
                return out
            h, w = state['shape']
            n = h*w
            assert out.shape[0] == len(branches), 'Requires batch size one'
            assert out.shape[1] == n+len(ids), 'Token alignment changed'
            start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            start.record()
            features = out[branches.index(0)].float()
            image, text_features = features[:n], features[n:]
            # Compute all token maps as Painter would; retain the requested words.
            center = image.mean(0, keepdim=True)
            methods = dict(dot=text_features @ image.T,
                           cosine=torch.nn.functional.normalize(text_features, dim=-1) @ torch.nn.functional.normalize(image, dim=-1).T,
                           centered=torch.nn.functional.normalize(text_features-center, dim=-1) @ torch.nn.functional.normalize(image-center, dim=-1).T)
            for method, maps in methods.items():
                maps = torch.stack([maps[indices].mean(0) for indices in spans.values()]).reshape(1,len(spans),h,w)
                maps = torch.nn.functional.interpolate(maps, size=(min(h,64),min(w,64)), mode='bilinear', align_corners=False)[0]
                state['pending'][f'{method}_layer{layer}'] = maps
            end.record()
            events.append((start,end))
            return out

        if capture:
            model.add_wrapper_with_key(WrappersMP.DIFFUSION_MODEL,'moss_quality',forward)
            model.model_options['transformer_options']['optimized_attention_override'] = observe
            model.model_options['painter_step_observer'] = finish
        inputs['model'] = model
        torch.cuda.synchronize()
        started = time.perf_counter()
        result = nodes.NODE_CLASS_MAPPINGS['PainterSamplerCustom']().sample(**inputs)
        torch.cuda.synchronize()
        elapsed = time.perf_counter()-started
        latent = result[0]['samples'].detach().cpu().contiguous()
        root = Path(folder_paths.get_output_directory())
        root.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(root/(label+'.npz'), **samples)
        report = dict(label=label, prompt=text, spans=spans, steps=steps, layers=sorted(selected_layers),
                      stride=stride, sampler_seconds=elapsed,
                      capture_cuda_seconds=sum(a.elapsed_time(b) for a,b in events)/1000,
                      map_limit=64, capture_evaluation='last positive evaluation before sampler callback',
                      latent_sha256=hashlib.sha256(latent.view(torch.uint8).numpy().tobytes()).hexdigest())
        (root/(label+'.json')).write_text(json.dumps(report,indent=2))
        print('MOSS_QUALITY '+json.dumps(report),flush=True)
        return result


NODE_CLASS_MAPPINGS = {'MossQualityExperiment': MossQualityExperiment}

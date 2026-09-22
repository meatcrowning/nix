#!/usr/bin/env python3
"""CPU-only patch algebra and native node contracts; no model weights/inference.

Run inside Comfy's nix-shell: python /home/lam/nix/apps/painter/tools/qwen21-patches-test.py
"""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

sys.argv += ["--cpu"]
sys.path.insert(0, str(Path.cwd()))
import torch
import nodes
import comfy.model_base
import comfy.model_patcher
import comfy.model_sampling
from comfy_extras import nodes_qwen, nodes_custom_sampler

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "comfy_nodes"))
import painter_qwen21 as P
import registry as R
import graph as G
from comfy.text_encoders.qwen_image21 import QwenImage21Tokenizer

spec = importlib.util.spec_from_file_location("advanced", Path.cwd() / "custom_nodes/ComfyUI-ModelSamplingSD3Advanced/__init__.py")
advanced = importlib.util.module_from_spec(spec)
spec.loader.exec_module(advanced)
nodes.NODE_CLASS_MAPPINGS.update(advanced.NODE_CLASS_MAPPINGS)

# Native tokenization otherwise disables weights, making the patch a no-op.
tokenizer = QwenImage21Tokenizer()
patched_tokenizer = P.weighted_tokenizer(tokenizer)
raw = tokenizer.tokenize_with_weights('cube, (blur:-1)')['qwen3vl_8b'][0]
signed = patched_tokenizer.tokenize_with_weights('cube, (blur:-1)')['qwen3vl_8b'][0]
assert all(t[1] == 1 for t in raw) and any(t[1] == -1 for t in signed)
assert all(t[1] == 1 for t in tokenizer.tokenize_with_weights('(blur:-1)')['qwen3vl_8b'][0])

# Reference images expand in the encoder, then disappear from text conditioning.
pairs = [(151644, 1), (10, 1), (151644, 1), ({"type": "image"}, 1),
         (20, -1), (21, .5)]
assert P.text_weights(pairs, [(3, 4)], False) == [1., -1., .5]
assert P.text_weights(pairs, [(3, 4)], True) == [1., 1., 1., 1., 1., -1., .5]
weights = torch.tensor([[[1.], [-1.], [.5]]])
refs = [torch.zeros(1, 64, 1, 2)]
full = P.sequence_weights(weights, refs, [1], 2)
assert full.flatten().tolist() == [1., 1., 1., -1., .5, 1., 1.]
q, k, v = (torch.ones(1, 2, 7, 4) for _ in range(3))
out = P.attention_values(q, k, v, extra_options={P.KEY: full})
assert out['q'] is q and out['k'] is k
assert torch.equal(out['v'][0, 0, :, 0], full.flatten())
assert torch.all(v == 1)  # no in-place changes to another patch's input

original_options = {"patches": {"attn1_patch": []}}
def executor(x, timestep, context, refs, slots, options, **kw):
    assert options['patches']['attn1_patch'] == [P.attention_values]
    assert torch.equal(options[P.KEY], full)
P.diffusion_wrapper(executor, torch.zeros(1, 64, 1, 2), None, None,
                    refs, [1], original_options, **{P.KEY: weights})
assert original_options == {"patches": {"attn1_patch": []}}

# Native encode output and extras survive; only its weights are neutralized.
def encode(tokens):
    assert all(t[1] == 1 for t in tokens['qwen3vl_8b'][0])
    return torch.ones(1, 3, 4), None, {"image_slots": [1]}
te = SimpleNamespace(clip='qwen3vl_8b', qwen3vl_8b=SimpleNamespace(image_spans=[(3, 4)]))
encoded, _, extra = P.encode_weights(te, encode, {'qwen3vl_8b': [pairs]})
assert extra['image_slots'] == [1] and torch.equal(extra[P.KEY], weights)
assert pairs[-2][1] == -1

# Exercise the actual sampler patch on a weightless model shell.
model = object.__new__(comfy.model_base.QwenImage21)
torch.nn.Module.__init__(model)
model.model_config = SimpleNamespace(sampling_settings={'shift': .69, 'multiplier': 1.})
model.model_sampling = comfy.model_sampling.ModelSamplingFlux(model.model_config)
patcher = comfy.model_patcher.ModelPatcher(model, torch.device('cpu'), torch.device('cpu'))
p = dict(shift_start=1.9937155332, shift_end=1.9937155332, start_percent=.2,
         end_percent=.8, curve='linear', outside_window='baseline', multiplier=1.)
patched, = P.PainterQwen21ModelSampling().patch(patcher, **p)
sampling = patched.get_model_object('model_sampling')
t = torch.tensor([.1, .5, .9])
assert torch.allclose(sampling.sigma(t), model.model_sampling.sigma(t))
assert torch.equal(sampling.timestep(t), t)
assert not patcher.object_patches and model.model_config.sampling_settings['shift'] == .69

# Build all toggle combinations against installed native schemas.
reg = R.Registry()
entry = next(e for e in reg.base_models() if e.family == 'qwen_image21')
classes = {**nodes.NODE_CLASS_MAPPINGS, **P.NODE_CLASS_MAPPINGS,
           'TextEncodeQwenImage21': nodes_qwen.TextEncodeQwenImage21,
           'BasicScheduler': nodes_custom_sampler.BasicScheduler,
           'KSamplerSelect': nodes_custom_sampler.KSamplerSelect,
           'PainterSamplerCustom': nodes_custom_sampler.SamplerCustom}
for edit in (False, True):
    for negpip in (False, True):
        for shift in (False, True):
            built = reg.build(entry, {'positive':'cube', 'negative':'blur', 'edit':edit,
                'input_images':['one.png', 'two.png'],
                'toggles': {'negpip':negpip, 'model_sampling':shift}})
            oi = {n['class_type']: {'input': classes[n['class_type']].INPUT_TYPES()}
                  for n in built['prompt'].values()}
            assert not G.validate(built['prompt'], oi), G.validate(built['prompt'], oi)
print('PASS Qwen patch algebra, sampler baseline, and native contracts (CPU; no weights loaded)')

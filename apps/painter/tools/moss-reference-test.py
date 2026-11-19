#!/usr/bin/env python3
"""CPU-only reference preprocessing and conditioning; no server or inference."""
import ast
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ['CUDA_VISIBLE_DEVICES'] = ''
import torch
sys.path.insert(0, os.environ.get('COMFY_ROOT', '/home/lam/comfy'))
# comfy.utils is CPU-safe; do not import nodes or the backend server.
import comfy.utils

source = Path(__file__).resolve().parents[1] / 'comfy_nodes/painter_moss.py'
classes = [n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef)
           and n.name in ('PainterMossReference', 'PainterMossReferenceEncode', 'PainterMossReferenceTiming')]
ns = dict(math=math, torch=torch)
exec(compile(ast.Module(body=classes, type_ignores=[]), str(source), 'exec'), ns)
append = ns['PainterMossReference']().append
# Distinct borders must survive the resize, including a wide reference.
image = torch.zeros(1, 128, 512, 3)
image[:, :, :32, 0] = 1
image[:, :, -32:, 2] = 1
references, = append(image, .065536)
assert references[0].shape == (1, 128, 512, 3)
assert references[0][0, 64, 0, 0] == 1 and references[0][0, 64, -1, 2] == 1
portrait = torch.ones(1, 512, 128, 3)
more, = append(portrait, .065536, references)
assert len(references) == 1 and len(more) == 2
assert more[1].shape == (1, 512, 128, 3)
resized, = append(image, .262144)
assert resized[0].shape == (1, 256, 1024, 3)
assert resized[0][0, 128, 0, 0] > .9 and resized[0][0, 128, -1, 2] > .9
for _ in range(20):
    more, = append(image, .065536, more)
assert len(more) == 22
calls = []
clip = SimpleNamespace(tokenize=lambda text, **kw: calls.append((text, kw)) or {'tokens': text},
                       encode_from_tokens_scheduled=lambda tokens: tokens)
encode = ns['PainterMossReferenceEncode']().encode
for prompt in ('red cube', 'blur'):
    result, = encode(clip, prompt, more)
    assert result['tokens'].endswith(prompt)
    assert calls[-1][0].count('<|image_pad|>') == 22
    assert calls[-1][1]['images'] is more
# Use native tokenization to check that markers become actual image embeddings.
from comfy.cli_args import args
args.cpu = True
from comfy.text_encoders.moss_image import MOSSImageTokenizer
tokens = MOSSImageTokenizer().tokenize_with_weights(calls[0][0], images=more)
embeddings = [t[0] for row in tokens['qwen35_9b'] for t in row if isinstance(t[0], dict)]
assert len(embeddings) == 22
assert all(e['type'] == 'image' for e in embeddings)
print('PASS: whole-image resize, per-image MP, 22 references, both CFG branches and native vision tokens')

# Every evaluation has exactly one branch, including exact switching sigmas.
schedule = ns['PainterMossReferenceTiming']().schedule
reference, plain = [['reference', {'kept': True}]], [['plain', {'kept': True}]]
# Exercise Comfy's actual conditioning gate without importing its sampler stack.
import collections
sampler_source = Path(os.environ.get('COMFY_ROOT', '/home/lam/comfy')) / 'comfy/samplers.py'
gate = next(n for n in ast.parse(sampler_source.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == 'get_area_and_mult')
gate_ns = dict(torch=torch, collections=collections)
exec(compile(ast.Module(body=[gate], type_ignores=[]), str(sampler_source), 'exec'), gate_ns)
def enabled(metadata, sigma):
    return gate_ns['get_area_and_mult'](dict(metadata, model_conds={}, uuid='test'),
                                        torch.zeros(1, 1, 2, 2), sigma.reshape(1)) is not None

for steps in (1, 2, 3, 7, 50):
    sigmas = torch.linspace(1, 0, steps + 1).square()
    for third, phase in enumerate(('early', 'middle', 'late')):
        result, = schedule(reference, plain, sigmas, phase)
        start, end = ((steps * i + 2) // 3 for i in (third, third + 1))
        for i, sigma in enumerate(sigmas[:-1]):
            active = [name for name, meta in result
                      if enabled(meta, sigma)]
            assert active == ['reference' if start <= i < end else 'plain'], (steps, phase, i, active)
        for sigma in (sigmas[:-1] + sigmas[1:]) / 2:
            assert sum(enabled(meta, sigma) for _, meta in result) == 1
assert reference == [['reference', {'kept': True}]] and plain == [['plain', {'kept': True}]]
print('PASS: early/middle/late follow actual sigmas with no gaps, overlapping branches or input mutation')

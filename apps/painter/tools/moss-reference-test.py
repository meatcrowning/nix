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
           and n.name in ('PainterMossReference', 'PainterMossReferenceEncode')]
ns = dict(math=math)
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

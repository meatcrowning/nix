#!/usr/bin/env python3
"""CPU-only checks for sampler-step capture and image-space scoring."""
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from moss_capture import CaptureWindow
import moss_data
import moss_rank

class Values:
    def __init__(self, value): self.values = [value]
    def add_(self, other): self.values.extend(other.values)

for heun in (False, True):
    capture = CaptureWindow(50)
    for step in range(50):
        capture.begin()
        if capture.wanted:
            capture.pending = Values(('predictor', step))
        capture.finish(step)
        if heun and step < 49:
            capture.begin()
            if capture.wanted:
                capture.pending = Values(('corrector', step))
    assert capture.captured == [16, 19, 22, 25, 28, 31]
    assert capture.maps.values == [('predictor', i) for i in capture.captured]
# No callback means no accepted map; stops keep only completed captures.
capture = CaptureWindow(1)
capture.begin()
capture.pending = Values('uncommitted')
assert capture.maps is None
capture.finish(0)
assert capture.maps.values == ['uncommitted']

prompt = '{"summary":{"caption":"red bird"},"items":[],"width":1024}'
texts = ['summary', 'red', 'bird', '1024']
tokens = [dict(index=i, visible=True, text=t, start=prompt.index(t), end=prompt.index(t)+len(t)) for i,t in enumerate(texts)]
doc = dict(prompt=prompt, tokens=tokens, width=2, height=2)
pixels = bytes([255,0,0,0, 0,100,200,255, 0,100,200,255, 255,0,0,0])
assert moss_data.descriptive_aggregate(doc,pixels) == moss_data.aggregate(dict(doc,tokens=tokens[1:3]),pixels)
# Horizontal and vertical two-point planes tie on a square map; the wider
# output gives horizontal spread twice the pixel radius, independently checked.
doc = dict(prompt='bird tree',width=3,height=3,tokens=[dict(index=i,visible=True,text=t,start=a,end=b) for i,(t,a,b) in enumerate([('bird',0,4),('tree',5,9)])])
pixels = bytes([0,0,0,255,0,255,0,0,0, 0,255,0,0,0,0,0,255,0])
focused = moss_rank.rank(doc,pixels,image_size=(600,300))['focused']
assert [x['token']['text'] for x in focused] == ['tree','bird']
assert math.isclose(focused[0]['percentage'],100/math.hypot(600,300)*100)
assert math.isclose(focused[1]['percentage'],200/math.hypot(600,300)*100)
print('PASS: Euler/Heun callback capture, incomplete capture, layout filtering, image-space focus')

# Exercise the production callback, including commit-before-stop ordering,
# without importing Comfy's server or preview machinery.
import ast
from types import SimpleNamespace
source = Path(__file__).resolve().parents[1]/'comfy_nodes/painter_partial_stop.py'
callback = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_callback')
events = []
namespace = dict(latent_preview=SimpleNamespace(prepare_callback=lambda *a: lambda *a: events.append('preview')),
                 STATE=SimpleNamespace(consume=lambda: True), _StopHere=RuntimeError)
exec(compile(ast.Module(body=[callback],type_ignores=[]),str(source),'exec'),namespace)
model = SimpleNamespace(model_options={'painter_step_observer':lambda i: events.append(i)})
try:
    namespace['_callback'](model,50,{ })(16,None,None,50)
except RuntimeError:
    pass
else:
    raise AssertionError('Stop callback did not stop')
assert events == [16,'preview']
print('PASS: production callback commits capture before preview/stop')

#!/usr/bin/env python3
"""CPU-only production math check; run with a Python containing torch/numpy."""
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
import ast
import sys
from pathlib import Path
from types import SimpleNamespace
import torch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import moss_data
from moss_capture import CaptureWindow, map_shape
from moss_rank import word_groups, word_maps

source = Path(__file__).resolve().parents[1]/'comfy_nodes/painter_moss.py'
cls = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'PainterMossSampler')
class Model:
    def __init__(self): self.model_options = {'transformer_options': {}}
    def clone(self): return self
    def add_wrapper_with_key(self, _, key, fn): self.forward = fn

torch.manual_seed(732)
h, w, n = 19, 17, 3
features = {i: torch.randn(1,h*w+n,8) for i in (4,8)}
# Unequal subpiece amplitudes make averaging normalized pieces observably wrong.
for f in features.values(): f[:,h*w+1] *= 20
accepted = []
class Sampler:
    PAINTER_STEP_OBSERVER_VERSION = 1
    def sample(self, model, **kw):
        for step in range(30):
            # A discarded positive evaluation must not pollute either statistic.
            for scale in (100, 1):
                model.forward(lambda *a,**kw: None, torch.empty(1,1,h,w), None, None, {'cond_or_uncond':[0]})
                for layer in (4,8):
                    f = features[layer]*scale
                    model.model_options['transformer_options']['optimized_attention_override'](
                        lambda *a,**kw: f, None,None,None,None,
                        transformer_options={'cond_or_uncond':[0], 'block_index':layer})
                    if scale == 1 and step in (7,10,13,16):
                        accepted.append((f[:,h*w:]@f[:,:h*w].transpose(1,2)).reshape(n,h,w))
            model.model_options['painter_step_observer'](step)
        return ({'samples':'unchanged'}, {'samples':'unchanged'})

tokens = [dict(id=i,index=i,text=t,visible=True,start=a,end=b) for i,(t,a,b) in enumerate(
    [('ram',0,3),('shackle',3,10),(' tree',10,15)])]
ns = dict(torch=torch,moss_data=moss_data,CaptureWindow=CaptureWindow,map_shape=map_shape,word_groups=word_groups,
          tokenize=lambda *a: dict(count=n,tokens=tokens),nodes=SimpleNamespace(NODE_CLASS_MAPPINGS={'PainterSamplerCustom':Sampler}),
          WrappersMP=SimpleNamespace(DIFFUSION_MODEL=0))
exec(compile(ast.Module(body=[cls],type_ignores=[]),str(source),'exec'),ns)
result = ns['PainterMossSampler']().sample(SimpleNamespace(tokenizer=None),'ramshackle tree',model=Model(),sigmas=list(range(31)))
assert result[0]['samples'] == 'unchanged'
doc,pixels = moss_data.decode(result[2][0])
assert doc['capture']['sampler_steps'] == [7,10,13,16]
raw = torch.stack(accepted).mean(0)
raw = torch.cat((raw,raw[:2].mean(0,keepdim=True),raw[2:3]),dim=0)
# Independent NumPy edge filtering, then quantiles, matches the serialized planes.
p = np.pad(raw.numpy(),((0,0),(1,1),(0,0)),mode='edge')
smoothed = (p[:,:-2]+2*p[:,1:-1]+p[:,2:])/4
p = np.pad(smoothed,((0,0),(0,0),(1,1)),mode='edge')
flat = torch.from_numpy((p[:,:,:-2]+2*p[:,:,1:-1]+p[:,:,2:])/4).flatten(1)
lo,hi = torch.quantile(flat,.05,dim=-1,keepdim=True),torch.quantile(flat,.99,dim=-1,keepdim=True)
expected = ((flat-lo)/(hi-lo)).clamp(0,1).mul(255).byte().numpy().astype(int)
actual = np.frombuffer(pixels+doc['_word_pixels'],dtype=np.uint8).reshape(-1,h*w).astype(int)
assert np.abs(actual-expected).max() <= 1
assert np.abs(actual[n]-(actual[0]+actual[1])/2).max() > 20
words,_ = word_maps(doc,pixels)
assert words[1] == doc['_word_pixels']
# Direct pairwise correlation independently checks the streaming sum identity.
pooled = torch.nn.functional.adaptive_avg_pool2d(torch.stack(accepted),(16,16)).flatten(2)
centered = pooled-pooled.mean(-1,keepdim=True)
units = centered/centered.norm(dim=-1,keepdim=True)
corr = torch.einsum('tnp,snp->nts',units,units)
expected_agreement = corr[:,~torch.eye(len(accepted),dtype=torch.bool)].mean(-1)
assert torch.allclose(torch.tensor(doc['consistency']),expected_agreement,atol=1e-5)
assert moss_data.decode(moss_data.encode(doc,pixels))[1] == pixels
print('PASS raw word grouping, independent smoothing, callback isolation, pairwise agreement and v3 round trip')

# The real save-node path persists a reason for every member of a skipped batch.
import base64
import tempfile
sys.path.insert(0, str(source.parents[2]/'pylib'))
import pngmeta
plain = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII=')
class SaveImage:
    def save_images(self,*args):
        return {'ui': {'images': [dict(filename=str(i)+'.png',subfolder='') for i in range(2)]}}
ns['nodes'].SaveImage = SaveImage
ns['Path'] = Path
save = next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef) and n.name == 'PainterMossSaveImage')
exec(compile(ast.Module(body=[save],type_ignores=[]),str(source),'exec'),ns)
with tempfile.TemporaryDirectory() as folder:
    node = ns['PainterMossSaveImage']()
    node.output_dir = folder
    for i in range(2): (Path(folder)/(str(i)+'.png')).write_bytes(plain)
    node.save_images(None,[dict(reason='Sampling ended before capture')])
    for i in range(2):
        output = Path(folder)/(str(i)+'.png')
        assert pngmeta.read_text_path(output)['painter_moss_status'] == 'Sampling ended before capture'
        assert output.read_bytes().startswith(plain[:-12])
print('PASS skipped-batch status persistence without changing image chunks')

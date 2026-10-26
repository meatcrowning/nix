#!/usr/bin/env python3
"""Compare equal-budget layer/schedule candidates from saved research captures.

Usage: Comfy Python moss-schedule-study.py STUDY_ROOT OUTPUT_DIRECTORY
Uses existing image-only polygons and raw captures; no inference or desktop I/O.
The validation scenes were previously inspected: this is retrospective evidence.
"""
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
import torch,numpy as np,json,sys,importlib.util
from pathlib import Path
from PIL import Image,ImageDraw
r=Path(sys.argv[1]);a=json.loads((r/'annotations.json').read_text())
spec=importlib.util.spec_from_file_location('analysis',Path(__file__).with_name('moss-quality-analyze.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rows={}
for scene,info in a.items():
 d=dict(np.load(r/'output'/(scene+'.npz')));doc=json.loads((r/'output'/(scene+'.json')).read_text());words=list(doc['spans'])
 for layers in ((4,8),(0,4),(4,12),(8,12)):
  for steps in ((4,7,10,13),(7,10,13,16),(10,13,16,19),(13,16,19,22)):
   parts=[v for k,v in d.items() if k.startswith('dot_') and int(k.split('_')[1][5:]) in layers and int(k.split('_')[2][4:]) in steps]
   assert len(parts)==8
   raw=np.mean(parts,axis=0);p=np.pad(raw,((0,0),(1,1),(0,0)),mode='edge');raw=(p[:,:-2]+2*p[:,1:-1]+p[:,2:])/4;p=np.pad(raw,((0,0),(0,0),(1,1)),mode='edge');raw=(p[:,:,:-2]+2*p[:,:,1:-1]+p[:,:,2:])/4
   vals=[]
   for word,poly in info['polygons'].items():
    mask=Image.new('L',(64,64));dr=ImageDraw.Draw(mask);dr.polygon([(x*64,y*64) for x,y in poly],fill=1)
    for hole in info.get('holes',{}).get(word,[]):dr.polygon([(x*64,y*64) for x,y in hole],fill=0)
    vals.append(m.metrics(raw[words.index(word)],np.array(mask,dtype=bool)))
   rows.setdefault(str((layers,steps)),{})[scene]=vals
scenes=list(a);scores=[]
for name,values in rows.items():
 scores.append(dict(name=name,selection=m.mean_metrics([v for s in scenes[:2] for v in values[s]]),retrospective_validation=m.mean_metrics([v for s in scenes[2:] for v in values[s]])))
scores.sort(key=lambda x:-x['selection']['ap']);out=Path(sys.argv[2]);out.mkdir(exist_ok=True)
(out/'schedule-report.json').write_text(json.dumps(dict(protocol='Equal eight captures from existing raw captures. First two scenes selection, four previously inspected scenes retrospective validation; no fresh held-out claim. Baseline schedule is layers 4,8 at 10,13,16,19; original raw study sampled steps 1,4,7 and so on.',scores=scores,details=rows),indent=2));print(json.dumps(scores,indent=2))

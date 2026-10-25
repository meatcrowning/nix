#!/usr/bin/env python3
"""Evaluate isolated raw captures against image-only polygon masks.

Usage: Comfy's Python moss-quality-analyze.py ROOT annotations.json
The first two scenes select a candidate; remaining scenes are held out.
Requires numpy/Pillow, no torch, GPU, backend or desktop connection.
"""
import json
import os
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

LAYERS = dict(l4=[4], early=[0,4,8], middle=[12,20,28], late=[28,36,41], all=[0,4,8,12,20,28,36,41])
BANDS = dict(early=(0,10), middle=(10,20), late=(20,30), all=(0,30))


def normalize(x):
    lo,hi=np.quantile(x,[.05,.99],axis=(-2,-1),keepdims=True)
    return np.clip((x-lo)/np.maximum(hi-lo,1e-12),0,1)


def metrics(plane,mask):
    scores=plane.ravel(); truth=mask.ravel().astype(bool)
    # Threshold groups avoid optimistic AP when quantization/clipping ties scores.
    order=np.argsort(-scores,kind='stable'); sorted_scores=scores[order]; labels=truth[order]
    ends=np.r_[np.nonzero(np.diff(sorted_scores))[0],len(scores)-1]
    tp=np.cumsum(labels)[ends]; precision=tp/(ends+1); recall=tp/max(1,truth.sum())
    ap=float(np.sum(np.diff(np.r_[0,recall])*precision))
    predicted=normalize(plane)>=.5
    iou=float((predicted&mask).sum()/max(1,(predicted|mask).sum()))
    maxima=scores==scores.max()
    hit=float(truth[maxima].mean())
    return dict(ap=ap,iou=iou,pointing=hit)


def candidates(data):
    for method in ['dot','cosine','centered']:
        for layer_name,layers in LAYERS.items():
            for band,(lo,hi) in BANDS.items():
                entries=[v for k,v in data.items() if k.split('_')[0]==method and int(k.split('_')[1][5:]) in layers and lo<=int(k.split('_')[2][4:])<hi]
                stack=np.stack(entries)
                name=f'{method}/{layer_name}/{band}'
                mean=stack.mean(0)
                yield name,mean,stack
                if len(stack)>1:
                    # An experimental stability gate, not confidence calibration.
                    stable=normalize(mean)*(normalize(stack)>=.5).mean(0)
                    yield name+'/agreement',stable,stack


def mean_metrics(rows):
    return {k:float(np.mean([r[k] for r in rows])) for k in ['ap','iou','pointing']}


def main():
    root=Path(sys.argv[1]); annotations=json.loads(Path(sys.argv[2]).read_text())
    output=root/'analysis';output.mkdir(exist_ok=True)
    evaluated={};planes={};stacks={};scene_info={}
    for scene,info in annotations.items():
        doc=json.loads((root/'output'/(scene+'.json')).read_text())
        data=dict(np.load(root/'output'/(scene+'.npz')))
        words=list(doc['spans']);size=next(iter(data.values())).shape[-1]
        assert all(len(doc['spans'][word])==1 for word in info['polygons']), 'Evaluate single-token targets to match Painter normalization exactly'
        masks={}
        for word,polygon in info['polygons'].items():
            mask=Image.new('L',(size,size));ImageDraw.Draw(mask).polygon([(x*size,y*size) for x,y in polygon],fill=1)
            for hole in info.get('holes',{}).get(word,[]):
                ImageDraw.Draw(mask).polygon([(x*size,y*size) for x,y in hole],fill=0)
            masks[word]=np.array(mask,dtype=bool)
        scene_info[scene]=(words,masks)
        for name,mean,stack in candidates(data):
            planes[scene,name]=mean;stacks[scene,name]=stack
            rows=[]
            for word,mask in masks.items():
                rows.append(dict(word=word,**metrics(mean[words.index(word)],mask)))
            evaluated.setdefault(name,{})[scene]=rows
    scenes=list(annotations);train=scenes[:2];test=scenes[2:]
    scores={name:dict(train=mean_metrics([r for s in train for r in by_scene[s]]),
                           test=mean_metrics([r for s in test for r in by_scene[s]])) for name,by_scene in evaluated.items()}
    ordered=sorted(scores,key=lambda n:(-scores[n]['train']['ap'],n))
    best=ordered[0];baseline='dot/l4/middle'
    # Show a best cosine, best centered and the overall train-selected winner.
    shown=[baseline]
    for prefix in ['cosine/','centered/']:
        chosen=next(n for n in ordered if n.startswith(prefix))
        if chosen not in shown:shown.append(chosen)
    if best not in shown:shown.append(best)
    if 'dot/early/middle' not in shown:shown.append('dot/early/middle')
    report=dict(selection='Mean pixel AP on first two scenes only; remaining scenes held out.',
                annotation='Image-only approximate polygons; object colors share noun masks. No boundary benchmark or general attribution claim.',
                baseline=baseline,selected=best,shown=shown,ranking=[dict(name=n,**scores[n]) for n in ordered],details=evaluated)
    # Per-word raw amplitude and temporal/layer agreement are kept separately.
    diagnostics={}
    for scene in scenes:
        words,masks=scene_info[scene]
        diagnostics[scene]={}
        for name in shown:
            raw=stacks[scene,name]
            flat=raw.reshape(len(raw),len(words),-1)
            centered=flat-flat.mean(-1,keepdims=True)
            unit=centered/np.maximum(np.linalg.norm(centered,axis=-1,keepdims=True),1e-12)
            corr=np.einsum('twp,swp->wts',unit,unit)
            offdiag=~np.eye(len(raw),dtype=bool)
            diagnostics[scene][name]={word:dict(raw_mean=float(flat[:,i].mean()),raw_std=float(flat[:,i].std()),
                 capture_correlation=float(corr[i][offdiag].mean()) if offdiag.any() else None) for i,word in enumerate(words)}
    report['diagnostics']=diagnostics
    if len(scenes)>4:
        report['followup']=dict(
            protocol='Early-layer ensemble nominated after fruit tests; room/desk generated and annotated next, before inspecting their maps.',
            scenes=scenes[4:], candidate='dot/early/middle',
            scores={name:mean_metrics([r for s in scenes[4:] for r in evaluated[name][s]])
                    for name in [baseline,'dot/early/middle']})
    (output/'report.json').write_text(json.dumps(report,indent=2))
    # One row per noun; matched colors are evaluated numerically too.
    tile=320;header=48;rows=sum(len(info['nouns']) for info in annotations.values())
    canvas=Image.new('RGB',((len(shown)+1)*tile,rows*(tile+header)+70),'#15191f');draw=ImageDraw.Draw(canvas)
    fontpath=os.environ.get('MOSS_STUDY_FONT','DejaVuSans.ttf')
    try:font=ImageFont.truetype(fontpath,15);title=ImageFont.truetype(fontpath,22)
    except OSError:font=ImageFont.load_default(size=15);title=ImageFont.load_default(size=22)
    draw.text((14,15),'MOSS heatmap accuracy experiment — 64×64 maps',font=title,fill='white')
    row=0
    for scene,info in annotations.items():
        original=Image.open(next((root/'output').glob(scene+'_*.png'))).convert('RGB').resize((tile,tile))
        words,masks=scene_info[scene]
        for word in info['nouns']:
            y=70+row*(tile+header)
            draw.text((8,y+4),f'{scene}: {word} — '+('selection' if scene in train else 'held out'),font=font,fill='white')
            annotated=original.copy();d=ImageDraw.Draw(annotated)
            poly=[(x*tile,y*tile) for x,y in info['polygons'][word]]
            d.line(poly+[poly[0]],fill='#00ff99',width=2)
            for hole in info.get('holes',{}).get(word,[]):
                poly=[(x*tile,y*tile) for x,y in hole]
                d.line(poly+[poly[0]],fill='#00ff99',width=2)
            canvas.paste(annotated,(0,y+header))
            for col,name in enumerate(shown,1):
                plane=normalize(planes[scene,name][words.index(word)])
                heat=np.stack([np.clip(1.5-abs(4*plane-3),0,1),np.clip(1.5-abs(4*plane-2),0,1),np.clip(1.5-abs(4*plane-1),0,1)],-1)
                overlay=Image.fromarray((heat*255).astype('uint8')).resize((tile,tile),Image.Resampling.BILINEAR)
                composed=Image.blend(original,overlay,.55)
                canvas.paste(composed,(col*tile,y+header))
                score=next(r for r in evaluated[name][scene] if r['word']==word)
                draw.text((col*tile+8,y+4),name,font=font,fill='white')
                draw.text((col*tile+8,y+25),f"AP {score['ap']:.3f} · IoU {score['iou']:.3f}",font=font,fill='white')
            row+=1
    canvas.save(output/'comparison.png')
    # A compact current/candidate view for the realistic follow-up scenes.
    if len(scenes)>4:
        indices=[0,1,shown.index('dot/early/middle')+1]
        first_row=sum(len(annotations[s]['nouns']) for s in scenes[:4])
        count=sum(len(annotations[s]['nouns']) for s in scenes[4:])
        compact=Image.new('RGB',(tile*3,70+count*(tile+header)),'#15191f')
        cd=ImageDraw.Draw(compact)
        cd.text((12,14),'MOSS: current maps vs three early layers',font=title,fill='white')
        for row in range(count):
            y=70+row*(tile+header)
            for dest,col in enumerate(indices):
                box=(col*tile,70+(first_row+row)*(tile+header),(col+1)*tile,70+(first_row+row+1)*(tile+header))
                compact.paste(canvas.crop(box),(dest*tile,y))
                if dest:
                    cd.rectangle((dest*tile,y,(dest+1)*tile,y+23),fill='#15191f')
                    cd.text((dest*tile+8,y+4),'Current: layer 5' if dest==1 else 'Candidate: layers 1, 5, 9',font=font,fill='white')
        compact.save(output/'natural-comparison.png')
    print(json.dumps(dict(selected=best,baseline=scores[baseline],winner=scores[best],shown={n:scores[n] for n in shown}),indent=2))


def self_test():
    mask=np.array([[1,0],[0,0]],dtype=bool)
    assert metrics(mask.astype(float),mask)==dict(ap=1.,iou=1.,pointing=1.)
    assert metrics(np.zeros((2,2)),mask)['ap']==.25
    assert metrics(np.zeros((2,2)),mask)['pointing']==.25
    assert metrics(1-mask.astype(float),mask)['ap']==.25
    ramp=np.arange(16,dtype=float).reshape(4,4)
    assert np.allclose(normalize(ramp),normalize(ramp*12-34))
    assert not normalize(np.ones((4,4))).any()
    print('PASS: perfect/tied/reversed AP, tied pointing, affine normalization, flat maps')


if __name__=='__main__':
    if sys.argv[1:]==['--self-test']:self_test()
    else:main()

"""Measure response of a synthetic horizontal wave using isolated GPU history."""
import ctypes as C
import math
import os
from pathlib import Path
assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(Path(__file__).resolve().parent/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_get.argtypes=[C.c_char_p];lib.gf_get.restype=C.c_double
lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_headless_history.argtypes=[C.POINTER(C.c_float)]
lib.gf_headless_fill.argtypes=[C.c_float]
w,h=320,180
assert lib.gf_headless(w,h),'Surfaceless EGL required'
def set_(n,v):assert lib.gf_set(n.encode(),v),lib.gf_error()
def frame(ms,level):
    pcm=(C.c_float*550)(*([level]*550))
    assert lib.gf_headless_fill(0)
    assert lib.gf_frame(pcm,ms,0),lib.gf_error()
    pixels=(C.c_float*(w*h))();assert lib.gf_headless_history(pixels)
    column=[pixels[y*w+w//2] for y in range(h)]
    assert sum(column)>.1
    return sum(y*v for y,v in enumerate(column))/sum(column)
def run(response,times):
    assert lib.gf_init(w,h),lib.gf_error()
    try:
        assert lib.gf_get(b'waveResponse')==0
        for k,v in [('waveResponse',response),('particles',0),('paused',1),('normalize',0),('sensitivity',1),('grid',320),('steps',550),('waveSmoothing',0),('minWidth',3),('softness',1),('flowSpeed',0),('frameSeed',42)]:set_(k,v)
        assert lib.gf_get(b'waveResponse')==response
        assert lib.gf_preset_recall(ord('W'),b'Simple_Horizontal',42,0)
        start=frame(0,0)
        positions=[frame(t,.3) for t in times]
        return start,positions
    finally:lib.gf_close()
try:
    start,instant=run(0,[10,20,40,80,120])
    start,soft=run(120,[10,20,40,80,120])
    target=instant[-1];distance=target-start
    assert abs(distance)>10,(start,target)
    fractions=[(p-start)/distance for p in soft]
    for t,fraction in zip([10,20,40,80,120],fractions):
        assert abs(fraction-(1-math.exp(-3*t/120)))<.025,(t,fraction)
    assert max(instant)-min(instant)<.05
    assert 0<fractions[0]<.4 and .92<fractions[-1]<.98
    print('PASS: 0 ms responds immediately; 120 ms eases through intermediate positions to ~95%')
    endpoints=[]
    for fps in (30,60,120):
        times=sorted({round(i*1000/fps) for i in range(1,20) if round(i*1000/fps)<120}|{120})
        _,positions=run(120,times);endpoints.append(positions[-1])
    assert max(endpoints)-min(endpoints)<.05,endpoints
    _,irregular=run(120,[5,5,21,78,120])
    assert abs(irregular[-1]-endpoints[0])<.05
    assert abs(irregular[0]-irregular[1])<.05
    print('PASS: response timing matches at 30/60/120 FPS, irregular paints and repeated timestamps')
    _,gap=run(120,[10,500])
    assert abs(gap[-1]-target)<.05
    print('PASS: long suspension snaps to current geometry instead of dragging stale history')
finally:lib.gf_headless_close()

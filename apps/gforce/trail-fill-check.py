"""Synthetic trail spacing and timing; surfaceless EGL, no audio or window."""
import ctypes as C
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
pcm=(C.c_float*550)()
assert lib.gf_headless(w,h), 'Surfaceless EGL required'
def set_(n,v):assert lib.gf_set(n.encode(),v),lib.gf_error()
def history():
    p=(C.c_float*(w*h))();assert lib.gf_headless_history(p);return list(p)
def run(fill,draw=True):
    assert lib.gf_init(w,h),lib.gf_error()
    try:
        assert lib.gf_get(b'trailFill')==1
        for n,v in [('trailFill',fill),('grid',320),('particles',0),('paused',1),('transitionLo',0),('transitionHi',0),('flowSpeed',4),('minWidth',1),('softness',.25),('persist',.99),('fadeBias',0),('frameSeed',123),('drawLines',int(draw))]:set_(n,v)
        assert lib.gf_get(b'trailFill')==fill
        assert lib.gf_preset_recall(ord('W'),b'Simple_Horizontal',123,0)
        assert lib.gf_preset_recall(ord('D'),b'SOLs_Base',123,0)
        if not draw: assert lib.gf_headless_fill(.625)
        for frame in range(61): assert lib.gf_frame(pcm,frame*33,0),lib.gf_error()
        clocks=tuple(lib.gf_get(n) for n in (b'elapsedSteps',b'waveLength',b'particleLength'))
        state=(C.c_long*6)();lib.gf_control_state(state)
        return history(),clocks,state[5]
    finally:lib.gf_close()
try:
    counts=[]; reference=None
    for fill in (1,2,4,8):
        pixels,clocks,ms=run(fill)
        if reference is None:reference=(clocks,ms)
        assert (clocks,ms)==reference,'fill changed engine time or wave geometry'
        # Count lit rows in the moving trail below/above the source line.
        rows=[max(pixels[y*w+w//2-8:y*w+w//2+8]) for y in range(h)]
        count=sum(v>.02 for v in rows);counts.append(count)
        print(f'fill {fill}: {count} lit rows; elapsed steps {clocks[0]:.2f}',flush=True)
    assert counts[-1]>counts[0]*1.2,counts
    assert counts==sorted(counts),counts
    print('PASS: added impressions fill trail gaps without advancing engine time or changing source geometry')
    low,_,_=run(1,False);high,_,_=run(8,False)
    assert low==high,'fill changed decay with line emission disabled'
    print('PASS: carried trail decay is independent of fill')
finally:lib.gf_headless_close()

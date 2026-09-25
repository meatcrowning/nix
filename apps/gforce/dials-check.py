"""Offscreen check of the dial API: surfaceless EGL, synthetic audio, no window."""
import ctypes as C, math, sys, os
assert os.environ.get("QT_QPA_PLATFORM")=="offscreen"
assert not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
from pathlib import Path
ROOT=Path(__file__).resolve().parent
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(ROOT/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_set.argtypes=[C.c_char_p,C.c_double]; lib.gf_get.argtypes=[C.c_char_p]; lib.gf_get.restype=C.c_double
lib.gf_get_interval.restype=C.c_char_p; lib.gf_set_interval.argtypes=[C.c_int,C.c_char_p]
W,H=640,360
assert lib.gf_headless(W,H), 'surfaceless EGL failed'
assert lib.gf_init(W,H), lib.gf_error()
pcm=(C.c_float*550)()
buf=(C.c_ubyte*(W*H*4))()
def run(n,t0):
    for i in range(n):
        for k in range(550): pcm[k]=.4*math.sin((t0+i)*.3+k*.05)*math.sin(k*.011*(1+i%7))
        assert lib.gf_frame(pcm,(t0+i)*33,0), lib.gf_error()
    lib.gf_finish(); lib.gf_read(buf,W,H)
    return sum(1 for i in range(0,len(buf),4) if buf[i]|buf[i+1]|buf[i+2]>40)/(W*H)
fails=0
def check(label,cond):
    global fails; fails+=not cond; print(('ok  ' if cond else 'FAIL'),label)
base=run(90,0)
print(f'coverage default {base:.3f}')
for name,val in [('persist',.5),('fadeBias',.02),('widthScale',3),('minWidth',4),('softness',3),('sensitivity',2.5),('steps',400),('transitionLo',2),('transitionHi',9),('normalize',1),('particles',0)]:
    assert lib.gf_set(name.encode(),val), lib.gf_error()
    got=lib.gf_get(name.encode())
    want=val/2*2 if name!='minWidth' else val
    check(f'{name} set {val} -> get {got:.4f}',abs(got-want)<1e-4)
short=run(60,90)
print(f'coverage with dials {short:.3f}')
check('dials change the picture',abs(short-base)>.002)
for kind,expr in [('W','3 + rnd( 4 )'),('D','5 + rnd( 1 )'),('C','2 + rnd( 2 )'),('P','1 + rnd( 1 )'),('R','2.000*.09/((NUM_PARTICLES+1)^1.66)')]:
    lib.gf_set_interval(ord(kind),expr.encode())
    check(f'interval {kind} = {lib.gf_get_interval(ord(kind)).decode()}',lib.gf_get_interval(ord(kind)).decode()==expr)
for cap in (256,1024,640):
    assert lib.gf_set(b'grid',cap), lib.gf_error()
    c=run(20,200)
    check(f'grid {cap}: renders, coverage {c:.3f}',lib.gf_get(b'grid')==cap and c>0)
check('unknown dial refused',lib.gf_set(b'nope',1)==0)
lib.gf_close(); lib.gf_headless_close()
sys.exit(1 if fails else 0)

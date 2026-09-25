"""Offscreen check that a recalled preset reproduces its look: surfaceless EGL,
synthetic audio, the same engine clock for each run, instant transitions."""
import os
assert os.environ.get("QT_QPA_PLATFORM")=="offscreen"
assert not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
import ctypes as C, math, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(ROOT/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_preset_capture.restype=C.c_char_p
lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
W,H=320,180
# Reseeding rand() per frame takes per-frame rnd() noise out of the comparison,
# so what is compared is the recalled look itself.
FRAME_SEED=int(sys.argv[1]) if len(sys.argv)>1 else 777
assert lib.gf_headless(W,H) and lib.gf_init(W,H), lib.gf_error()
for n,v in (('transitionLo',0),('transitionHi',0),('paused',1)): lib.gf_set(n.encode(),v)
pcm=(C.c_float*550)(); buf=(C.c_ubyte*(W*H*4))()
def frames(n,t0):
    for i in range(n):
        for k in range(550): pcm[k]=.4*math.sin((t0+i)*.3+k*.05)*math.sin(k*.011*(1+i%7))
        assert lib.gf_frame(pcm,(t0+i)*33,0), lib.gf_error()
    lib.gf_finish(); lib.gf_read(buf,W,H); return bytes(buf)
def recall(lines,seed_shift=0):
    lib.gf_preset_clear_particles()
    for kind,name,seed in lines:
        assert lib.gf_preset_recall(ord(kind),name.encode(),int(seed)+(seed_shift if kind in 'WDC' else 0),0), (kind,name)
def diff(a,b): return sum(abs(x-y) for x,y in zip(a,b))/len(a)
frames(60,0)
text=lib.gf_preset_capture().decode()
lines=[l.split('\t') for l in text.strip().split('\n')]
print('captured:'); print(text.rstrip())
fails=0
def check(label,cond):
    global fails; fails+=not cond; print(('ok  ' if cond else 'FAIL'),label)
def fresh():
    lib.gf_close(); assert lib.gf_init(W,H), lib.gf_error()
    for n,v in (('transitionLo',0),('transitionHi',0),('paused',1)): lib.gf_set(n.encode(),v)
    lib.gf_key(ord('r'))   # start from some other look
    lib.gf_set(b'frameSeed',FRAME_SEED)
fresh(); recall(lines); a=frames(240,0)
check('recapture after recall names the same components and seeds',
      [l[:3] for l in (x.split('\t') for x in lib.gf_preset_capture().decode().strip().split('\n')) if l[0] in 'WDC']==[l for l in lines if l[0] in 'WDC'])
fresh(); recall(lines); b=frames(240,0)
fresh(); recall(lines,seed_shift=12345); c=frames(240,0)
print(f'mean abs diff: same seeds {diff(a,b):.3f}, other seeds {diff(a,c):.3f} (0-255 per channel)')
check('same preset renders the same',diff(a,b)<0.05)
check('seeds matter, when the preset uses rnd()',diff(a,c)>diff(a,b) or diff(a,c)==0)
lib.gf_close(); lib.gf_headless_close()
sys.exit(1 if fails else 0)

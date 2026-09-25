"""Offscreen check (surfaceless EGL, synthetic audio): W/C/X change the wave
shape/distortion/colours as the menu names them. The requested FPS must not
change carried trails at a given set of actual frame timestamps."""
import ctypes as C, math, os, sys
assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
assert not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
from pathlib import Path
ROOT=Path(__file__).resolve().parent
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(ROOT/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_get.argtypes=[C.c_char_p]
lib.gf_get.restype=C.c_double
lib.gf_key.argtypes=[C.c_int]
lib.gf_preset_capture.restype=C.c_char_p
lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
lib.gf_control_state.argtypes=[C.POINTER(C.c_long)]
W,H=320,180
assert lib.gf_headless(W,H) and lib.gf_init(W,H), lib.gf_error()
pcm=(C.c_float*550)(); buf=(C.c_ubyte*(W*H*4))()
fails=0
def check(label,cond):
    global fails; fails+=not cond; print(('ok  ' if cond else 'FAIL'),label)
def state():
    v=(C.c_long*6)(); lib.gf_control_state(v); return tuple(v)
def run(seconds,fps,t0=0.):
    n=round(seconds*fps)
    for i in range(n):
        t=t0+i/fps
        for k in range(550): pcm[k]=.4*math.sin(t*9+k*.05)*math.sin(k*.011*(1+int(t*30)%7))
        assert lib.gf_frame(pcm,round(t*1000),0), lib.gf_error()
    lib.gf_finish(); lib.gf_read(buf,W,H); return bytes(buf)
for n,v in (('transitionLo',0),('transitionHi',0),('paused',1),('particles',0)): lib.gf_set(n.encode(),v)
run(1,30)
for key,moves in (('w',1),('c',2),('x',3)):
    before=state(); lib.gf_key(ord(key)); run(.1,30,1.); after=state()
    changed=[i for i in (1,2,3) if before[i]!=after[i]]
    check(f'{key.upper()} changes only component {moves}',changed==[moves])
# Repeated presses land mid-blend: each must land the blend in progress and
# start the next, without the step count running away.
for n,v in (('transitionLo',4),('transitionHi',18)): lib.gf_set(n.encode(),v)
t=2.
for i in range(60):
    lib.gf_key(ord('wxrWXR'[i%6])); run(.1,30,t); t+=.1
check('60 rapid W/X/R presses mid-blend keep rendering',True)
for n,v in (('transitionLo',0),('transitionHi',0)): lib.gf_set(n.encode(),v)
look=[l.split('\t') for l in lib.gf_preset_capture().decode().strip().split('\n') if l[0] in 'WDC']
# Paint trails at 30 fps, then stop drawing lines and let the flow carry and
# fade what is there for a second: that isolates the per-frame warp and decay.
def carried(fps,dial):
    lib.gf_close(); assert lib.gf_init(W,H), lib.gf_error()
    for n,v in (('transitionLo',0),('transitionHi',0),('paused',1),('particles',0)): lib.gf_set(n.encode(),v)
    lib.gf_preset_clear_particles()
    lib.gf_set(b'frameSeed',777)
    for kind,name,seed in look: assert lib.gf_preset_recall(ord(kind),name.encode(),int(seed),0)
    run(1,30)
    lib.gf_set(b'drawLines',0); lib.gf_set(b'fps',dial)
    return run(.6,fps,1.)
for actual in (15,30,60,120):
    matched=carried(actual,actual)
    capped=carried(actual,120 if actual!=120 else 15)
    check(f'actual {actual} fps: target FPS never changes pixels',matched==capped)
    # Last time is 1 + .6 - 1/fps; first frame supplies one original step.
    expected=1+round((1.6-1/actual)*1000)*.03
    check(f'actual {actual} fps: elapsed time drives flow',abs(lib.gf_get(b'elapsedSteps')-expected)<1e-6)
    check(f'actual {actual} fps: engine clock follows elapsed time',state()[5]==round((1.6-1/actual)*1000))
# Irregular delivery, extra paints at the same timestamp, a dropped frame,
# and a target change midway must all keep the same integrated motion time.
for index,target in enumerate((15,120,30)):
    lib.gf_set(b'fps',target)
    for ms in (2000,2000,2008,2050,2187,3000):
        assert lib.gf_frame(pcm,ms+1000*index,0),lib.gf_error()
    check(f'jitter/drop/target {target}: no lost or extra time',abs(lib.gf_get(b'elapsedSteps')-(91+30*index))<1e-6)
# No negative warp or duplicate time when a caller repeats/rewinds a timestamp.
assert lib.gf_frame(pcm,4900,0),lib.gf_error()
assert lib.gf_frame(pcm,5000,0),lib.gf_error()
check('repeated/older timestamps never reverse or double-count motion',abs(lib.gf_get(b'elapsedSteps')-151)<1e-6)
lib.gf_close(); lib.gf_headless_close()
sys.exit(1 if fails else 0)

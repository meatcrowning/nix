"""Surfaceless check for the audioOnly dial: with it on, no shape or particle
whose equations skip mag()/fft() is shown; with it off, they come back."""
import ctypes as C
import math
import os
from pathlib import Path
import re

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
root=Path(__file__).resolve().parent
def static(folder):
    out=set()
    for f in (root/'data'/folder).iterdir():
        s=re.sub(r'/\*.*?\*/|//[^\n]*','',f.read_text(errors='replace'),flags=re.S)
        if not re.search(r'\b(mag|fft)\s*\(',s,re.I):
            out.add(f.name.replace('_',' '))
    return out
still={'W':static('GForceWaveShapes'),'P':static('GForceParticles')}
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(root/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_set_interval.argtypes=[C.c_int,C.c_char_p]
lib.gf_preset_capture.restype=C.c_char_p
lib.gf_key.argtypes=[C.c_int]
assert lib.gf_headless(320,240), 'No surfaceless EGL; refusing fallback'
assert lib.gf_init(320,240),lib.gf_error()
pcm=(C.c_float*550)(*(.3*math.sin(i*.08) for i in range(550)))
def seen(t0,t1):
    names={'W':set(),'P':set()}
    for t in range(t0,t1,333):
        assert lib.gf_frame(pcm,t,0),lib.gf_error()
        if t%3000<333: lib.gf_key(ord('r'))
        for line in lib.gf_preset_capture().decode().splitlines():
            k,name,_=line.split('\t')
            if k in names: names[k].add(name)
    return names
try:
    # Other isolated harnesses may have saved particles off in .G-Force.
    lib.gf_set(b'paused',0)
    lib.gf_set(b'particles',1)
    lib.gf_set_interval(ord('W'),b'1 + rnd( 1 )')
    lib.gf_set_interval(ord('R'),b'5')
    lib.gf_set(b'audioOnly',1)
    on=seen(0,600000)
    lib.gf_set(b'audioOnly',0)
    off=seen(600000,1200000)
    for k in 'WP':
        bad=on[k]&still[k]
        assert not bad,(k,bad)
        assert off[k]&still[k],(k,'none of the non-reactive ones came back')
    print(f"PASS: on shows {len(on['W'])} shapes/{len(on['P'])} particles, none of {len(still['W'])}+{len(still['P'])} non-reactive; off shows {len(off['W']&still['W'])}+{len(off['P']&still['P'])} of them again")
finally:
    lib.gf_close()
    lib.gf_headless_close()

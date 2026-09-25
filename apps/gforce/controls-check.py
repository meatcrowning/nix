"""Synthetic-audio, surfaceless regression for randomize and change pause."""
import ctypes as C
import math
import os
from pathlib import Path

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(Path(__file__).resolve().parent/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_control_state.argtypes=[C.POINTER(C.c_long)]
lib.gf_control_state.restype=None
lib.gf_key.argtypes=[C.c_int]
lib.gf_key.restype=None
assert lib.gf_headless(640,480), 'No surfaceless EGL; refusing fallback'
assert lib.gf_init(640,480),lib.gf_error()
pcm=(C.c_float*550)(*(.3*math.sin(i*.08) for i in range(550)))
def state():
    values=(C.c_long*6)()
    lib.gf_control_state(values)
    return tuple(values)
def frame(t):
    assert lib.gf_frame(pcm,t,0),lib.gf_error()
try:
    frame(0)
    assert state()[0]==0
    lib.gf_key(ord(' '))
    before=state()
    assert before[0]==1
    for t in range(33,120001,333):
        frame(t)
        assert state()[1:5]==before[1:5],(before,state())
    assert state()[5]>119000, 'Pause stopped animation time'
    for key in ('r','R','r'):
        before=state()
        lib.gf_key(ord(key))
        after=state()
        assert after[0]==1
        assert all(a!=b for a,b in zip(before[1:5],after[1:5]))
        frame(120033)
    held=state()[1:5]
    for t in range(120066,240001,333):
        frame(t)
        assert state()[1:5]==held
    lib.gf_key(ord(' '))
    assert state()[0]==0
    changed=False
    for t in range(240033,480001,333):
        frame(t)
        changed |= state()[1:5]!=held
    assert changed,'Automatic changes failed to resume'
    print('PASS: pause holds components, animation advances, R/r reroll all four while paused, Space resumes automatic changes')
finally:
    lib.gf_close()
    lib.gf_headless_close()

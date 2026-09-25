"""Verify live connection override at low detail using surfaceless EGL."""
import ctypes as C
import os
from pathlib import Path
assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(Path(__file__).resolve().parent/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_get.argtypes=[C.c_char_p];lib.gf_get.restype=C.c_double
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
lib.gf_headless_fill.argtypes=[C.c_float]
pcm=(C.c_float*550)();ms=0
assert lib.gf_headless(320,180) and lib.gf_init(320,180),lib.gf_error()
def set_(n,v):assert lib.gf_set(n.encode(),v),lib.gf_error()
def frame():
    global ms
    ms+=16
    assert lib.gf_headless_fill(0)
    assert lib.gf_frame(pcm,ms,0),lib.gf_error()
    return lib.gf_get(b'lineLength')
try:
    assert lib.gf_get(b'forceConnect')==0
    for n,v in [('particles',0),('paused',1),('steps',16),('flowSpeed',0),('frameSeed',77)]:set_(n,v)
    assert lib.gf_preset_recall(ord('W'),b'DT_-_SineDot',77,0)
    assert frame()==0,'dot preset should have zero-length segments'
    set_('forceConnect',1);assert frame()>50
    set_('forceConnect',0);assert frame()==0,'off must restore original point mode'
    print('PASS: low-detail dot wave gains connecting lines; disabling restores dots')
    assert lib.gf_preset_recall(ord('W'),b'Simple_Horizontal',77,0)
    normal=frame();set_('forceConnect',1);connected=frame()
    assert abs(normal-connected)<1e-5
    print('PASS: presets already drawing lines retain their geometry')
    set_('forceConnect',0);set_('particles',1)
    assert lib.gf_preset_recall(ord('P'),b'Cycling_Dots',77,0)
    frame();assert lib.gf_get(b'particleLength')==0
    set_('forceConnect',1);frame();assert lib.gf_get(b'particleLength')>0
    set_('forceConnect',0);frame();assert lib.gf_get(b'particleLength')==0
    print('PASS: particle presets also obey the reversible override')
finally:lib.gf_close();lib.gf_headless_close()

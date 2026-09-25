"""Surfaceless layer-scale independence and high-resolution map regression."""
import ctypes as C
import math,os,time
from pathlib import Path
assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(Path(__file__).resolve().parent/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_get.argtypes=[C.c_char_p];lib.gf_get.restype=C.c_double
lib.gf_select.argtypes=[C.c_int,C.c_char_p]
lib.gf_headless_fill.argtypes=[C.c_float]
lib.gf_headless_history.argtypes=[C.POINTER(C.c_float)]
lib.gf_choices.argtypes=[C.c_int];lib.gf_choices.restype=C.c_char_p
pcm=(C.c_float*550)(*(.3*math.sin(i*.07) for i in range(550)))
w,h=320,180
assert lib.gf_headless(w,h) and lib.gf_init(w,h),lib.gf_error()
def set_(n,v):assert lib.gf_set(n.encode(),v),lib.gf_error()
def get(n):return lib.gf_get(n.encode())
def frame(t=10):
    set_('frameSeed',777)
    assert lib.gf_frame(pcm,t,0),lib.gf_error()
try:
    for n,v in [('paused',1),('transitionLo',0),('transitionHi',0),('sceneScale',1)]:set_(n,v)
    assert lib.gf_select(ord('W'),b'Simple_Horizontal')
    assert lib.gf_select(ord('P'),b'Spinners')
    frame();set_('masterSpeed',0);frame()
    wave,particle=get('waveLength'),get('particleLength')
    assert wave>0 and particle>0,(wave,particle)
    set_('waveScale',.5);frame()
    assert abs(get('waveLength')/wave-.5)<1e-5
    assert abs(get('particleLength')/particle-1)<1e-5
    set_('particleScale',.25);frame()
    assert abs(get('particleLength')/particle-.25)<1e-5
    assert abs(get('waveLength')/wave-.5)<1e-5
    set_('distortionScale',2);frame()
    assert get('waveScale')==.5 and get('particleScale')==.25
    assert abs(get('waveLength')/wave-.5)<1e-5
    assert abs(get('particleLength')/particle-.25)<1e-5
    print('PASS: wave, particle and distortion scale changes are independent')
    for n,v in [('drawLines',0),('masterSpeed',1),('persist',1),('fadeBias',0)]:set_(n,v)
    buf=(C.c_float*(w*h))()
    choices=lib.gf_choices(ord('D')).decode().splitlines()
    start=time.monotonic()
    set_('grid',2048)
    assert get('grid')==2048 and get('fieldWidth')==2048 and get('fieldHeight')==1152
    for i,name in enumerate(choices[::30]):
        assert lib.gf_select(ord('D'),name.encode())
        assert lib.gf_headless_fill(.625)
        frame(100+i*33)
        assert lib.gf_headless_history(buf)
        assert min(buf)>.62 and max(buf)<.63,name
    print(f'PASS: 2048×1152 maps preserve every output pixel across {len(choices[::30])} representative presets ({time.monotonic()-start:.2f}s total)')
    set_('grid',99999);assert get('grid')==2048
    set_('grid',640);assert get('grid')==640
    frame(500)
    print('PASS: map limit clamps and returns to default without a render-size change')
finally:
    lib.gf_close();lib.gf_headless_close()

"""Surfaceless regressions for distortion coverage and full-frame scene scale."""
import ctypes as C
import os
from pathlib import Path
assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(Path(__file__).resolve().parent/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_get.argtypes=[C.c_char_p];lib.gf_get.restype=C.c_double
lib.gf_choices.argtypes=[C.c_int];lib.gf_choices.restype=C.c_char_p
lib.gf_select.argtypes=[C.c_int,C.c_char_p]
lib.gf_headless_fill.argtypes=[C.c_float]
lib.gf_headless_history.argtypes=[C.POINTER(C.c_float)]
pcm=(C.c_float*550)()
w,h=320,180;now=0
assert lib.gf_headless(400,400) and lib.gf_init(w,h),lib.gf_error()
def set_(n,v):assert lib.gf_set(n.encode(),v),lib.gf_error()
def frame():
    global now
    now+=33
    assert lib.gf_frame(pcm,now,0),lib.gf_error()
def history():
    buf=(C.c_float*(w*h))()
    assert lib.gf_headless_history(buf),lib.gf_error()
    return list(buf)
try:
    for name,value in [('grid',128),('particles',0),('paused',1),('drawLines',0),('persist',1),('fadeBias',0)]:set_(name,value)
    presets=lib.gf_choices(ord('D')).decode().splitlines()
    for preset in presets:
        assert lib.gf_select(ord('D'),preset.encode()),preset
        assert lib.gf_headless_fill(.625)
        frame()
        pixels=history()
        assert min(pixels)>.62 and max(pixels)<.63,(preset,min(pixels),max(pixels))
    print(f'PASS: all {len(presets)} distortions preserve filled history at every pixel, including edges')
    for grid in (256,640,1024):
        set_('grid',grid)
        for preset in presets[::30]:
            assert lib.gf_select(ord('D'),preset.encode())
            assert lib.gf_headless_fill(.625)
            frame();assert min(history())>.62,(grid,preset)
    print('PASS: representative distortions retain coverage through field detail 1024')
    set_('grid',128)
    for w,h in [(93,167),(320,180)]:
        assert lib.gf_resize(w,h),lib.gf_error()
        for scale in [.25,.5,1,2,3]:
            set_('sceneScale',scale)
            for preset in presets[::max(1,len(presets)//8)]:
                assert lib.gf_select(ord('D'),preset.encode()),preset
                assert lib.gf_headless_fill(.625)
                frame()
                assert min(history())>.62,(w,h,scale,preset)
    print('PASS: scene scale 0.25–3x preserves full-frame flow in landscape and portrait')
    # Measure the line footprint, independently of field/palette behaviour.
    set_('drawLines',1);set_('flowSpeed',0);set_('transitionLo',0);set_('transitionHi',0)
    assert lib.gf_select(ord('W'),b'Simple_Horizontal')
    frame();frame()
    spans=[]
    for scale in [.25,.5,1]:
        set_('sceneScale',scale)
        # Finish the one-shot history zoom before measuring a clean new wave.
        frame();assert lib.gf_headless_fill(0)
        frame();pixels=history()
        xs=[i%w for i,p in enumerate(pixels) if p>.05]
        assert xs
        spans.append(max(xs)-min(xs)+1)
    assert abs(spans[0]/spans[2]-.25)<.04 and abs(spans[1]/spans[2]-.5)<.04,spans
    # Existing history must survive scale changes even with simulation stopped.
    set_('masterSpeed',0);set_('drawLines',0)
    assert lib.gf_headless_fill(.625)
    for scale in [3,.25,1]:
        set_('sceneScale',scale);frame()
        assert min(history())>.62
    print(f'PASS: wave widths scale around centre ({spans}); carried history survives paused scale edits')
finally:
    lib.gf_close();lib.gf_headless_close()

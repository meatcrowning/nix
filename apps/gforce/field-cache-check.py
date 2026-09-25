"""Check field revisions against actual map bytes across remaps and swaps."""
import ctypes as C
import math
import os

assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
# The renderer's verifier retains the old byte comparison only for this test.
os.environ['GF_VERIFY_FIELD']='1'
lib=C.CDLL(os.environ['GF_RENDERER_PATH'])
lib.gf_error.restype=C.c_char_p
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
lib.gf_set_interval.argtypes=[C.c_int,C.c_char_p]
lib.gf_selection.argtypes=[C.c_int];lib.gf_selection.restype=C.c_char_p
lib.gf_resize.argtypes=[C.c_int,C.c_int]
pcm=(C.c_float*550)(*[.3*math.sin(i*.11) for i in range(550)])
def set_(name,value):assert lib.gf_set(name.encode(),value),lib.gf_error()
def recall(name):assert lib.gf_preset_recall(ord('D'),name.encode(),77,0),lib.gf_error()
assert lib.gf_headless(320,180)
try:
    assert lib.gf_init(320,180),lib.gf_error()
    for name,value in [('grid',640),('particles',0),('paused',1),('frameSeed',77)]:set_(name,value)
    recall('SOLs_Base')
    fields=set()
    for n in range(650):
        if n==105:set_('distortionScale',1.12)
        if n==115:set_('distortionScale',.975)
        if n==125:set_('grid',1024)
        if n==135:set_('grid',640)
        if n==145:recall('SOLs_Base')
        if n==165:recall('Watery_Ripples')
        if n==180:recall('SOLs_Base')
        if n==215:assert lib.gf_resize(240,180),lib.gf_error()
        if n==230:assert lib.gf_resize(320,180),lib.gf_error()
        if n==245:
            set_('grid',128)
            set_('paused',0)
            lib.gf_set_interval(ord('D'),b'.01')
            lib.gf_set_interval(ord('W'),b'10000')
            lib.gf_set_interval(ord('C'),b'10000')
        assert lib.gf_frame(pcm,n*13,0),lib.gf_error()
        if n>=245:fields.add(lib.gf_selection(ord('D')))
    assert len(fields)>2,fields
    lib.gf_finish()
    print('PASS: field revisions preserve map bytes across reloads, remaps, resizing and automatic swaps')
finally:
    lib.gf_close();lib.gf_headless_close()

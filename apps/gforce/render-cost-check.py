"""Fixed synthetic scene benchmark; surfaceless EGL, no live display or audio access."""
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import time
assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
root=Path(__file__).resolve().parent
lib=C.CDLL(os.environ.get('GF_TEST_LIBRARY',os.environ.get('GF_RENDERER_PATH',str(root/'renderer.so'))))
lib.gf_error.restype=C.c_char_p
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
lib.gf_read.argtypes=[C.POINTER(C.c_ubyte),C.c_int,C.c_int]
w,h=1080,900
pcm=(C.c_float*550)(*[.3*math.sin(i*.11) for i in range(550)])
assert lib.gf_headless(w,h),'Surfaceless EGL required'
results=[]
try:
    for scale,fill in ((1,1),(2,1),(2,6)):
        assert lib.gf_init(w,h),lib.gf_error()
        try:
            for k,v in [('resolution',scale),('trailFill',fill),('grid',2048),('particles',0),('paused',1),('normalize',0),('sensitivity',5),('steps',550),('waveSmoothing',12),('flowSpeed',1.1),('frameSeed',77)]:assert lib.gf_set(k.encode(),v)
            for kind,name in [('W','DT_-_Circle_III'),('D','SOLs_Base'),('C','DT_-_Ocean_Club')]:assert lib.gf_preset_recall(ord(kind),name.encode(),77,0)
            for n in range(100):assert lib.gf_frame(pcm,n*13,0),lib.gf_error()
            lib.gf_finish();start=time.monotonic()
            for n in range(100,220):assert lib.gf_frame(pcm,n*13,0),lib.gf_error()
            lib.gf_finish();ms=(time.monotonic()-start)*1000/120
            buf=(C.c_ubyte*(w*h*4))();lib.gf_read(buf,w,h)
            result={'scale':scale,'fill':fill,'ms':round(ms,3),'pixels':hashlib.sha256(bytes(buf)).hexdigest()};results.append(result)
            print(result,flush=True)
        finally:lib.gf_close()
finally:lib.gf_headless_close()
if os.environ.get('GF_TEST_RESULTS'):Path(os.environ['GF_TEST_RESULTS']).write_text(json.dumps(results))

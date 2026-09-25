import ctypes as C
import math
import os
import time
from pathlib import Path
from PySide6.QtGui import QImage

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('WAYLAND_DISPLAY') and not os.environ.get('DISPLAY')
ROOT=Path(__file__).resolve().parent
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(ROOT/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_fft_check.restype=C.c_double
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_read.argtypes=[C.POINTER(C.c_ubyte),C.c_int,C.c_int]
fft_error=lib.gf_fft_check()
assert fft_error < 1e-6, fft_error
print('FFT matches direct transform: max error',fft_error,flush=True)
assert lib.gf_headless(1920,1200), 'Surfaceless EGL failed; refusing fallback'
assert lib.gf_init(640,480), lib.gf_error()
pcm=(C.c_float*550)()
try:
    elapsed=0
    for w,h in [(640,480),(1280,800),(1733,977),(1920,1200),(431,713)]:
        assert lib.gf_resize(w,h),lib.gf_error()
        started=time.monotonic()
        for frame in range(240):
            for i in range(550):
                t=elapsed/1000+i/22050
                pcm[i]=.25*math.sin(t*2*math.pi*220)+.15*math.sin(t*2*math.pi*83)+.05*math.cos(t*2*math.pi*1760)
            assert lib.gf_frame(pcm,elapsed,0),lib.gf_error()
            elapsed+=33
        lib.gf_finish()
        duration=time.monotonic()-started
        pixels=(C.c_ubyte*(w*h*4))()
        lib.gf_read(pixels,w,h)
        image=QImage(bytes(pixels),w,h,w*4,QImage.Format.Format_RGBA8888).mirrored(False,True)
        image.save(str(Path(os.environ['GF_BUILD_CACHE'])/f'check-{w}x{h}.png'))
        colours={bytes(pixels[i:i+3]) for i in range(0,w*h*4,400)}
        print(f'{w}x{h}: {duration/240*1000:.2f} ms/frame incl synthetic audio; {len(colours)} sampled colours',flush=True)
        assert len(colours)>8,'Blank render'
finally:
    lib.gf_close()
    lib.gf_headless_close()

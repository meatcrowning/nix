"""Measure circular joins and open endpoints without a display or audio device."""
import ctypes as C
import math
import os

assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
lib=C.CDLL(os.environ['GF_RENDERER_PATH'])
lib.gf_error.restype=C.c_char_p
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_get.argtypes=[C.c_char_p];lib.gf_get.restype=C.c_double
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
lib.gf_headless_wave_endpoints.argtypes=[C.POINTER(C.c_float)]
assert lib.gf_headless(640,640)
try:
    for wave in ('DT_-_Circle_II','DT_-_Circle_III','Simple_Horizontal'):
        for forced in (0,1):
            for points in (16,200,550):
                assert lib.gf_init(640,640),lib.gf_error()
                try:
                    for key,value in [('grid',640),('particles',0),('paused',1),('steps',points),('forcePoints',forced),('forceConnect',1),('waveSmoothing',12),('waveResponse',0),('flowSpeed',0)]:
                        assert lib.gf_set(key.encode(),value),lib.gf_error()
                    assert lib.gf_preset_recall(ord('W'),wave.encode(),77,0)
                    pcm=(C.c_float*550)(*[.3*math.sin(i*.11) for i in range(550)])
                    for n in range(20):assert lib.gf_frame(pcm,n*13,0),lib.gf_error()
                    p=(C.c_float*8)()
                    assert lib.gf_headless_wave_endpoints(p)
                    gap=math.hypot(p[6]-p[0],p[7]-p[1])
                    assert lib.gf_get(b'waveSegments')==points-1
                    if wave=='Simple_Horizontal':
                        assert gap>600,'open wave must not be joined'
                    else:
                        assert gap<.001,(wave,forced,points,gap)
                        a=(p[2]-p[0],p[3]-p[1]);b=(p[6]-p[4],p[7]-p[5])
                        dot=sum(x*y for x,y in zip(a,b))/(math.hypot(*a)*math.hypot(*b))
                        angle=math.degrees(math.acos(max(-1,min(1,dot))))
                        print(f'{wave} forced={forced} points={points}: gap={gap:.6f}px turn={angle:.2f}deg')
                        if points==200:assert angle<20,(wave,angle)
                        if points==550:assert angle<5,(wave,angle)
                finally:lib.gf_close()
    print('PASS: circles include their closing point, high-detail joins stay smooth, open waves stay open')
finally:lib.gf_headless_close()

"""Synthetic-audio/surfaceless regression. Run only in an isolated extraction."""
import ctypes as C
import math
import os
from pathlib import Path
from array import array
from audio_window import AudioWindow
assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
root=Path(__file__).resolve().parent
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(root/'renderer.so')))
lib.gf_error.restype=C.c_char_p
lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
lib.gf_set.argtypes=[C.c_char_p,C.c_double]
lib.gf_get.argtypes=[C.c_char_p];lib.gf_get.restype=C.c_double
lib.gf_choices.argtypes=lib.gf_selection.argtypes=[C.c_int]
lib.gf_choices.restype=lib.gf_selection.restype=lib.gf_preset_capture.restype=C.c_char_p
lib.gf_select.argtypes=[C.c_int,C.c_char_p]
lib.gf_set_interval.argtypes=[C.c_int,C.c_char_p]
lib.gf_control_state.argtypes=[C.POINTER(C.c_long)]
pcm=(C.c_float*550)(*(.4*math.sin(i*.8)+.2*math.sin(i*2.5) for i in range(550)))
def set_(name,value): assert lib.gf_set(name.encode(),value),lib.gf_error()
def get(name): return lib.gf_get(name.encode())
def frame(ms): assert lib.gf_frame(pcm,ms,0),lib.gf_error()
def state():
    out=(C.c_long*6)();lib.gf_control_state(out);return tuple(out)
def names(k): return lib.gf_choices(ord(k)).decode().splitlines()
def selected(k): return lib.gf_selection(ord(k)).decode()
def select(k,name): assert lib.gf_select(ord(k),name.encode()),(k,name,lib.gf_error())
def particle_count(): return lib.gf_preset_capture().decode().count('P\t')
assert lib.gf_headless(640,360), 'No surfaceless EGL; refusing fallback'
assert lib.gf_init(320,180),lib.gf_error()
try:
    set_('paused',1);set_('particles',0)
    frame(0)
    for n,v in [('masterSpeed',2),('waveSpeed',.5),('particleSpeed',.25),('colourSpeed',4)]: set_(n,v)
    frame(1000)
    assert state()[5]==2000
    for name,value in [('waveTime',1),('particleTime',.5),('colourTime',8)]: assert abs(get(name)-value)<1e-6
    set_('masterSpeed',.5);set_('fps',120)
    frame(2000)
    assert state()[5]==2500
    for name,value in [('waveTime',1.25),('particleTime',.625),('colourTime',10)]: assert abs(get(name)-value)<1e-6
    set_('waveSpeed',4);frame(2000)
    assert abs(get('waveTime')-1.25)<1e-6,'changing speed jumped the clock'
    set_('masterSpeed',0);frame(3000)
    assert state()[5]==2500 and abs(get('waveTime')-1.25)<1e-6
    print('PASS: independent clocks, continuous speed edits, master zero, FPS independence')
    for kind in 'WDCP':
        choices=names(kind);assert len(choices)>1
        before={k:selected(k) for k in 'WDCP'}
        target=next(n for n in choices if n!=before[kind])
        select(kind,target)
        assert selected(kind)==target
        assert all(selected(k)==v for k,v in before.items() if k!=kind)
    assert not lib.gf_select(ord('W'),b'not-an-installed-preset')
    lib.gf_key(ord('n')); before=selected('P');lib.gf_key(ord('n'))
    assert selected('P')!=before and state()[0]==1 and particle_count()==1
    lib.gf_key(ord('p'))
    assert not get('particles') and particle_count()==0
    lib.gf_key(ord('p'))
    assert get('particles') and particle_count()==1,'toggle on must show a particle while paused'
    set_('particles',0);lib.gf_key(ord('r'))
    assert not get('particles') and particle_count()==0,'randomise ignored particles off'
    set_('audioOnly',1)
    assert set(names('P')) and len(names('P'))<len(list((Path(os.environ.get('GF_RENDERER_PATH',str(root/'renderer.so'))).parent/'data/GForceParticles').iterdir()))
    set_('audioOnly',0)
    print('PASS: named selectors, independent selections, N/P, off clears, on visible while paused, filtering')
    set_('transitionLo',0);set_('transitionHi',0)
    select('W','Simple_Horizontal')
    # Finish the minimum 1ms transition, then freeze a deterministic waveform.
    set_('masterSpeed',1);frame(3010);set_('masterSpeed',0)
    set_('steps',550);set_('waveSmoothing',0);frame(3010)
    jagged=get('lineLength')
    set_('waveSmoothing',8);frame(3010)
    smooth=get('lineLength')
    assert smooth<jagged*.8,(jagged,smooth)
    assert get('steps')==550
    for n in [0,.1,1.3,4.9,5,8,12]:set_('waveSmoothing',n);frame(3010)
    print(f'PASS: smoothing retains 550 points; path length {jagged:.1f} -> {smooth:.1f}; full smoothing range')
    set_('drawLines',0);set_('flowSpeed',0);set_('persist',1);set_('fadeBias',0)
    buf=(C.c_ubyte*(320*180*4))()
    frame(3010);lib.gf_read(buf,320,180)
    original=sum(buf[0::4])+sum(buf[1::4])+sum(buf[2::4])
    assert original>0
    for scale in (.5,1,1.5,2,1):
        set_('resolution',scale)
        assert get('renderWidth')==320*scale and get('renderHeight')==180*scale
        frame(3010);lib.gf_read(buf,320,180)
        brightness=sum(buf[0::4])+sum(buf[1::4])+sum(buf[2::4])
        assert brightness>original*.2,'resolution change cleared trails'
    assert lib.gf_resize(480,270),lib.gf_error()
    assert get('renderWidth')==480 and get('renderHeight')==270
    frame(3010)
    for name in ('masterSpeed','resolution','waveSmoothing'): assert not lib.gf_set(name.encode(),float('nan'))
    print('PASS: render scale 0.5–2x, resize follows output, trails survive reallocations, invalid values refused')
    set_('masterSpeed',1);set_('particleSpeed',0)
    lib.gf_set_interval(ord('P'),b'1 + rnd( 0 )')
    select('P','Spinners')
    frame(10000)
    assert particle_count()==1,'zero particle speed must hold its lifetime as well as T'
    set_('particleSpeed',1);frame(20000)
    assert particle_count()==0,'particle lifetime clock did not resume'
    print('PASS: particle T and END_TIME stay in the same time domain')
finally:
    lib.gf_close();lib.gf_headless_close()

hit=array('f',[.8]*550).tobytes();quiet=array('f',[0]*550).tobytes()
a=AudioWindow();a.feed(hit+quiet,1.)
assert max(a.sample(1.,0))==0
assert max(a.sample(1.,100))>.5,'hit earlier in the read was discarded'
assert max(a.sample(1.05,100))>.2
assert max(a.sample(1.3,100))==0
b=AudioWindow();b.feed(hit[:19],1.);b.feed(hit[19:]+quiet,1.)
c=AudioWindow();c.feed(hit+quiet,1.)
for t in (1.,1.01,1.02,1.03):b.sample(t,100)
assert b.sample(1.04,100)==c.sample(1.04,100),'hold depends on number of paints'
assert len(b.pending)==0
print('PASS: brief-hit hold/release, earlier hit in a pipe read, byte alignment, FPS-independent hold')

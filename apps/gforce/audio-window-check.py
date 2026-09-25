"""Synthetic PCM checks; no Qt, capture process, or audio devices."""
from array import array
from audio_window import AudioWindow

# Byte-split reads must expose complete samples before a full window arrives.
a=AudioWindow()
data=array('f',range(1200)).tobytes()
for i in range(0,len(data),19):
    end=min(i+19,len(data))
    a.feed(data[i:end],end/4/a.RATE)
    count=end//4
    expected=tuple([0.]*max(0,a.SIZE-count)+list(map(float,range(max(0,count-a.SIZE),count))))
    assert a.sample(end/4/a.RATE,0)==expected
    assert len(a.pending)<4 and len(a.hold_pending)<a.SIZE
assert a.latest==tuple(map(float,range(650,1200)))
print('PASS: partial reads, immediate updates, sample order, bounded buffers')

# Model 5 ms capture delivery with independent frame clocks. Every frame must
# see the newest delivered samples at all supported representative rates.
for fps in (15,30,60,76,120):
    a=AudioWindow(); delivered=0; tick=0; previous=-1
    for frame in range(1,fps+1):
        now=frame/fps
        while (tick+1)*.005<=now+1e-10:
            tick+=1
            end=round(tick*.005*a.RATE)
            a.feed(array('f',range(delivered,end)).tobytes(),tick*.005)
            delivered=end
        samples=a.sample(now,0)
        assert samples[-1]==delivered-1 and samples[-1]>previous
        if delivered>=a.SIZE:
            assert samples==tuple(map(float,range(delivered-a.SIZE,delivered)))
        previous=samples[-1]
    print(f'PASS: fresh rolling audio on every frame at {fps} FPS')

# Preserve brief-hit retention and frame-independent release.
hit=array('f',[.8]*550).tobytes(); quiet=array('f',[0]*550).tobytes()
a=AudioWindow(); a.feed(hit+quiet,1.)
assert max(a.sample(1.,0))==0
assert max(a.sample(1.,100))>.5
assert max(a.sample(1.05,100))>.2
assert max(a.sample(1.3,100))==0
b=AudioWindow(); b.feed(hit[:19],1.); b.feed(hit[19:]+quiet,1.)
c=AudioWindow(); c.feed(hit+quiet,1.)
for t in (1.,1.01,1.02,1.03): b.sample(t,100)
assert b.sample(1.04,100)==c.sample(1.04,100)
assert len(b.pending)==0
print('PASS: batched hits, byte alignment, time-based hold/release')
a.feed(array('f',[float('nan'),float('inf'),-float('inf')]).tobytes(),2.)
assert a.latest[-3:]==(0.,0.,0.)
print('PASS: nonfinite PCM is sanitized')

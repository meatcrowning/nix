"""Rolling display PCM and optional peak hold; no audio device or playback."""
from array import array
from collections import deque
import math

class AudioWindow:
    SIZE=550
    RATE=22050

    def __init__(self):
        self.pending=bytearray()
        self.recent=deque()
        self.window=deque((0.,)*self.SIZE,maxlen=self.SIZE)
        self.hold_pending=[]
        self.latest=(0.,)*self.SIZE

    def feed(self,chunk,now):
        self.pending.extend(chunk)
        # Publish every complete float immediately. Overlapping windows retain
        # the engine's 550-sample span without limiting updates to ~40 Hz.
        size=len(self.pending)//4*4
        pcm=array('f',self.pending[:size])
        del self.pending[:size]
        pcm=[v if math.isfinite(v) else 0. for v in pcm]
        if pcm:
            self.window.extend(pcm)
            self.latest=tuple(self.window)
        # Peak hold still evaluates every non-overlapping block, including
        # transient hits earlier in a batched read. Its timing is independent
        # of both paint frequency and capture chunk boundaries.
        self.hold_pending.extend(pcm)
        blocks=len(self.hold_pending)//self.SIZE
        for i in range(blocks):
            start=i*self.SIZE
            block=tuple(self.hold_pending[start:start+self.SIZE])
            stamp=now-(len(self.hold_pending)-start-self.SIZE)/self.RATE
            energy=sum(v*v for v in block)/self.SIZE
            self.recent.append((stamp,energy,block))
        del self.hold_pending[:blocks*self.SIZE]
        self.prune(now)

    def prune(self,now):
        while self.recent and self.recent[0][0]<now-.3:
            self.recent.popleft()

    def sample(self,now,hold_ms):
        self.prune(now)
        if hold_ms<=0 or not self.recent:
            return self.latest
        # A time-based release, not a frame count: 60 FPS and 15 FPS hold the
        # same transient for the same duration. New stronger hits win at once.
        tau=hold_ms/1000.
        candidates=[(energy*math.exp(-2*max(0.,now-stamp)/tau),stamp,pcm)
                    for stamp,energy,pcm in self.recent if now-stamp<=tau]
        if not candidates:
            return self.latest
        _,stamp,pcm=max(candidates,key=lambda x:x[0])
        gain=math.exp(-max(0.,now-stamp)/tau)
        if sum(v*v for v in self.latest)>=sum(v*v for v in pcm)*gain*gain:
            return self.latest
        return tuple(v*gain for v in pcm)

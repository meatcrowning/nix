"""Audio sinks for the receiver: PipeWire playback, UDP stream, WAV recorder."""

import json
import socket
import subprocess
import time
import wave
from pathlib import Path

import numpy as np

RATE = 48000


def output_devices():
    """[(node.name, description)] of PipeWire's audio sinks, default first."""
    try:
        dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, timeout=5).stdout or b"[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    sinks, default = [], None
    for obj in dump:
        info = obj.get("info") or {}
        props = info.get("props") or {}
        if obj.get("type", "").endswith("Node") and props.get("media.class") == "Audio/Sink":
            sinks.append((props.get("node.name", ""), props.get("node.description") or props.get("node.name", "")))
        if obj.get("type", "").endswith("Metadata") and props.get("metadata.name") == "default":
            for item in obj.get("metadata") or []:
                if item.get("key") == "default.audio.sink":
                    value = item.get("value")
                    default = value.get("name") if isinstance(value, dict) else None
    sinks.sort(key=lambda s: s[0] != default)
    return sinks


class Playback:
    """Float32 stereo frames into pw-cat. A dead pipe is reopened on next write."""

    def __init__(self, target=None):
        self.target = target
        self.proc = None

    def _open(self):
        cmd = ["pw-cat", "--playback", "--raw", "--format", "f32", "--rate", str(RATE),
               "--channels", "2", "--latency", "60ms", "--media-role", "Music",
               "-P", '{ node.name = "tuner" node.description = "Tuner" application.name = "Tuner" '
                     'application.icon-name = "gqrx" }']
        if self.target:
            cmd += ["--target", self.target]
        self.proc = subprocess.Popen(cmd + ["-"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def write(self, frames):
        if self.proc is None or self.proc.poll() is not None:
            self._open()
        try:
            self.proc.stdin.write(np.ascontiguousarray(frames, dtype="<f4").tobytes())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.close()

    def set_target(self, target):
        if target != self.target:
            self.target = target
            self.close()

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


class UdpStream:
    """gqrx's UDP audio: 48 kHz signed 16-bit, mono or interleaved stereo."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = None

    def send(self, frames, host, port, stereo):
        try:
            if self.addr is None or self.addr[0] != (host, port):
                self.addr = ((host, port), socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4])
            data = frames if stereo else frames.mean(axis=1)
            pcm = (np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()
            for i in range(0, len(pcm), 1024):  # gqrx sends small datagrams
                self.sock.sendto(pcm[i:i + 1024], self.addr[1])
        except OSError:
            self.addr = None


class Recorder:
    def __init__(self, directory, freq, mode):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = Path(directory).expanduser() / ("tuner_%s_%d_%s.wav"
                                                     % (stamp, freq, mode.replace(" ", "").replace("(", "-").replace(")", "")))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.wav = wave.open(str(self.path), "wb")
        self.wav.setnchannels(2)
        self.wav.setsampwidth(2)
        self.wav.setframerate(RATE)
        self.frames = 0

    def write(self, frames):
        self.wav.writeframes((np.clip(frames, -1, 1) * 32767).astype("<i2").tobytes())
        self.frames += len(frames)

    def close(self):
        self.wav.close()
        return self.path, self.frames / RATE

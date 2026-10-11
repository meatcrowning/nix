"""Play Ubuntu's ready drums from ly's start/logout hooks, without a desktop.

Use the built-in analog playback PCM, by ALSA card ID rather than a changing
card number. Do not change mixer levels or fall back to HDMI/controller audio.
The greeter has no user PipeWire server on a cold boot.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import syslog
import time

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())


def analog_device(proc=Path("/proc/asound")):
    for line in (proc / "pcm").read_text().splitlines():
        match = re.match(r"(\d+)-(\d+):.*\bAnalog\b.*\bplayback\b", line, re.I)
        if match:
            card, device = map(int, match.groups())
            name = (proc / ("card%d" % card) / "id").read_text().strip()
            if re.fullmatch(r"[A-Za-z0-9_]+", name):
                return "plughw:CARD=%s,DEV=%d" % (name, device)
    raise RuntimeError("No built-in analog playback PCM; greeter sound skipped")


def greeter_active():
    def query(*args):
        return subprocess.run([CONFIG["loginctl"], *args], capture_output=True, text=True,
                              check=True, timeout=2).stdout.strip()
    session = query("show-seat", "seat0", "--property=ActiveSession", "--value")
    return not session or query("show-session", session, "--property=Class", "--value") == "greeter"


def main():
    if sys.argv[1:] != ["--worker"]:
        # ly waits for hook commands. Detach just the bounded playback worker,
        # so starting the greeter never waits for an audio device.
        subprocess.Popen([sys.executable, str(HERE / "greeter-sound.py"), "--worker"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return
    time.sleep(.3)
    try:
        device = analog_device()
        for _ in range(24):
            if not greeter_active():
                return
            result = subprocess.run([CONFIG["aplay"], "-q", "-D", device, str(HERE / "system-ready.wav")],
                                    env={"PATH": "/nonexistent", "LANG": "C"}, capture_output=True,
                                    text=True, timeout=4)
            if result.returncode == 0:
                return
            if "Device or resource busy" not in result.stderr:
                raise RuntimeError(result.stderr.strip())
            # PipeWire may need to release its idle PCM after logout. Never
            # seize it or replay the drums once a new user session starts.
            time.sleep(.25)
        raise RuntimeError("Analog PCM is still busy after logout")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        syslog.openlog("unity-quantal-greeter-sound")
        syslog.syslog(syslog.LOG_WARNING, str(error))


if __name__ == "__main__":
    main()

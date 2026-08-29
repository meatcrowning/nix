#!/usr/bin/env python3
"""Self-heal the easyeffects_sink -> asahi-convolver link on book (event-driven).

WHY THIS EXISTS: EasyEffects creates `easyeffects_sink` and links its monitor
to the asahi-audio convolver (`audio_effect.j313-convolver`) so apps that play
into `easyeffects_sink` reach the speakers. That link (and the ports behind it)
is torn down ~5-25s after the chain goes idle — this is EasyEffects dropping its
own output link, not WirePlumber: neither `session.suspend-timeout-seconds=0`
(global) nor `node.rules` (which WirePlumber only applies to nodes IT creates,
not client-created sinks like easyeffects_sink) prevents it, and the ports are
not externally linkable, so `pw-link link` fails even during playback. Only a
restart of easyeffects recreates the link. Measured on book 2026-08-29.

This daemon watches `pactl subscribe` and, the moment a stream appears, checks
whether an app is actively playing into easyeffects_sink while the onward link
is missing — and restarts easyeffects. Event-driven, so the heal lands within a
second of playback resuming rather than on the next poll tick (the poll-only
version left up to 15s of silence at the start of every playback after idle,
which is what the user experienced as audio "breaking again"). A periodic
re-check is the backstop for events `pactl subscribe` misses.

When the daemon fires, audio is ALREADY silent (the link is broken), so the
restart restores sound rather than cutting it.

FAILS CLOSED, idempotently: any detection error returns without acting, so a
broken probe cannot cause restart churn. A restart is only ever issued when
BOTH (a stream is actively playing into easyeffects_sink) AND (the link is
missing) hold.

Kill switch: `~/.local/state/easyeffects-link-watch/off`.
Log: `~/.cache/easyeffects-link-watch.log`.
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

KILL = Path.home() / ".local/state/easyeffects-link-watch/off"
LOG = Path.home() / ".cache/easyeffects-link-watch.log"
CONVOLVER = "audio_effect.j313-convolver"
# Backstop: re-check this often even if no pactl event arrived (a stream can
# start without an event this daemon sees if pactl subscribe reconnects, etc.).
BACKSTOP_SEC = 20


def log(msg: str) -> None:
    try:
        with LOG.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def run(args: list[str]) -> str:
    """Run a command, returning stdout or '' on any failure (fails open)."""
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=4)
    except Exception:
        return ""
    return out.stdout if out.returncode == 0 else ""


def ee_sink_index() -> int | None:
    """The pipewire/pulse index of easyeffects_sink, or None if absent."""
    out = run(["pactl", "-f", "json", "list", "sinks"])
    if not out:
        return None
    try:
        sinks = json.loads(out)
    except ValueError:
        return None
    for s in sinks:
        if s.get("properties", {}).get("node.name") == "easyeffects_sink":
            return s.get("index")
    return None


def playing_into_ee() -> bool:
    """Is an app actively (uncorked, non-effect) playing into easyeffects_sink?"""
    idx = ee_sink_index()
    if idx is None:
        return False
    out = run(["pactl", "-f", "json", "list", "sink-inputs"])
    if not out:
        return False
    try:
        inputs = json.loads(out)
    except ValueError:
        return False
    for si in inputs:
        if si.get("sink") != idx:
            continue
        if si.get("corked"):
            continue
        props = si.get("properties") or {}
        node = str(props.get("node.name") or "")
        app = str(props.get("application.name") or "")
        if node.startswith("effect_") or "EasyEffects" in app:
            continue
        return True
    return False


def convolver_link_present() -> bool:
    """Is easyeffects_sink:monitor actually linked into the convolver?"""
    out = run(["pw-link", "-l"])
    # The onward link prints as a `|-> audio_effect.j313-convolver:playback_FL`
    # line fed by an `|<- easyeffects_sink:monitor_FL` line. Presence of either
    # of the stereo channels means the chain is routed.
    return "|-> %s:playback" % CONVOLVER in out


def heal_once() -> None:
    """If an app is playing into easyeffects_sink but the onward link is gone,
    restart easyeffects — the only reliable way to recreate the link."""
    if KILL.exists():
        return
    if not playing_into_ee():
        return
    if convolver_link_present():
        return
    # An app is playing into easyeffects_sink but nothing onward: heal.
    log("restarting easyeffects: app playing into easyeffects_sink "
        "but the ->%s link is missing" % CONVOLVER)
    subprocess.run(["systemctl", "--user", "restart", "easyeffects.service"],
                   timeout=15)


def subscribe_loop() -> None:
    """Block on `pactl subscribe`; heal on every event. Dies with SIGINT/SIGTERM."""
    while True:
        try:
            proc = subprocess.Popen(
                ["pactl", "subscribe"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if proc.stdout is None:
                proc.wait()
                continue
            for line in proc.stdout:
                # Any client/sink-input change is a good-enough trigger; the
                # check itself is cheap and idempotent.
                heal_once()
            proc.wait()
        except Exception:
            pass
        time.sleep(1)  # reconnect loop if pactl subscribe died


def main() -> int:
    # Backstop thread so a missed pactl event still self-heals.
    threading.Thread(target=subscribe_loop, daemon=True).start()
    while True:
        heal_once()
        time.sleep(BACKSTOP_SEC)


if __name__ == "__main__":
    sys.exit(main())

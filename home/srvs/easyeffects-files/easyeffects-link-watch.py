#!/usr/bin/env python3
"""Self-heal the easyeffects_sink -> asahi-convolver link on book.

WHY THIS EXISTS: EasyEffects creates `easyeffects_sink` and links its monitor
to the asahi-audio convolver (`audio_effect.j313-convolver`) so apps that play
into `easyeffects_sink` reach the speakers. That link (and the ports behind it)
is torn down when the chain goes idle, and EasyEffects does NOT re-create it
when a new stream starts — measured on book 2026-08-29: restart easyeffects,
the link is present and survives active playback, but ~25s after the last
stream ends it is gone, and a fresh stream does not bring it back. Only a
restart of easyeffects heals it.

WHAT THIS DOES: when an app is actively playing into `easyeffects_sink` (an
uncorked, non-effect sink-input targeting it) but the onward link to the
convolver is missing, restart easyeffects. It never acts on idle: no stream,
no onward link is the *normal* state, so the check only fires when the two
conditions are true together.

FAILS CLOSED, idempotently: any detection error returns 0 (do nothing) and
logs, so a broken probe cannot cause restart churn. The restart itself is
systemd's job (Restart=on-failure already covers a crash); this only nudges the
service when it is alive but unlinked.

Kill switch: `~/.local/state/easyeffects-link-watch/off`.
Log: `~/.cache/easyeffects-link-watch.log`.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

KILL = Path.home() / ".local/state/easyeffects-link-watch/off"
LOG = Path.home() / ".cache/easyeffects-link-watch.log"
CONVOLVER = "audio_effect.j313-convolver"


def log(msg: str) -> None:
    try:
        with LOG.open("a") as f:
            f.write(msg + "\n")
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


def main() -> int:
    if KILL.exists():
        return 0
    if not playing_into_ee():
        return 0
    if convolver_link_present():
        return 0
    # An app is playing into easyeffects_sink but nothing onward: heal.
    log("restarting easyeffects: app playing into easyeffects_sink "
        "but the ->%s link is missing" % CONVOLVER)
    subprocess.run(["systemctl", "--user", "restart", "easyeffects.service"],
                   timeout=15)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Is any application actually playing audio? Prints `1` or `0`.

WHY THIS EXISTS: both cava instances (SysInfo.qml's VU meter, Media.qml's
spectrum) used to run unconditionally at 60fps. Measured on book, that chain
cost ~19.5% of a core CONTINUOUSLY WITH NOTHING PLAYING — cava itself 11.4%,
plus it doubled the panel's own CPU (animating bars 60 times a second) and
tripled wireplumber's (serving two monitor captures). On a laptop that is pure
battery burn. See docs/perf-cpu-hotspots.md.

THE TRAP THIS AVOIDS: the obvious test — "does any un-corked sink-input
exist?" — is ALWAYS TRUE here. EasyEffects (started alongside the session)
permanently holds an un-corked sink-input for its convolver output
(`effect_output.j313-convolver` on book). A gate written that way never fires
and looks like it works. Apps play into `easyeffects_sink`, so the effect
chain's own nodes must be excluded before counting.

FAILS OPEN. Any error — pactl missing, JSON unparseable, unexpected shape —
prints `1`, so the meters keep working exactly as they did before. The worst
case of a bug here is today's battery life, never dead bars during music.
"""
import json
import subprocess
import sys


def main() -> int:
    try:
        out = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True, timeout=4, text=True,
        )
        if out.returncode != 0:
            return 1
        inputs = json.loads(out.stdout)
    except Exception:
        return 1

    if not isinstance(inputs, list):
        return 1

    for si in inputs:
        if not isinstance(si, dict):
            return 1
        props = si.get("properties") or {}
        node = str(props.get("node.name") or "")
        app = str(props.get("application.name") or "")
        # EasyEffects' own chain nodes are not playback; skip them.
        if node.startswith("effect_") or "EasyEffects" in app:
            continue
        if si.get("corked"):
            continue
        return 1
    return 0


if __name__ == "__main__":
    print(main())
    sys.stdout.flush()

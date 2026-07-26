#!/usr/bin/env python3
"""push-windows.py <edge> <reserve_px>

Push floating windows out from under the panel after it grows.

Hyprland's exclusive zone only reflows TILED windows, and this desktop is
essentially all floating (hyprvtb draws the titlebars and remembers per-class
geometry), so widening the panel into dock mode would simply cover whatever was
sitting on that side of the screen. This walks the floating windows and moves
any that now overlap the reserved strip back into the visible area.

Only ever called when the panel GROWS — shrinking it uncovers windows, and
"restoring" them afterwards would fight hyprvtb's own geometry memory.

Dispatchers under Hyprland's Lua config are `hl.dsp.*` OBJECTS handed to
`hyprctl dispatch`, not bare dispatcher names (a bare name is a nil global and
silently does nothing). The pixel movers are:

    hl.dsp.window.move  ({ window = "address:0x..", x = X, y = Y })   absolute
    hl.dsp.window.resize({ window = "address:0x..", x = W, y = H })   absolute

RESIZE BEFORE MOVE: resizing re-anchors the window itself, so a move issued
first is immediately undone by the resize that follows.
"""

import json
import subprocess
import sys


def hypr(*args):
    out = subprocess.run(["hyprctl", "-j", *args],
                         capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else []


def main():
    edge = sys.argv[1] if len(sys.argv) > 1 else "right"
    try:
        reserve = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    except ValueError:
        return
    if reserve <= 0 or edge not in ("left", "right"):
        return

    monitors = {m["id"]: m for m in hypr("monitors")}
    if not monitors:
        return

    cmds = []
    for c in hypr("clients"):
        # Tiled windows are already handled by the exclusive zone. `hidden`
        # windows are hyprvtb's rolled-up/minimized ones, parked off-screen on
        # purpose — moving them would drag them back into view and lose the
        # position the plugin restores them to. Negative workspace ids are
        # special/scratch workspaces, which aren't part of the desktop layout.
        if not c.get("floating") or not c.get("mapped"):
            continue
        if c.get("hidden"):
            continue
        if c.get("workspace", {}).get("id", 0) < 0:
            continue

        mon = monitors.get(c.get("monitor"))
        if not mon:
            continue

        if edge == "right":
            avail_l = mon["x"]
            avail_r = mon["x"] + mon["width"] - reserve
        else:
            avail_l = mon["x"] + reserve
            avail_r = mon["x"] + mon["width"]
        avail_w = avail_r - avail_l
        if avail_w <= 0:
            continue

        x, y = c["at"]
        w, h = c["size"]
        addr = c["address"]

        # A window too wide for what's left has to shrink, or no placement can
        # keep it clear of the panel.
        new_w = min(w, avail_w)
        # Then slide it back inside: off the right first, then clamp to the left
        # (order matters for a window that is exactly avail_w wide).
        new_x = x
        if new_x + new_w > avail_r:
            new_x = avail_r - new_w
        if new_x < avail_l:
            new_x = avail_l

        if new_w != w:
            cmds.append(f'hl.dsp.window.resize({{ window = "address:{addr}", '
                        f'x = {new_w}, y = {h} }})')
        if new_x != x or new_w != w:
            cmds.append(f'hl.dsp.window.move({{ window = "address:{addr}", '
                        f'x = {new_x}, y = {y} }})')

    for c in cmds:
        subprocess.run(["hyprctl", "dispatch", c],
                       capture_output=True, text=True)


if __name__ == "__main__":
    main()

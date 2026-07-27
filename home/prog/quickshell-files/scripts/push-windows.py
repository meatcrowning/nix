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


def option(key, field):
    """One value out of `hyprctl getoption`. None if absent/unparseable."""
    out = subprocess.run(["hyprctl", "getoption", key, "-j"],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(out).get(field)
    except (ValueError, AttributeError):
        return None


def frame_extents():
    """How far the visible frame extends beyond a window's client area.

    `at`/`size` from `hyprctl clients` are the CLIENT rectangle — they do not
    include the chrome, and pushing by those alone leaves the chrome behind
    under the panel, which is the bug this exists to fix.

    hyprvtb's titlebar is VERTICAL and sits on the window's RIGHT edge
    (getPositioningInfo: DECORATION_EDGE_RIGHT, desiredExtents right =
    totalBarW() = bar_width * 2) — the same side the panel is normally on, so
    it is exactly the part that stays covered. `enabled` is a global config
    bool, not per-window, so every decorated window carries it. Hyprland's own
    border then wraps window + bar as a single frame (the deco's priority is
    above the border's), adding border_size on every side.

    Returns (extra_right, border).
    """
    border = option("general:border_size", "int") or 0
    if not option("plugin:hyprvtb:enabled", "bool"):
        return 0, border
    return (option("plugin:hyprvtb:bar_width", "int") or 0) * 2, border


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

    extra_right, border = frame_extents()
    cmds = []
    for c in hypr("clients"):
        # Tiled windows are already handled by the exclusive zone. Negative
        # workspace ids are special/scratch workspaces, not part of the layout.
        if not c.get("floating") or not c.get("mapped"):
            continue
        if c.get("workspace", {}).get("id", 0) < 0:
            continue

        mon = monitors.get(c.get("monitor"))
        if not mon:
            continue

        x, y = c["at"]
        w, h = c["size"]

        # ROLLED UP vs MINIMIZED — these are NOT the same, and hyprctl's
        # `hidden` flag means the first, not the second (vtbDeco.cpp: "A
        # minimized window is still mapped and NOT hidden — just slid
        # off-screen").
        #
        #   rolled up  -> hidden=true, but the titlebar is STILL DRAWN in place.
        #                 It is on screen, so it must be pushed clear like
        #                 anything else. Skipping these was the bug.
        #   minimized  -> not hidden; parked at monitor.x + monitor.width by
        #                 minimizeWindow(). It is deliberately off-screen and
        #                 must be left alone, or resizing the panel would haul
        #                 every minimized window back into view.
        #
        # Minimized is detected by that parked position rather than by asking
        # the plugin: nothing in hyprctl reports it, and "entirely outside the
        # monitor" is the property we actually care about anyway.
        rolled = bool(c.get("hidden"))
        if x >= mon["x"] + mon["width"] or x + w <= mon["x"]:
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

        addr = c["address"]

        # Work in VISIBLE-BOX coordinates, then convert back to the client
        # `at`/`size` the dispatchers speak.
        #
        # Rolled up, the client is not drawn at all — only the titlebar, which
        # sits just past the client's right edge (m_rollBox = {winBox.x +
        # winBox.w, y, totalBarW, h}). So its visible box is the bar alone, and
        # it must never be "resized to fit": its width is the chrome's, fixed.
        if rolled:
            vis_l = x + w
            vis_w = extra_right + border
        else:
            vis_l = x - border
            vis_w = w + extra_right + 2 * border

        # A box too wide for what's left has to shrink, or no placement can keep
        # it clear of the panel. The chrome is fixed-size, so the whole shrink
        # comes off the client area.
        new_vis_w = min(vis_w, avail_w)
        new_w = w if rolled else max(1, new_vis_w - extra_right - 2 * border)

        # Then slide it back inside: off the right first, then clamp to the left
        # (order matters for a box exactly as wide as the space).
        new_vis_l = vis_l
        if new_vis_l + new_vis_w > avail_r:
            new_vis_l = avail_r - new_vis_w
        if new_vis_l < avail_l:
            new_vis_l = avail_l
        new_x = (new_vis_l - w) if rolled else (new_vis_l + border)

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

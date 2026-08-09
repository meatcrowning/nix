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

    hyprvtb's titlebar is a strip totalBarW() = bar_width * 2 thick on ONE of
    the window's four edges (`plugin:hyprvtb:titlebar_edge`, default right —
    the same side the panel is normally on, so it is exactly the part that
    stays covered). A left/right bar runs along the window's height and adds
    to its WIDTH; a top/bottom bar runs along its width and adds to its
    HEIGHT. `enabled` is a global config bool, not per-window, so every
    decorated window carries it. Hyprland's own border then wraps window + bar
    as a single frame (the deco's priority is above the border's), adding
    border_size on every side.

    Returns (extra, border, side, vertical) — the chrome extent, the border,
    the titlebar's edge ("right"/"left"/"top"/"bottom") and whether that edge
    is a vertical one. The caller reconstructs the visible frame per side.
    """
    border = option("general:border_size", "int") or 0
    if not option("plugin:hyprvtb:enabled", "bool"):
        return 0, border, "right", True
    side = option("plugin:hyprvtb:titlebar_edge", "str") or "right"
    if side not in ("left", "top", "bottom"):
        side = "right"  # same fallback as the plugin (globals.hpp barSide())
    return (option("plugin:hyprvtb:bar_width", "int") or 0) * 2, border, side, side in ("left", "right")


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

    extra, border, bside, bvert = frame_extents()
    # The chrome sits on ONE side: a left/right bar is a VERTICAL strip and
    # adds to the window's width (on its own side); a top/bottom bar is a
    # horizontal strip and adds to its height. The push below only slides
    # horizontally, so a horizontal bar contributes nothing to the width
    # arithmetic — but it must not be counted as if it did (a top/bottom bar
    # would otherwise shrink wide windows by a bar-width it does not own).
    bar_l = extra if (bside == "left" and bvert) else 0.0
    bar_r = extra if (bside == "right" and bvert) else 0.0
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
        #   rolled up  -> hidden=true, and the titlebar is STILL DRAWN in place.
        #                 It must be pushed clear, but NOT from here: the drawn
        #                 bar sits at m_rollBox, a snapshot frozen at roll-up
        #                 time, and the window is hidden so the decoration
        #                 positioner never refreshes it. Moving the window from
        #                 outside moves nothing visible. The plugin does these
        #                 itself, via push_rolled() below — and it must be the
        #                 ONLY one that touches them, or the window gets shifted
        #                 twice for one overhang.
        #   minimized  -> not hidden; parked at monitor.x + monitor.width by
        #                 minimizeWindow(). Deliberately off-screen, so leave it
        #                 alone or resizing the panel hauls every minimized
        #                 window back into view.
        #
        # Minimized is detected by that parked position rather than by asking
        # the plugin: nothing in hyprctl reports it, and "entirely outside the
        # monitor" is the property we actually care about anyway.
        if c.get("hidden"):
            continue
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

        # Work in VISIBLE-BOX coordinates — the client rect grown by the chrome,
        # so the titlebar is pushed clear too — then convert back to the client
        # `at`/`size` the dispatchers speak. The bar extends the frame on its
        # own side only (see bar_l/bar_r above).
        vis_l = x - border - bar_l
        vis_w = w + bar_l + bar_r + 2 * border

        # A box too wide for what's left has to shrink, or no placement can keep
        # it clear of the panel. The chrome is fixed-size, so the whole shrink
        # comes off the client area.
        new_vis_w = min(vis_w, avail_w)
        new_w = max(1, new_vis_w - bar_l - bar_r - 2 * border)

        # Then slide it back inside: off the right first, then clamp to the left
        # (order matters for a box exactly as wide as the space).
        new_vis_l = vis_l
        if new_vis_l + new_vis_w > avail_r:
            new_vis_l = avail_r - new_vis_w
        if new_vis_l < avail_l:
            new_vis_l = avail_l
        new_x = new_vis_l + border + bar_l

        if new_w != w:
            cmds.append(f'hl.dsp.window.resize({{ window = "address:{addr}", '
                        f'x = {new_w}, y = {h} }})')
        if new_x != x or new_w != w:
            cmds.append(f'hl.dsp.window.move({{ window = "address:{addr}", '
                        f'x = {new_x}, y = {y} }})')

    for c in cmds:
        subprocess.run(["hyprctl", "dispatch", c],
                       capture_output=True, text=True)

    # Rolled-up windows, which only the plugin can move (see above). One call
    # sweeps every rolled bar on every monitor. A plugin action is a Lua
    # function, never a dispatcher — `hyprctl dispatch <name>` would evaluate
    # the name as a Lua expression and silently do nothing.
    subprocess.run(["hyprctl", "eval",
                    f"hl.plugin.hyprvtb.push_rolled({reserve}, '{edge}')"],
                   capture_output=True, text=True)


if __name__ == "__main__":
    main()

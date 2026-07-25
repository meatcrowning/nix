#!/usr/bin/env python3
# rgb-set.py — set every RGB device on the box to one colour (the wallpaper
# accent), so the DRAM sticks and motherboard headers follow the desktop theme.
#
#   rgb-set.py RRGGBB
#
# Called detached from wal-set.sh (step 6c). Talks to the system
# openrgb.service SDK server on 127.0.0.1:6742 (hardware.openrgb.enable in
# hosts/top/configuration.nix) — never to the hardware directly, so it can't
# fight the server over the SMBus/USB devices. If the server is down this
# exits quietly and the lights just keep their last colour.
#
# Known controllers on `top` (informational, the loop below is generic):
#   2x "ENE DRAM"                    — RAM sticks, 8 LEDs each (SMBus, slow-ish)
#   "MSI PRO B650-VC WIFI (MS-7D78)" — JRGB1/2 + JRAINBOW1/2 headers
# Physical chains (mapped by per-zone test colours, 2026-07):
#   JRAINBOW1 — CPU cooler + case fans + power button, daisy-chained
#   JRAINBOW2 — bottom case RGB strip
#   JRGB1/2   — nothing visible connected
import colorsys
import fcntl
import os
import sys

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor


def vivid(hexstr):
    """Saturate a palette colour for LED output.

    The wal palette's accents are deliberate pastels (e.g. e6cc97 is ~90%
    white) — right for text on screen, but on RGB LEDs a pastel renders as
    a washed-out near-white "tint" (tested on the box: 2x saturation was
    still read as "basically white", warm hues especially need near-full
    saturation to register as a colour at all). Keep the hue, push
    saturation hard (2.8x, capped) and value to full. Near-grey accents
    stay near-grey (2.8x of almost nothing is still almost nothing).
    """
    r, g, b = (int(hexstr[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r, g, b = colorsys.hsv_to_rgb(h, min(1.0, s * 2.8), 1.0)
    return RGBColor(round(r * 255), round(g * 255), round(b * 255))

# ARGB (addressable) headers are write-only — OpenRGB can't detect how many
# LEDs are chained on them and defaults the zone to 5, leaving everything
# past LED 5 (CPU cooler, case fans, power button...) dark. Resize them to a
# generous fixed count before colouring: LEDs beyond the physical end of the
# chain simply ignore the data, so overshooting is harmless, while the real
# hardware caps are 200 (JRAINBOW1) / 240 (JRAINBOW2). Resized on every run,
# so nothing depends on the OpenRGB server persisting sizes.
ZONE_RESIZE = {
    "JRAINBOW1": 120,
    "JRAINBOW2": 120,
}


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: rgb-set.py RRGGBB")
    color = vivid(sys.argv[1])

    # Serialise overlapping fires (rapid theme flips): same trick as
    # cursor-recolor.sh — queued runs each apply their own colour in order,
    # so the devices converge on the last theme instead of getting a mix of
    # interleaved SMBus/USB writes from two instances at once.
    lock = open(os.path.expanduser("~/.cache/wal/rgb-set.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)

    try:
        client = OpenRGBClient(name="wal-set")
    except Exception as e:
        print(f"rgb-set: OpenRGB server unavailable, skipping ({e})")
        return

    for dev in client.devices:
        try:
            # Direct = per-LED colours pushed from software, no hardware
            # effect running underneath; exactly what a static theme colour
            # wants. Fall back to Static for anything without it.
            modes = {m.name.lower(): m for m in dev.modes}
            mode = modes.get("direct") or modes.get("static")
            if mode is not None:
                dev.set_mode(mode)
            for zone in dev.zones:
                want = ZONE_RESIZE.get(zone.name)
                if want is not None and len(zone.leds) != want:
                    zone.resize(want)
            dev.set_color(color)
            print(f"rgb-set: {dev.name} -> #{sys.argv[1]} (vivid {color})")
        except Exception as e:
            print(f"rgb-set: {dev.name}: {e}")

    client.disconnect()


main()

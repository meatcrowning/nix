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
import sys

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: rgb-set.py RRGGBB")
    color = RGBColor.fromHEX(sys.argv[1])

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
            dev.set_color(color)
            print(f"rgb-set: {dev.name} -> #{sys.argv[1]}")
        except Exception as e:
            print(f"rgb-set: {dev.name}: {e}")

    client.disconnect()


main()

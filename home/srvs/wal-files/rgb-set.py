#!/usr/bin/env python3
# rgb-set.py — set every RGB device on the box to one colour (the wallpaper
# accent), so the DRAM sticks and motherboard headers follow the desktop theme.
#
#   rgb-set.py [--force] RRGGBB
#
# The automatic follow is a setting: `rgbFollowTheme` in settings.json
# (Settings -> Appearance -> rgb lighting, drawn on top only). Off means every
# automatic fire is a no-op and the lights keep their last colour; --force
# ignores it, for setting them by hand.
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
import fcntl
import json
import os
import sys

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor


def led_color(hexstr):
    """Convert a screen palette colour to LED PWM values.

    Screens encode colours with sRGB gamma; LED PWM is linear. Sending the
    palette hex raw made every colour wash toward white (which we first
    mis-fixed with big saturation boosts that turned the sandy accents
    plain yellow). Linearising each channel (^2.2) reproduces the screen
    colour's actual light balance, then BRIGHTNESS scales the emission.
    Calibrated on the box against a ladder of variants: gamma + no
    saturation boost at 30% was the closest match to the on-screen accent.
    """
    lin = ((int(hexstr[i : i + 2], 16) / 255) ** 2.2 * BRIGHTNESS for i in (0, 2, 4))
    return RGBColor(*(round(ch * 255) for ch in lin))

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

# Overall LED emission scale, 0..1 (linear light, applied after gamma in
# led_color()). These modes expose no hardware brightness knob (checked:
# brightness=None on every device) — full output was uncomfortably bright.
BRIGHTNESS = 0.30

# The desktop's one cross-app settings channel; see SettingsStore.qml.
SETTINGS = os.path.expanduser("~/.config/quickshell/settings.json")


def follows_theme():
    """Is the automatic accent push switched on? (`rgbFollowTheme`)

    The Settings window's Appearance page writes this key; wal-set.sh fires
    us on every theme change regardless, and the gate lives HERE rather than
    in that script because our own interpreter is baked by home/srvs/wal.nix
    while wal-set.sh has no json reader on its pinned PATH. Missing file or
    missing key means on — the same fail-open default the panel declares, so
    a machine that has never opened Settings behaves as it always did.
    """
    try:
        with open(SETTINGS) as f:
            return bool(json.load(f).get("rgbFollowTheme", True))
    except Exception:
        return True


def main():
    argv = [a for a in sys.argv[1:] if a != "--force"]
    forced = "--force" in sys.argv
    if len(argv) != 1:
        sys.exit("usage: rgb-set.py [--force] RRGGBB")
    # --force is for setting the lights by hand (or from a test) with the
    # automatic follow switched off; without it, off means off.
    if not forced and not follows_theme():
        print("rgb-set: rgbFollowTheme is off, leaving the lights alone")
        return
    color = led_color(argv[0])

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
            print(f"rgb-set: {dev.name} -> #{argv[0]} (led {color})")
        except Exception as e:
            print(f"rgb-set: {dev.name}: {e}")

    client.disconnect()


main()

# qutebrowser config.py — the one config file qutebrowser always reads.
#
# The desktop's "pixel font" pick lives in the Quickshell store
# (~/.config/quickshell/settings.json, fontFamily/fontSize). kitty, the hyprvtb
# titlebar and kdeglobals get it pushed live by apply-pixel-font.sh, but
# qutebrowser only reads its config at startup — there is no live font hot-swap
# for it. So this file is qutebrowser's half of that same propagation: it reads
# the pick itself on every launch, so the browser shows the current face the
# moment it opens, and follows a pick on the next start.
#
# autoconfig.yml is still the force-deployed base (colours, tabs, zoom, …):
# load it first, then override only the font keys from settings.json. Without
# load_autoconfig() a config.py would make qutebrowser IGNORE autoconfig.yml
# entirely.

import json
import os.path

config.load_autoconfig()

SETTINGS = os.path.expanduser("~/.config/quickshell/settings.json")
DEFAULT_FAMILY = "More Perfect DOS VGA"
DEFAULT_SIZE_PT = 11


def _read_pick():
    fam = DEFAULT_FAMILY
    pt = DEFAULT_SIZE_PT
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return fam, pt
    if isinstance(data.get("fontFamily"), str) and data["fontFamily"].strip():
        fam = data["fontFamily"].strip()
    px = data.get("fontSize")
    if isinstance(px, (int, float)) and not isinstance(px, bool) and px > 0:
        # settings.json fontSize is in PIXELS; qutebrowser wants points
        # (DESIGN §2.1: 15px == 11pt at 96 DPI).
        pt = round(px * 72 / 96)
    return fam, pt


_fam, _pt = _read_pick()
_mono_fam = "Oxygen Mono" if _fam == "Oxygen-Sans" else _fam
config.set("fonts.default_family", _fam)
config.set("fonts.monospace_family", _mono_fam)
config.set("fonts.default_size", "{}pt".format(_pt))

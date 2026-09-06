"""Pure-Python pixel-font glyph mapping.

This module owns the mapping used at data-ingest sites.  It deliberately has
no Qt dependency so headless consumers of parsers that call :func:`px` do not
load PySide6.  ``glyphs`` re-exports this API and adds the QObject adapter used
by QML display sites.
"""
import re


# Keys that are invisible or confusable are written as escapes; the visible ones
# stay literal so the table reads.
PX_MAP = {
    "‘": "'",  "’": "'",  "‚": "'",  "‛": "'",
    "ʼ": "'",  "´": "'",  "′": "'",
    "“": '"',  "”": '"',  "„": '"',  "‟": '"',
    "″": '"',
    "‐": "-",  "‑": "-",  "‒": "-",  "–": "-",
    "—": "-",  "―": "-",  "−": "-",
    "…": "...", "•": "*",  "⁄": "/",
    "ﬁ": "fi", "ﬂ": "fl",
    " ": " ",  " ": " ",  "​": "",
    "←": "<-", "→": "->", "↑": "^",  "↓": "v",
    "‹": "<",  "›": ">",  "⁃": "-",  "‣": "-",
    "™": "(tm)", "©": "(c)", "®": "(r)", "℗": "(p)",
    "×": "x",  "¾": "3/4", "ø": "o",
    # Added 2026-07-27, measured against the font by `reader/tools/reader-test.py`
    # over this repo's own 47 markdown files — every one of these clips a line
    # today, in the panel as well as here. `§` alone occurs 330 times, most of
    # them in the document that states the rule. It is the ONE entry with no
    # exact ASCII equivalent: `S` is what the glyph is drawn from, and "S2.3"
    # beats a clipped row. The rest are ordinary substitutions.
    "§": "S",
    "⇒": "=>", "⇐": "<=", "↔": "<->", "‖": "||", "≠": "!=",
    "●": "*",  "▲": "^",  "▼": "v",  "▴": "^",  "▾": "v",
    "✓": "v",  "✗": "x",  "✅": "v", "❌": "x",
    "¹": "1",  "³": "3",  "⁰": "0",  "⁻": "-",  "₀": "0",
    "✕": "x",  "✖": "x",  "✔": "v",  "▶": ">",  "◀": "<",  "▢": "[]",
    "⇄": "<->", "⇔": "<->", "↩": "<-", "↪": "->", "⚠": "!",
    "≫": ">>", "≪": "<<", "‾": "-",  "⌘": "cmd", "⌥": "alt", "⏎": "<-",
    "↵": "<-", "★": "*",  "☆": "*",  "⚑": "!",  "⚡": "!",
}

# Characters this desktop's own documents contain that the font lacks and this
# table deliberately does NOT map, so a harness can tell a KNOWN limit from a
# new regression.
UNMAPPED_BY_DESIGN = set("♫♥♪¶")

# Greek and mathematical notation remain deliberately unmapped.
UNMAPPED_RANGES = ((0x0370, 0x03FF), (0x2200, 0x22FF), (0x3000, 0x10FFFF))


def is_mappable(ch):
    """Would a missing ``ch`` be a bug the table should have caught?"""
    if ch in PX_MAP or ch in UNMAPPED_BY_DESIGN:
        return ch in PX_MAP
    return not any(lo <= ord(ch) <= hi for lo, hi in UNMAPPED_RANGES)


_PX_RE = re.compile("[" + re.escape("".join(PX_MAP)) + "]")


def px(s):
    """Return the pixel-font-safe form of ``s``."""
    if not s:
        return s or ""
    return _PX_RE.sub(lambda m: PX_MAP[m.group(0)], s)

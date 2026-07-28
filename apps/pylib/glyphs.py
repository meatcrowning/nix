"""px(): make a string safe to DRAW in More Perfect DOS VGA — the apps' half.

The panel has had this for a long time (`home/prog/quickshell-files/Glyphs.qml`)
and `docs/DESIGN.md` §2.3 states the rule for the whole desktop: hardcoded UI strings
are written to suit the font, and text that arrives from OUTSIDE is mapped at
INGEST. The six apps had no mapping at all (§19.1 records that as a divergence,
and Open question 2 as the proposal); `reader` is the first app that could not
ship without one, because a markdown document is nothing BUT foreign text and
this repo's own docs are full of em dashes, curly quotes, ellipses and arrows.

WHY IT CLIPS, not just "looks wrong": a string containing a glyph the family
lacks makes Qt fall back to another font for that ONE character, the line takes
the fallback's taller ascent, and under `lineHeightMode: FixedHeight` (which
every PixelText sets, §2.2) that ascent has nowhere to go — so the whole line is
pushed down inside its row and clipped along the bottom.

This is the PYTHON side on purpose. §2.3 says to map at the ingest point where
there is one, "one pass per data change, not one per delegate per scroll", and
for these apps that point is where a file is parsed, not where a delegate draws.

**DISPLAY ONLY.** Nothing identifying goes through here — a path handed to a
process, a URL that will be opened, a search query matched against the file on
disk. Mapping those quietly opens or renames the wrong thing. Call sites that
must not map carry a comment saying so.

The table is a copy of the panel's, character for character, and must stay one:
two roofs, no shared file (the panel's QML is Quickshell's, this is Python), the
same standing arrangement as `PixelText` and the `Kinetic*` types. It is a
LOOKUP TABLE, not "strip anything the font lacks" — CJK has no ASCII form, and a
title turned into question marks is worse than one drawn in the wrong font.
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
# new regression:
#
#   ♫ ♥      — docs/DESIGN.md Open question 8: they have no ASCII equivalent, so
#              replacing them is his decision, not a sweep.
#   CJK, Δ ∈ ⊂ and friends — the recorded limit of §2.3: a lookup table, not
#              "strip anything the font lacks".
UNMAPPED_BY_DESIGN = set("♫♥♪¶")

# ...and the two RANGES with the same status, checked by
# `reader/tools/reader-test.py` rather than listed character by character:
# Greek (research notes write `v0·e^(-friction·t)` with real betas and gammas)
# and the mathematical operators. Both are notation — an ASCII "b" for a beta
# would not be a substitution, it would be a different formula.
UNMAPPED_RANGES = ((0x0370, 0x03FF), (0x2200, 0x22FF), (0x3000, 0x10FFFF))


def is_mappable(ch):
    """Would a missing `ch` be a BUG (something the table should have caught)?

    False for the recorded limits above. This is the question a harness asks;
    `px` itself never needs it."""
    if ch in PX_MAP or ch in UNMAPPED_BY_DESIGN:
        return ch in PX_MAP
    return not any(lo <= ord(ch) <= hi for lo, hi in UNMAPPED_RANGES)

# re.escape over the joined keys, not a bare join: a character class treats `-`
# and `^` structurally, and this table is meant to be extended by hand.
_PX_RE = re.compile("[" + re.escape("".join(PX_MAP)) + "]")


def px(s):
    """The mapped form of `s`, or `s` unchanged when it holds nothing to map."""
    if not s:
        return s or ""
    return _PX_RE.sub(lambda m: PX_MAP[m.group(0)], s)

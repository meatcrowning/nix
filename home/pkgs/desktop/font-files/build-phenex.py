#!/usr/bin/env python3
"""Build "Phenex", the desktop's hand-authored connected-script (cursive)
face — a NORMAL smooth outline font, not a pixel one. Run under FontForge:

    fontforge -lang=py -script build-phenex.py <out.ttf>

Like Botis 4x6 (build-4x6.py) every stroke of every glyph is invented here —
no donor face — under the same explicit override of the "do not invent a
font" rule. Named for the goetia's poet, Botis's foundry-mate. It replaced
the first draft, "Phenex 6x8", a pixel-grid version: his call 2026-08-08 —
*"it should be a normal non pixel cursive font"*.

HOW IT IS BUILT — pen skeletons, stroked. Each glyph is authored as the pen's
PATH (open cubic-bezier strokes, the way a hand actually writes it), and
FontForge's stroke expansion sweeps a circular nib (STROKE units wide, round
caps/joins) along it to make the outline: a monoline script, like felt-tip
handwriting. A few symbol glyphs (block/heart/triangle) are authored as
closed FILLED contours instead and skip the stroking.

WHAT MAKES IT CURSIVE — the join convention. Every glyph advances exactly
ADV with zero side bearing, and every lowercase skeleton STARTS at (0, JOIN)
and ENDS at (ADV, JOIN) with a matching rightward tangent. Glyph N's exit
point therefore lands on glyph N+1's entry point exactly, and the round nib
caps overlap — so lowercase words render as one continuous connected stroke,
rising from the join height into each letterform. Capitals, digits and
punctuation carry no connectors and sit inside the advance with clear air.

Vertical scheme (font units, UPM 1000, baseline y=0):

    ASC  750   ascender loops (l b f h k), caps ~700
    XH   500   x-height
    JOIN 130   where the connectors cross the glyph border
    DESC -250  descender loops (f g j p q y)

The face is proportional-of-spirit but METRICALLY MONO (every advance ADV):
the pick drives kitty too, and kitty needs a fixed cell. Rendering: this face
is SMOOTH — it must be antialiased, never pixel-snapped; the selectable-face
plumbing carries a `smooth` flag (font.nix FontFaces.qml / deskstyle.py) that
PixelText and the editors branch on. See docs/DESIGN.md §2.1.
"""

import sys

# --- geometry ----------------------------------------------------------------
ADV = 600          # every glyph; zero side bearing on lowercase (joins touch)
JOIN = 130         # y where connectors cross x=0 / x=ADV
XH = 500           # x-height
ASC = 750          # ascender
CAP = 700          # cap height
DESC = -250        # descender
STROKE = 95        # nib diameter
K = 0.5523         # circle-approximation handle factor

FAMILY = "Phenex"

# Path ops: ("m",x,y) ("l",x,y) ("c",x1,y1,x2,y2,x,y). One glyph = list of ops;
# "m" starts a new (open) subpath. CLOSED contours (for rings/filled shapes)
# use ("z",) to close the current subpath.


def ring(cx, cy, rx, ry):
    """Closed ellipse contour (stroked -> ring; in FILLED glyphs -> disc)."""
    return [
        ("m", cx + rx, cy),
        ("c", cx + rx, cy + K * ry, cx + K * rx, cy + ry, cx, cy + ry),
        ("c", cx - K * rx, cy + ry, cx - rx, cy + K * ry, cx - rx, cy),
        ("c", cx - rx, cy - K * ry, cx - K * rx, cy - ry, cx, cy - ry),
        ("c", cx + K * rx, cy - ry, cx + rx, cy - K * ry, cx + rx, cy),
        ("z",),
    ]


def dot(x, y, r=28):
    """A visible dot: a tiny closed circle; stroking fattens it to ~r+nib/2."""
    return ring(x, y, r, r)


def entry(tx, ty):
    """Connector: rise from the left join point (0,JOIN) up into the letter."""
    return [("m", 0, JOIN), ("c", 110, JOIN + 55, tx - 120, ty - 190, tx, ty)]


def exit_(fx, fy=95):
    """Connector: from a stem foot out to the right join point (ADV,JOIN)."""
    return [("c", fx + 25, 5, 520, 0, ADV, JOIN)]


def stem_exit(x, ytop):
    """New subpath: a stem from (x,ytop) down to the baseline, then exit."""
    return [("m", x, ytop), ("l", x, 95)] + exit_(x)


def bowl_open(top_x=400, top_y=450):
    """The a/d/g/q bowl as ONE open stroke: rise from the join over the top,
    around the left, along the bottom, up the right side to x-height (where
    the stem subpath will land on it)."""
    return [
        ("m", 0, JOIN),
        ("c", 120, 180, 300, 330, top_x, top_y),      # rise to bowl top-right
        ("c", 360, 512, 268, 516, 210, 490),           # over the top, leftward
        ("c", 118, 448, 98, 345, 98, 265),             # left side
        ("c", 98, 128, 172, 48, 272, 50),              # bottom
        ("c", 345, 52, 402, 100, 418, 180),            # lower right
        ("c", 436, 280, 444, 400, 448, 480),           # up to x-height
    ]


def loopstem():
    """The l/b/h/k looped ascender: rise from the join, sweep up the right
    side to the top, curl over leftward, and come down to the baseline."""
    return [
        ("m", 0, JOIN),
        ("c", 130, 215, 235, 430, 252, 600),           # rising upstroke
        ("c", 262, 700, 242, 752, 205, 746),           # loop over the top
        ("c", 172, 740, 158, 692, 165, 632),           # curl back down
        ("c", 178, 520, 192, 320, 200, 180),           # descending stroke
        ("c", 204, 120, 210, 85, 218, 68),             # easing onto baseline
    ]


def g_tail(x=450):
    """g/j/y descender: from the baseline at x, down, loop left, back up and
    out to the join."""
    return [
        ("m", x, XH - 10),
        ("l", x, -80),
        ("c", x, -195, x - 68, -250, x - 138, -218),
        ("c", x - 188, -192, x - 184, -136, x - 132, -96),
        ("c", x - 50, -30, 480, 40, ADV, JOIN),
    ]


G = {}

# =============================================================================
# lowercase — the connected script
# =============================================================================
G[ord("a")] = bowl_open() + stem_exit(450, 490)
G[ord("d")] = bowl_open() + [("m", 452, CAP), ("l", 450, 95)] + exit_(450)
G[ord("g")] = bowl_open() + g_tail(450)
G[ord("q")] = bowl_open() + [
    ("m", 450, XH - 10), ("l", 450, -110),
    ("c", 450, -205, 505, -235, 548, -192),
    ("c", 578, -160, 578, -60, ADV, JOIN),
]
G[ord("o")] = [
    ("m", 0, JOIN),
    ("c", 120, 180, 300, 330, 400, 450),
    ("c", 362, 512, 270, 516, 212, 490),
    ("c", 120, 448, 100, 345, 100, 265),
    ("c", 100, 128, 174, 48, 274, 50),
    ("c", 352, 52, 408, 108, 418, 190),
    ("c", 426, 270, 418, 390, 400, 450),               # close the bowl
    ("m", 400, 450),                                   # HIGH exit (the o tell)
    ("c", 470, 430, 545, 290, ADV, JOIN),
]
G[ord("c")] = [
    ("m", 452, 408),
    ("c", 428, 486, 338, 514, 268, 505),
    ("c", 160, 492, 102, 396, 98, 276),
    ("c", 94, 148, 170, 50, 284, 48),
    ("c", 340, 48, 390, 64, 420, 90),
    ("c", 466, 50, 524, 38, ADV, JOIN),
]
G[ord("e")] = [
    ("m", 0, JOIN),
    ("c", 160, 165, 340, 235, 400, 385),
    ("c", 400, 468, 340, 510, 270, 505),
    ("c", 164, 495, 104, 398, 100, 278),
    ("c", 96, 150, 174, 52, 288, 50),
    ("c", 352, 50, 408, 72, 434, 100),
    ("c", 476, 50, 532, 26, ADV, JOIN),
]
G[ord("i")] = [
    ("m", 0, JOIN), ("c", 110, 180, 262, 352, 294, 478),
    ("m", 298, 490), ("l", 300, 95),
] + exit_(300) + dot(312, 625)
G[ord("j")] = [
    ("m", 0, JOIN), ("c", 110, 180, 272, 352, 306, 478),
    ("m", 310, 490), ("l", 310, -80),
    ("c", 310, -195, 244, -248, 178, -216),
    ("c", 130, -190, 134, -134, 186, -94),
    ("c", 268, -30, 480, 40, ADV, JOIN),
] + dot(324, 625)
G[ord("u")] = [
    ("m", 0, JOIN),
    ("c", 105, 175, 142, 330, 148, 470),
    ("m", 150, 490),
    ("l", 150, 200),
    ("c", 150, 82, 214, 48, 292, 60),
    ("c", 382, 76, 442, 160, 448, 290),
    ("c", 452, 370, 452, 440, 450, 490),
    ("l", 452, 95),
] + exit_(452)
G[ord("t")] = [
    ("m", 0, JOIN),
    ("c", 120, 195, 290, 440, 332, 690),
    ("l", 330, 95),
] + exit_(330) + [("m", 205, 548), ("l", 458, 548)]
G[ord("l")] = loopstem() + [("c", 245, 25, 310, 2, 380, 12), ("c", 480, 28, 545, 68, ADV, JOIN)]
G[ord("b")] = loopstem() + [
    ("c", 240, 45, 290, 42, 330, 55),                  # onto the bowl
] + ring(322, 252, 138, 208) + [
    ("m", 420, 165), ("c", 448, 62, 512, 8, ADV, JOIN),
]
G[ord("h")] = loopstem() + [
    ("m", 208, 120),
    ("c", 214, 300, 258, 468, 338, 482),
    ("c", 418, 494, 448, 424, 450, 330),
    ("l", 452, 95),
] + exit_(452)
G[ord("k")] = loopstem() + [
    ("m", 430, 470),
    ("c", 340, 442, 262, 362, 218, 292),
    ("c", 292, 252, 372, 165, 420, 95),
    ("c", 458, 15, 522, 2, ADV, JOIN),
]
G[ord("n")] = [
    ("m", 0, JOIN),
    ("c", 105, 175, 140, 330, 148, 460),
    ("m", 150, 480), ("l", 154, 95),
    ("m", 155, 140),
    ("c", 162, 310, 202, 468, 302, 482),
    ("c", 398, 494, 446, 424, 448, 325),
    ("l", 452, 95),
] + exit_(452)
G[ord("m")] = [
    ("m", 0, JOIN),
    ("c", 100, 175, 132, 330, 138, 460),
    ("m", 140, 480), ("l", 144, 95),
    ("m", 145, 140),
    ("c", 152, 300, 182, 458, 258, 470),
    ("c", 322, 480, 340, 420, 342, 335),
    ("l", 344, 95),
    ("m", 345, 140),
    ("c", 352, 300, 382, 458, 452, 470),
    ("c", 512, 478, 528, 420, 528, 335),
    ("l", 530, 100),
    ("c", 548, 18, 566, 6, ADV, JOIN),
]
G[ord("r")] = [
    ("m", 0, JOIN),
    ("c", 110, 185, 172, 350, 192, 498),
    ("c", 235, 468, 292, 462, 330, 478),
    ("c", 342, 355, 348, 210, 350, 95),
    ("c", 378, 8, 480, 0, ADV, JOIN),
]
G[ord("s")] = [
    ("m", 0, JOIN),
    ("c", 130, 200, 310, 390, 388, 478),
    ("c", 358, 506, 296, 505, 258, 470),
    ("c", 222, 435, 248, 380, 315, 335),
    ("c", 390, 285, 420, 222, 396, 152),
    ("c", 372, 85, 288, 62, 235, 108),
    ("c", 290, 30, 460, 32, ADV, JOIN),
]
G[ord("v")] = [
    ("m", 0, JOIN),
    ("c", 105, 178, 138, 320, 142, 462),
    ("l", 252, 82),
    ("l", 408, 468),
    ("c", 442, 372, 528, 248, ADV, JOIN),
]
G[ord("w")] = [
    ("m", 0, JOIN),
    ("c", 100, 180, 128, 320, 132, 470),
    ("c", 138, 280, 168, 100, 238, 78),
    ("c", 298, 95, 318, 250, 322, 395),
    ("c", 330, 255, 352, 100, 420, 82),
    ("c", 478, 100, 498, 300, 500, 452),
    ("c", 522, 365, 558, 235, ADV, JOIN),
]
G[ord("x")] = [
    ("m", 0, JOIN),
    ("c", 100, 172, 132, 330, 146, 452),
    ("c", 250, 305, 352, 182, 428, 102),
    ("c", 465, 32, 522, 8, ADV, JOIN),
    ("m", 428, 470),
    ("c", 330, 382, 232, 182, 162, 80),
]
G[ord("y")] = [
    ("m", 0, JOIN),
    ("c", 105, 175, 142, 330, 148, 470),
    ("m", 150, 490),
    ("l", 150, 200),
    ("c", 150, 82, 214, 48, 292, 60),
    ("c", 382, 76, 442, 160, 448, 290),
    ("l", 450, 490),
] + g_tail(452)
G[ord("z")] = [
    ("m", 0, JOIN),
    ("c", 112, 182, 142, 360, 152, 468),
    ("c", 252, 498, 362, 494, 428, 478),
    ("c", 330, 380, 240, 222, 192, 122),
    ("c", 282, 58, 380, 52, 438, 72),
    ("c", 500, 88, 556, 102, ADV, JOIN),
]
G[ord("f")] = [
    ("m", 0, JOIN),
    ("c", 130, 210, 255, 440, 278, 600),
    ("c", 295, 712, 268, 762, 222, 752),
    ("c", 178, 742, 168, 682, 180, 615),
    ("c", 202, 470, 212, 200, 213, 20),
    ("l", 214, -130),
    ("c", 215, -230, 262, -272, 318, -242),
    ("c", 365, -216, 360, -150, 305, -110),
    ("c", 365, -45, 470, 45, ADV, JOIN),
]
G[ord("p")] = [
    ("m", 0, JOIN),
    ("c", 92, 172, 142, 310, 156, 435),
    ("m", 158, 490),
    ("l", 160, -150),
    ("c", 160, -228, 130, -252, 104, -232),
] + ring(305, 260, 128, 205) + [
    ("m", 420, 175), ("c", 448, 62, 512, 8, ADV, JOIN),
]

# =============================================================================
# capitals — clean monoline semi-script, cap height ~700, no connectors
# =============================================================================
G[ord("A")] = [
    ("m", 90, 25), ("c", 180, 280, 272, 560, 305, 695),
    ("c", 340, 560, 432, 280, 508, 25),
    ("m", 190, 260), ("l", 420, 260),
]
G[ord("B")] = [
    ("m", 142, 690), ("l", 142, 28),
    ("m", 140, 686),
    ("c", 320, 700, 402, 640, 402, 540),
    ("c", 402, 442, 322, 392, 150, 386),
    ("m", 150, 386),
    ("c", 350, 394, 440, 330, 440, 214),
    ("c", 440, 92, 330, 20, 145, 30),
]
G[ord("C")] = [
    ("m", 472, 558),
    ("c", 432, 660, 332, 710, 250, 690),
    ("c", 120, 655, 70, 520, 75, 360),
    ("c", 80, 180, 170, 40, 320, 35),
    ("c", 400, 32, 452, 80, 470, 142),
]
G[ord("D")] = [
    ("m", 150, 690), ("l", 150, 30),
    ("m", 146, 688),
    ("c", 350, 700, 470, 560, 470, 360),
    ("c", 470, 160, 350, 20, 148, 32),
]
G[ord("E")] = [
    ("m", 150, 690), ("l", 150, 30),
    ("m", 150, 686), ("c", 280, 700, 380, 700, 445, 682),
    ("m", 150, 372), ("c", 240, 386, 300, 386, 362, 372),
    ("m", 150, 34), ("c", 280, 16, 392, 16, 458, 46),
]
G[ord("F")] = [
    ("m", 158, 690), ("l", 158, 28),
    ("m", 158, 686), ("c", 290, 700, 392, 700, 452, 678),
    ("m", 158, 372), ("c", 248, 386, 310, 386, 372, 372),
]
G[ord("G")] = [
    ("m", 470, 556),
    ("c", 430, 660, 330, 712, 248, 690),
    ("c", 120, 655, 72, 520, 76, 360),
    ("c", 80, 180, 170, 38, 320, 36),
    ("c", 422, 35, 470, 100, 470, 195),
    ("l", 470, 300), ("l", 340, 300),
]
G[ord("H")] = [
    ("m", 140, 690), ("l", 140, 30),
    ("m", 460, 690), ("l", 460, 30),
    ("m", 140, 372), ("l", 460, 372),
]
G[ord("I")] = [
    ("m", 300, 688), ("l", 300, 32),
    ("m", 205, 690), ("l", 398, 690),
    ("m", 205, 30), ("l", 398, 30),
]
G[ord("J")] = [
    ("m", 430, 690), ("l", 430, 130),
    ("c", 430, 42, 352, 14, 282, 40),
    ("c", 232, 60, 210, 108, 214, 158),
    ("m", 320, 690), ("l", 520, 690),
]
G[ord("K")] = [
    ("m", 140, 690), ("l", 140, 30),
    ("m", 452, 682), ("c", 340, 560, 240, 442, 150, 372),
    ("m", 232, 432), ("c", 322, 322, 402, 162, 462, 30),
]
G[ord("L")] = [
    ("m", 156, 690), ("l", 156, 38),
    ("m", 156, 38), ("c", 280, 18, 400, 20, 465, 52),
]
G[ord("M")] = [
    ("m", 118, 28), ("l", 128, 685),
    ("m", 128, 685), ("c", 200, 520, 262, 380, 300, 298),
    ("m", 300, 298), ("c", 340, 380, 402, 520, 470, 685),
    ("m", 472, 685), ("l", 482, 28),
]
G[ord("N")] = [
    ("m", 130, 28), ("l", 138, 688),
    ("m", 138, 682), ("c", 240, 500, 360, 248, 458, 42),
    ("m", 462, 32), ("l", 468, 690),
]
G[ord("O")] = ring(300, 358, 196, 332)
G[ord("P")] = [
    ("m", 150, 690), ("l", 150, 28),
    ("m", 148, 686),
    ("c", 330, 700, 432, 630, 432, 520),
    ("c", 432, 408, 330, 358, 152, 368),
]
G[ord("Q")] = ring(300, 358, 196, 332) + [
    ("m", 362, 142), ("c", 420, 82, 472, 40, 532, 10),
]
G[ord("R")] = [
    ("m", 150, 690), ("l", 150, 28),
    ("m", 148, 686),
    ("c", 330, 700, 432, 630, 432, 520),
    ("c", 432, 408, 330, 358, 152, 368),
    ("m", 300, 368),
    ("c", 372, 290, 432, 160, 470, 30),
]
G[ord("S")] = [
    ("m", 445, 592),
    ("c", 410, 685, 300, 715, 220, 675),
    ("c", 145, 636, 155, 545, 235, 488),
    ("c", 330, 420, 432, 380, 440, 278),
    ("c", 448, 158, 335, 25, 178, 88),
    ("c", 158, 98, 148, 112, 145, 122),
]
G[ord("T")] = [
    ("m", 302, 685), ("l", 302, 30),
    ("m", 128, 688), ("c", 230, 700, 382, 700, 478, 686),
]
G[ord("U")] = [
    ("m", 140, 690), ("l", 140, 252),
    ("c", 140, 108, 220, 30, 308, 30),
    ("c", 398, 30, 460, 110, 460, 252),
    ("l", 460, 690),
]
G[ord("V")] = [
    ("m", 118, 690),
    ("c", 180, 450, 252, 178, 302, 32),
    ("c", 352, 178, 422, 450, 484, 690),
]
G[ord("W")] = [
    ("m", 98, 690), ("c", 128, 470, 158, 178, 188, 38),
    ("m", 188, 38), ("c", 230, 200, 270, 380, 300, 480),
    ("m", 300, 480), ("c", 330, 380, 372, 200, 412, 38),
    ("m", 412, 38), ("c", 442, 178, 472, 470, 502, 690),
]
G[ord("X")] = [
    ("m", 130, 680), ("c", 250, 480, 372, 218, 472, 38),
    ("m", 462, 680), ("c", 350, 480, 230, 218, 138, 38),
]
G[ord("Y")] = [
    ("m", 128, 690), ("c", 190, 540, 252, 428, 300, 368),
    ("m", 472, 690), ("c", 412, 540, 350, 428, 302, 368),
    ("m", 300, 368), ("l", 300, 30),
]
G[ord("Z")] = [
    ("m", 140, 678), ("c", 250, 694, 362, 694, 455, 684),
    ("m", 455, 684), ("c", 342, 470, 222, 232, 148, 42),
    ("m", 148, 42), ("c", 262, 22, 382, 22, 465, 42),
]

# =============================================================================
# digits — monoline print, height ~700
# =============================================================================
G[ord("0")] = ring(300, 352, 172, 330)
G[ord("1")] = [
    ("m", 198, 555), ("c", 250, 598, 282, 640, 302, 690),
    ("l", 302, 30),
]
G[ord("2")] = [
    ("m", 158, 555),
    ("c", 178, 660, 282, 712, 372, 672),
    ("c", 452, 636, 462, 540, 410, 452),
    ("c", 340, 332, 228, 190, 158, 78),
    ("c", 265, 30, 392, 32, 462, 48),
]
G[ord("3")] = [
    ("m", 162, 598),
    ("c", 200, 690, 332, 712, 402, 650),
    ("c", 458, 598, 442, 508, 372, 468),
    ("c", 342, 452, 312, 448, 288, 448),
    ("m", 288, 448),
    ("c", 385, 442, 458, 375, 452, 268),
    ("c", 446, 138, 322, 22, 168, 92),
]
G[ord("4")] = [
    ("m", 372, 690),
    ("c", 282, 545, 192, 390, 142, 272),
    ("l", 468, 272),
    ("m", 372, 690), ("l", 372, 30),
]
G[ord("5")] = [
    ("m", 428, 688),
    ("c", 340, 695, 262, 695, 192, 686),
    ("c", 184, 600, 178, 500, 174, 418),
    ("c", 232, 462, 332, 466, 396, 416),
    ("c", 466, 360, 466, 220, 392, 140),
    ("c", 322, 68, 202, 68, 152, 138),
]
G[ord("6")] = [
    ("m", 428, 622),
    ("c", 390, 690, 300, 715, 230, 668),
    ("c", 122, 598, 82, 420, 96, 272),
    ("c", 110, 122, 200, 32, 310, 36),
    ("c", 420, 42, 468, 132, 464, 220),
    ("c", 460, 330, 380, 392, 290, 386),
    ("c", 202, 380, 132, 322, 110, 252),
]
G[ord("7")] = [
    ("m", 142, 618),
    ("c", 150, 668, 172, 688, 222, 690),
    ("c", 302, 692, 402, 690, 460, 685),
    ("m", 460, 685),
    ("c", 390, 500, 300, 250, 245, 35),
]
G[ord("8")] = ring(300, 512, 148, 175) + ring(300, 182, 172, 158)
G[ord("9")] = ring(292, 478, 158, 196) + [
    ("m", 448, 528),
    ("c", 452, 420, 440, 240, 382, 35),
]

# =============================================================================
# punctuation & symbols — monoline
# =============================================================================
G[0x20] = []                                              # space
G[0x21] = [("m", 300, 690), ("l", 292, 225)] + dot(288, 50)      # !
G[0x22] = [("m", 258, 690), ("l", 252, 555), ("m", 352, 690), ("l", 346, 555)]  # "
G[0x23] = [
    ("m", 268, 618), ("l", 232, 92), ("m", 408, 618), ("l", 372, 92),
    ("m", 152, 442), ("l", 478, 442), ("m", 138, 258), ("l", 462, 258),
]                                                          # #
G[0x24] = [
    ("m", 428, 552),
    ("c", 398, 636, 302, 658, 232, 618),
    ("c", 164, 578, 172, 500, 250, 452),
    ("c", 330, 402, 420, 372, 428, 288),
    ("c", 436, 182, 348, 82, 218, 132),
    ("m", 308, 712), ("l", 296, -15),
]                                                          # $
G[0x25] = ring(182, 545, 88, 108) + ring(428, 148, 88, 108) + [
    ("m", 458, 662), ("c", 368, 452, 248, 222, 152, 38),
]                                                          # %
G[0x26] = [
    ("m", 432, 178),
    ("c", 340, 58, 218, 28, 158, 98),
    ("c", 98, 168, 158, 262, 258, 340),
    ("c", 358, 418, 398, 502, 358, 588),
    ("c", 328, 656, 240, 656, 216, 588),
    ("c", 190, 518, 242, 418, 330, 310),
    ("c", 390, 238, 458, 138, 522, 62),
]                                                          # &
G[0x27] = [("m", 302, 690), ("l", 296, 555)]               # '
G[0x28] = [("m", 372, 738), ("c", 282, 618, 242, 450, 250, 290),
           ("c", 258, 140, 300, 0, 370, -88)]              # (
G[0x29] = [("m", 238, 738), ("c", 328, 618, 368, 450, 360, 290),
           ("c", 352, 140, 310, 0, 240, -88)]              # )
G[0x2a] = [("m", 300, 642), ("l", 300, 398),
           ("m", 195, 578), ("l", 405, 462),
           ("m", 195, 462), ("l", 405, 578)]               # *
G[0x2b] = [("m", 300, 558), ("l", 300, 162), ("m", 112, 360), ("l", 488, 360)]  # +
G[0x2c] = [("m", 312, 62), ("c", 306, 8, 290, -42, 258, -82)]  # ,
G[0x2d] = [("m", 142, 330), ("c", 242, 340, 360, 340, 458, 330)]  # -
G[0x2e] = dot(296, 48)                                     # .
G[0x2f] = [("m", 432, 738), ("c", 340, 490, 240, 200, 168, -42)]  # /
G[0x3a] = dot(296, 380) + dot(296, 55)                     # :
G[0x3b] = dot(300, 380) + [("m", 310, 62), ("c", 304, 8, 288, -40, 256, -78)]  # ;
G[0x3c] = [("m", 432, 542), ("c", 300, 470, 200, 408, 150, 360),
           ("c", 200, 312, 300, 250, 432, 178)]            # <
G[0x3d] = [("m", 140, 452), ("l", 460, 452), ("m", 140, 262), ("l", 460, 262)]  # =
G[0x3e] = [("m", 168, 542), ("c", 300, 470, 400, 408, 450, 360),
           ("c", 400, 312, 300, 250, 168, 178)]            # >
G[0x3f] = [
    ("m", 162, 568),
    ("c", 172, 668, 262, 715, 342, 690),
    ("c", 430, 660, 450, 558, 390, 472),
    ("c", 352, 415, 310, 372, 302, 288),
    ("l", 300, 240),
] + dot(295, 55)                                           # ?
G[0x40] = ring(300, 300, 240, 285) + ring(298, 322, 88, 108) + [
    ("m", 386, 420), ("l", 392, 262),
    ("c", 396, 178, 448, 168, 486, 226),
]                                                          # @
G[0x5b] = [("m", 362, 738), ("l", 256, 738), ("l", 258, -78), ("l", 365, -78)]  # [
G[0x5c] = [("m", 170, 738), ("c", 240, 490, 340, 200, 432, -42)]  # backslash
G[0x5d] = [("m", 238, 738), ("l", 345, 738), ("l", 343, -78), ("l", 236, -78)]  # ]
G[0x5e] = [("m", 178, 478), ("c", 230, 568, 272, 638, 300, 690),
           ("c", 328, 638, 370, 568, 422, 478)]            # ^
G[0x5f] = [("m", 100, -58), ("l", 500, -58)]               # _
G[0x60] = [("m", 252, 692), ("l", 340, 572)]               # `
G[0x7b] = [
    ("m", 388, 738),
    ("c", 310, 728, 292, 678, 292, 598),
    ("c", 292, 490, 282, 400, 222, 330),
    ("c", 282, 260, 292, 170, 292, 62),
    ("c", 292, -18, 310, -68, 388, -78),
]                                                          # {
G[0x7c] = [("m", 300, 718), ("l", 300, -58)]               # |
G[0x7d] = [
    ("m", 212, 738),
    ("c", 290, 728, 308, 678, 308, 598),
    ("c", 308, 490, 318, 400, 378, 330),
    ("c", 318, 260, 308, 170, 308, 62),
    ("c", 308, -18, 290, -68, 212, -78),
]                                                          # }
G[0x7e] = [("m", 138, 338), ("c", 188, 418, 258, 420, 308, 362),
           ("c", 358, 302, 428, 302, 468, 380)]            # ~

# --- the non-ASCII parity set (see build-4x6.py for the audit) ---------------
G[0x00b0] = ring(300, 592, 85, 85)                         # °
G[0x00b7] = dot(300, 330)                                  # ·
G[0x00d7] = [("m", 192, 468), ("l", 408, 192), ("m", 408, 468), ("l", 192, 192)]  # ×
G[0x2016] = [("m", 252, 598), ("l", 252, 102), ("m", 358, 598), ("l", 358, 102)]  # ‖
G[0x2039] = [("m", 362, 518), ("c", 262, 458, 202, 408, 172, 360),
             ("c", 202, 312, 262, 262, 362, 202)]          # ‹
G[0x203a] = [("m", 238, 518), ("c", 338, 458, 398, 408, 428, 360),
             ("c", 398, 312, 338, 262, 238, 202)]          # ›
G[0x2191] = [("m", 300, 622), ("l", 300, 118),
             ("m", 182, 462), ("c", 232, 518, 272, 570, 300, 622),
             ("m", 418, 462), ("c", 368, 518, 328, 570, 300, 622)]  # ↑
G[0x2193] = [("m", 300, 622), ("l", 300, 118),
             ("m", 182, 278), ("c", 232, 222, 272, 170, 300, 118),
             ("m", 418, 278), ("c", 368, 222, 328, 170, 300, 118)]  # ↓
G[0x2212] = [("m", 142, 330), ("c", 242, 340, 360, 340, 458, 330)]  # −
G[0x25a0] = [("m", 150, 452), ("l", 450, 452), ("l", 450, 152), ("l", 150, 152), ("z",)]  # ■ (filled)
G[0x2588] = [("m", 0, 750), ("l", 600, 750), ("l", 600, -250), ("l", 0, -250), ("z",)]    # █ (filled)
G[0x2591] = (dot(100, 600) + dot(300, 600) + dot(500, 600)
             + dot(200, 450) + dot(400, 450)
             + dot(100, 300) + dot(300, 300) + dot(500, 300)
             + dot(200, 150) + dot(400, 150)
             + dot(100, 0) + dot(300, 0) + dot(500, 0)
             + dot(200, -150) + dot(400, -150))            # ░
G[0x25b6] = [("m", 180, 560), ("l", 500, 300), ("l", 180, 40), ("z",)]  # ▶ (filled)
G[0x2665] = [
    ("m", 300, 80),
    ("c", 160, 200, 80, 320, 80, 440),
    ("c", 80, 558, 180, 610, 255, 570),
    ("c", 285, 554, 300, 528, 300, 498),
    ("c", 300, 528, 315, 554, 345, 570),
    ("c", 420, 610, 520, 558, 520, 440),
    ("c", 520, 320, 440, 200, 300, 80),
    ("z",),
]                                                          # ♥ (filled)
G[0x266b] = [
    ("m", 252, 480), ("l", 252, 130),
    ("m", 452, 520), ("l", 452, 170),
    ("m", 252, 480), ("c", 320, 512, 385, 522, 452, 515),
] + dot(212, 108, 68) + dot(412, 148, 68)                  # ♫
G[0x2018] = [("m", 262, 555), ("c", 268, 610, 284, 655, 316, 692)]  # '
G[0x2019] = [("m", 316, 690), ("c", 310, 636, 294, 592, 262, 555)]  # '
G[0x201c] = [("m", 212, 555), ("c", 218, 610, 234, 655, 266, 692),
             ("m", 332, 555), ("c", 338, 610, 354, 655, 386, 692)]  # "
G[0x201d] = [("m", 266, 690), ("c", 260, 636, 244, 592, 212, 555),
             ("m", 386, 690), ("c", 380, 636, 364, 592, 332, 555)]  # "
G[0x2013] = [("m", 120, 330), ("l", 480, 330)]             # –
G[0x2014] = [("m", 70, 330), ("l", 530, 330)]              # —

# glyphs authored as closed FILLED contours: no stroke expansion
FILLED = {0x25a0, 0x2588, 0x25b6, 0x2665}


def draw(pen, ops):
    open_path = False
    for op in ops:
        if op[0] == "m":
            if open_path:
                pen.endPath()
            pen.moveTo((op[1], op[2]))
            open_path = True
        elif op[0] == "l":
            pen.lineTo((op[1], op[2]))
        elif op[0] == "c":
            pen.curveTo((op[1], op[2]), (op[3], op[4]), (op[5], op[6]))
        elif op[0] == "z":
            pen.closePath()
            open_path = False
    if open_path:
        pen.endPath()


def main():
    import fontforge

    out = sys.argv[1] if len(sys.argv) > 1 else "Phenex.ttf"

    ascii_cps = [cp for cp in G if 0x20 <= cp <= 0x7E]
    assert len(ascii_cps) == 95, f"expected 95 printable ASCII, got {len(ascii_cps)}"
    # every lowercase must start and end on the join anchors
    for cp in range(ord("a"), ord("z") + 1):
        ops = G[cp]
        if cp != ord("c"):  # c is a lift letter (see its comment)
            assert ops[0] == ("m", 0, JOIN), f"{chr(cp)}: bad entry anchor"
        last = [op for op in ops if op[0] in "lc" and op[-2:] == (ADV, JOIN)]
        assert last, f"{chr(cp)}: no exit anchor at (ADV, JOIN)"

    f = fontforge.font()
    f.em = 1000
    f.ascent, f.descent = ASC, 1000 - ASC
    f.familyname = FAMILY
    f.fontname = FAMILY + "-Regular"
    f.fullname = FAMILY
    f.weight = "Regular"
    f.copyright = ""
    f.version = "1.0"
    # Line metrics: cover the real ink (loops overshoot ASC/DESC by half a
    # nib) with a little air; every desktop consumer measures this cell live.
    for attr, val in (("hhea_ascent", 830), ("hhea_descent", -330),
                      ("os2_typoascent", 830), ("os2_typodescent", -330),
                      ("os2_winascent", 830), ("os2_windescent", 330)):
        setattr(f, attr, val)
        try:
            setattr(f, attr + "_add", 0)
        except Exception:
            pass
    f.os2_typolinegap = 0
    # panose: latin text, monospaced (kitty and Qt both sniff this)
    f.os2_panose = (2, 0, 5, 9, 0, 0, 0, 0, 0, 0)

    for cp, ops in sorted(G.items()):
        g = f.createChar(cp)
        if ops:
            draw(g.glyphPen(), ops)
            if cp not in FILLED:
                g.stroke("circular", STROKE, "round", "round")
            g.removeOverlap()
            g.correctDirection()
            g.simplify()
            g.round()
        g.width = ADV

    # .notdef with the mono advance, so fallback boxes keep the grid
    nd = f.createChar(-1, ".notdef")
    nd.width = ADV

    f.selection.all()
    f.generate(out)
    print(f"wrote {out}: {len(G)} glyphs, monoline script, UPM 1000, "
          f"advance {ADV}, nib {STROKE}, join y={JOIN}")


if __name__ == "__main__":
    main()

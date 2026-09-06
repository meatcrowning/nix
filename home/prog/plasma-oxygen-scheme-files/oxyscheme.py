#!/usr/bin/env python3
"""Convert an Oxygen Plasma-theme SVG so it follows the user's colour scheme.

The naive reading of this job -- "map every baked colour onto a ColorScheme-*
role" -- is wrong, and wrong for most of the theme.  Measured on Oxygen 6.7.4,
of the 1803 gradients painted elements actually reference:

    72%  are ALPHA ramps      (one fixed achromatic colour, opacity varies)
    24%  are COLOUR ramps     (opaque, luminance varies)
     3%  chromatic
     1%  both

An alpha ramp is already a shading layer: black-fading-to-nothing is a shadow,
white-fading-to-nothing is a gloss highlight or an outline, and both composite
correctly over any colour underneath them.  Recolouring one destroys it -- a
white@1 -> white@0 outline glow "converted" to a role becomes a solid block.

So the transform is not a recolour, it is an INSERTION.  Inside each element
Plasma addresses by id, the first painted descendant is the body and everything
after it is shading drawn on top (verified: panel-background's `north-top` is a
black body ramp followed by three white glows).  We put a scheme-coloured base
underneath the body and otherwise leave the artwork completely alone.  Oxygen's
gradients, outlines and gloss all survive; they simply sit on the user's colour.

Only the body is ever touched, and only when its paint is achromatic --
saturated colour is Oxygen's identity and stays baked.  `hint-*` elements are
Plasma metadata (geometry read, never drawn) and are never touched.
"""
import gzip, re, sys, os, copy, math, base64
from pngdec import png_rgba, mean_chroma
import xml.etree.ElementTree as ET

SVG = 'http://www.w3.org/2000/svg'
XL  = 'http://www.w3.org/1999/xlink'
ET.register_namespace('', SVG)
ET.register_namespace('xlink', XL)
S = '{%s}' % SVG
X = '{%s}' % XL

CHROMA_MAX    = 0.12   # absolute (max-min), NOT relative saturation: Oxygen's
                       # greys are dark and blue-tinted, and relative saturation
                       # reads #2b2f34 as 17% coloured when its chroma is 3.5%
CHROMA_RASTER = 0.10
LUM_SPREAD    = 0.02   # above this a gradient is a colour ramp, not an alpha ramp
ALPHA_SPREAD  = 0.05
# What to do with an alpha ramp (72% of Oxygen's gradients). See convert().
#   centre    (default) recentre on the ramp's own mean and cap the swing at
#             CENTRE_AMPLITUDE, so the mid-tone IS the scheme colour and the
#             shading moves gently both ways around it. At 0.12 this matches how
#             Oxygen draws a TITLEBAR -- a smooth symmetric gradient over the
#             surface colour -- which is the look he asked the panel to have.
#   flip      the same ramp, reversed along its axis. Keeps Oxygen's full
#             contrast, which on the panel reads as a heavy dark smear.
#   faithful  keep it exactly -- but Oxygen's ramps run TOWARD opaque black, and
#             an opaque end stays opaque whatever the scheme is, so the panel
#             keeps a black band and panel text becomes unreadable on a light
#             scheme. That is what `flip` exists to fix: Oxygen shades away from
#             the edge it darkens, so reversing it puts the scheme colour where
#             the text sits and the dark end on the panel's outer border.
#
# Only alpha ramps are affected. Button/frame/lineedit bodies are COLOUR ramps
# and render identically under all three.
ALPHA_MODE = os.environ.get('OXYSCHEME_ALPHA_MODE', 'titlebar')
# `titlebar` mode: a white overlay at the top fading to nothing, i.e. the same
# shape Oxygen's window/titlebar gradient has (light at the top edge, the plain
# surface colour at the foot). Symmetric `centre` shading put the surface colour
# in the MIDDLE, so the panel never reached the titlebar's light top and read as
# dimmer than every window.
TOP_ALPHA = float(os.environ.get('OXYSCHEME_TOP_ALPHA', '0.25'))
# Oxygen's edge highlights are white at full alpha, authored against a near-black
# panel. On a light surface six of them stacked in `north-bottom` render as a
# hard near-white line (measured L=248 against a 212 panel) -- the "weird line at
# the bottom". They are shading, so they are never recoloured; they are damped.
GLOW_SCALE = float(os.environ.get('OXYSCHEME_GLOW_SCALE', '0.35'))
# A panel is one continuous window surface, so Oxygen's separate white edge
# glows have no place on it.  Even its 1–2% residual stack reads as a hard line
# at the side panel's window-facing edge.
PANEL_GLOW_SCALE = float(os.environ.get('OXYSCHEME_PANEL_GLOW', '0.0'))
# A panel samples one screen-tall light-to-base field: the north panel occupies
# only its first 34px, while a west/east panel carries that same field down the
# screen.  Its SVG is rotated, so an east/west panel needs the *local x* axis
# to make the gradient run down the physical screen.
# OxygenLightFlat's real titlebar is Background (198,209,224) → Blend
# (223,229,237): a 0.43 white overlay, not the 0.96 body-background estimate
# this replaced.  Use the titlebar's stop so a vertical panel joins it exactly.
PANEL_TOP_ALPHA = float(os.environ.get('OXYSCHEME_PANEL_TOP', '0.43'))
PANEL_BOTTOM_ALPHA = float(os.environ.get('OXYSCHEME_PANEL_BOTTOM', '0.0'))
# Plasma's five-pixel frame caps need their corresponding samples rather than
# restarting the field in each slice.  The top bar deliberately keeps a full
# titlebar-strength ramp; its light stop is shared with the top of a vertical
# side panel, which then carries that same tint down to the window base.
PANEL_CAP_FRAC = 5.0 / 1080.0
PANEL_EDGE_FRAC = 0.02
CENTRE_AMPLITUDE = float(os.environ.get('OXYSCHEME_AMPLITUDE', '0.12'))
# Oxygen shades with black. Plasma's accent lands on the Selection group, so
# ColorScheme-Highlight IS the accent colour -- pointing the dark end of every
# ramp at it makes the panel's shading tint with the theme instead of going grey.
# The light end stays white: it is a specular highlight, not a colour.
ACCENT_ROLE = os.environ.get('OXYSCHEME_ACCENT_ROLE', 'ColorScheme-Highlight')
ACCENT_RAMPS = os.environ.get('OXYSCHEME_ACCENT_RAMPS', '0') not in ('0', 'no', '')
# Oxygen's ramp starts at alpha 0, so the accent only reaches full strength at
# the very edge and the panel reads as a pale wash rather than the theme blue.
# The floor lifts the whole accent side so the colour is actually present.
ACCENT_FLOOR = float(os.environ.get('OXYSCHEME_ACCENT_FLOOR', '0.35'))

ROLES = [
    ("Text",             "#31363b"), ("Background",       "#eff0f1"),
    ("Highlight",        "#3daee9"), ("ViewText",         "#31363b"),
    ("ViewBackground",   "#fcfcfc"), ("ViewHover",        "#93cee9"),
    ("ViewFocus",        "#3daee9"), ("ButtonText",       "#31363b"),
    ("ButtonBackground", "#eff0f1"), ("ButtonHover",      "#93cee9"),
    ("ButtonFocus",      "#3daee9"), ("NegativeText",     "#da4453"),
    ("NeutralText",      "#f67400"), ("PositiveText",     "#27ae60"),
]

def stylesheet():
    return "\n" + "\n".join(
        "      .ColorScheme-%s {\n        color:%s;\n        stop-color:%s;\n      }"
        % (n, c, c) for n, c in ROLES) + "\n    "

# ---------- colour ----------
def parse_hex(c):
    c = c.strip().lstrip('#')
    if len(c) == 3: c = ''.join(ch*2 for ch in c)
    if len(c) != 6: return None
    try: return tuple(int(c[i:i+2], 16)/255 for i in (0, 2, 4))
    except ValueError: return None

def chroma(rgb):    return max(rgb) - min(rgb)
def luminance(rgb): return 0.2126*rgb[0] + 0.7152*rgb[1] + 0.0722*rgb[2]
def achromatic(rgb): return chroma(rgb) <= CHROMA_MAX

# ---------- style ----------
def style_dict(el):
    d = {}
    for part in (el.get('style') or '').split(';'):
        if ':' in part:
            k, v = part.split(':', 1); d[k.strip()] = v.strip()
    return d

def set_style(el, d):
    el.set('style', ';'.join(f"{k}:{v}" for k, v in d.items() if v is not None))

def get_fill(el):
    d = style_dict(el)
    f = d.get('fill') or el.get('fill')
    o = d.get('fill-opacity', el.get('fill-opacity'))
    try: o = float(o) if o is not None else 1.0
    except ValueError: o = 1.0
    return f, o, d

PAINTED = {S+'path', S+'rect', S+'circle', S+'ellipse', S+'polygon'}
AUTO_ID = re.compile(r'^(path|rect|circle|ellipse|g|use|image|tspan|text|'
                     r'flowRoot|layer|polygon|stop|linearGradient|radialGradient)'
                     r'[0-9][0-9_-]*$')

class Doc:
    def __init__(self, root):
        self.root = root
        self.idx = {e.get('id'): e for e in root.iter() if e.get('id')}
        self.defs = root.find(S+'defs')
        if self.defs is None:
            self.defs = ET.Element(S+'defs'); root.insert(0, self.defs)
        self.n = 0
    def stops(self, gid, seen=()):
        g = self.idx.get(gid)
        if g is None or gid in seen: return []
        own = []
        for st in g.findall(S+'stop'):
            sd = style_dict(st)
            c = sd.get('stop-color') or st.get('stop-color') or '#000000'
            o = sd.get('stop-opacity', st.get('stop-opacity'))
            try: o = float(o) if o is not None else 1.0
            except ValueError: o = 1.0
            own.append((st.get('offset') or '0', c, o))
        if own: return own
        href = g.get(X+'href') or g.get('href')
        return self.stops(href[1:], seen+(gid,)) if href else []
    def uid(self, b):
        self.n += 1; return f"{b}-oxysch{self.n}"
    def publish(self, gid, el):
        """defs added during the run must join the index -- a later pass looks
        gradients up by id, and idx is built once at construction."""
        self.idx[gid] = el
        self.defs.append(el)
        return gid


_TF = re.compile(r'(matrix|translate|scale|rotate)\s*\(([^)]*)\)')

def _nums(t):
    return [float(x) for x in re.split(r'[,\s]+', t.strip()) if x not in ('',)]

def axis_signs(el, parents):
    """Sign of the cumulative x/y scale above and on `el`.

    Oxygen draws several framesvg slices through a Y-flip -- `north-center` is
    matrix(1,0,0,-1,...) -- so an objectBoundingBox gradient authored top-to-
    bottom comes out upside down on exactly those slices and the panel ends up
    lighter at the FOOT than at the edge. Walk the transform chain and flip."""
    a, d = 1.0, 1.0            # 2x2 diagonal is all we need for scale sign
    node = el
    while node is not None:
        t = node.get('transform')
        if t:
            for kind, body in _TF.findall(t):
                v = _nums(body)
                if kind == 'matrix' and len(v) >= 4:
                    a *= v[0]; d *= v[3]
                elif kind == 'scale':
                    a *= v[0]; d *= (v[1] if len(v) > 1 else v[0])
        node = parents.get(node)
    return (1 if a >= 0 else -1), (1 if d >= 0 else -1)

def gradient_screen_y_sign(el, parents, axis):
    """Which way an element-local gradient runs on the physical screen.

    `east-*` and `west-*` slices are rotated copies of the horizontal art, so
    their local *x* gradient maps to physical Y through matrix ``b`` rather
    than ``a``.  A panel is meant to follow the window ramp from the screen's
    top down, independent of which edge it sits on.  The old scale-only check
    happened to work for the ordinary SVG, but selected the inverse ramp for
    the rotated opaque artwork that adaptive transparency uses.
    """
    # [a b c d], mapping local (x,y) to screen (a*x+c*y, b*x+d*y).
    m = (1.0, 0.0, 0.0, 1.0)
    node = el
    while node is not None:
        t = node.get('transform')
        if t:
            for kind, body in _TF.findall(t):
                v = _nums(body)
                if kind == 'matrix' and len(v) >= 4:
                    q = tuple(v[:4])
                elif kind == 'scale' and v:
                    q = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0])
                elif kind == 'rotate' and v:
                    r = math.radians(v[0]); q = (math.cos(r), math.sin(r),
                                                   -math.sin(r), math.cos(r))
                else:
                    continue
                a, b, c, d = q; e, f, g, h = m
                # Parent transforms apply after child transforms.
                m = (a*e + c*f, b*e + d*f, a*g + c*h, b*g + d*h)
        node = parents.get(node)
    # The local X axis of east/west slices is the panel's thin direction;
    # north/south use local Y.  We care only about its physical Y component.
    component = m[1] if axis == 'h' else m[3]
    return 1 if component >= 0 else -1

def gradient_screen_x_sign(el, parents, axis):
    """Sign of an element-local gradient along physical screen X."""
    m = (1.0, 0.0, 0.0, 1.0)
    node = el
    while node is not None:
        t = node.get('transform')
        if t:
            for kind, body in _TF.findall(t):
                v = _nums(body)
                if kind == 'matrix' and len(v) >= 4:
                    q = tuple(v[:4])
                elif kind == 'scale' and v:
                    q = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0])
                elif kind == 'rotate' and v:
                    r = math.radians(v[0]); q = (math.cos(r), math.sin(r),
                                                   -math.sin(r), math.cos(r))
                else:
                    continue
                a, b, c, d = q; e, f, g, h = m
                m = (a*e + c*f, b*e + d*f, a*g + c*h, b*g + d*h)
        node = parents.get(node)
    component = m[0] if axis == 'h' else m[2]
    return 1 if component >= 0 else -1

def panel_gradient_invert(el, parents, axis, location):
    """Put the field's light stop at the physical top of every panel."""
    return gradient_screen_y_sign(el, parents, axis) < 0

def panel_band(location, slice_name):
    """Return this framesvg slice's interval in the shared screen field."""
    if location == 'north':
        if slice_name == 'top':
            return (0.0, PANEL_EDGE_FRAC)
        if slice_name == 'bottom':
            return (1.0 - PANEL_EDGE_FRAC, 1.0)
        return (PANEL_EDGE_FRAC, 1.0 - PANEL_EDGE_FRAC)
    if location in ('east', 'west'):
        if slice_name == 'top':
            return (0.0, PANEL_CAP_FRAC)
        if slice_name == 'bottom':
            return (1.0 - PANEL_CAP_FRAC, 1.0)
        return (PANEL_CAP_FRAC, 1.0 - PANEL_CAP_FRAC)
    if location == 'south':
        return (1.0 - PANEL_EDGE_FRAC, 1.0)
    return None

# ---------- role inference ----------
def role_family(filename):
    n = os.path.basename(filename)
    if n.startswith(('button', 'actionbutton')):          return 'Button'
    if n.startswith(('lineedit', 'viewitem', 'listitem')): return 'View'
    return None

def role_for(ancestry, family):
    ctx = ' '.join(filter(None, ancestry)).lower()
    if 'selected' in ctx:  return 'ColorScheme-Highlight'
    if 'attention' in ctx: return 'ColorScheme-NeutralText'
    if family == 'Button':
        if 'focus' in ctx: return 'ColorScheme-ButtonFocus'
        if 'hover' in ctx: return 'ColorScheme-ButtonHover'
        return 'ColorScheme-ButtonBackground'
    if family == 'View':
        if 'focus' in ctx: return 'ColorScheme-ViewFocus'
        if 'hover' in ctx: return 'ColorScheme-ViewHover'
        return 'ColorScheme-ViewBackground'
    if 'focus' in ctx or 'hover' in ctx: return 'ColorScheme-Highlight'
    return 'ColorScheme-Background'

def is_hint(eid): return bool(eid) and 'hint-' in eid

# Plasma stencils and drop shadows. `mask-*` defines the blur/opacity region --
# only its alpha is read, so recolouring it is meaningless; `shadow-*` is a drop
# shadow and must stay dark or it inverts on a light scheme.
SKIP_PREFIX = ('mask-', 'shadow-')

def addressable(eid):
    """an id Plasma might render by name (framesvg slice, state, glyph)"""
    return bool(eid) and not is_hint(eid) and not AUTO_ID.match(eid)

def skipped(eid):
    return bool(eid) and eid.startswith(SKIP_PREFIX)

# ---------- gloss for opaque colour ramps ----------
def gloss_gradient(doc, src_gid, stops):
    lums = []
    for _, c, _ in stops:
        rgb = parse_hex(c); lums.append(luminance(rgb) if rgb else 0.0)
    mid = sum(lums)/len(lums)
    out = []
    for L in lums:
        if L >= mid:
            a = 0.0 if mid >= 1.0 else (L-mid)/(1.0-mid); out.append(('#ffffff', a))
        else:
            a = 0.0 if mid <= 0.0 else 1.0 - L/mid;       out.append(('#000000', a))
    src = doc.idx.get(src_gid)
    new = ET.Element(src.tag if src is not None else S+'linearGradient')
    if src is not None:
        for k, v in src.attrib.items():
            if k not in ('id', X+'href', 'href'): new.set(k, v)
        href = src.get(X+'href') or src.get('href')
        if href and not any(a in src.attrib for a in ('x1','x2','y1','y2','cx','cy','r')):
            par = doc.idx.get(href[1:])
            if par is not None:
                for k, v in par.attrib.items():
                    if k not in ('id', X+'href', 'href') and k not in new.attrib:
                        new.set(k, v)
    for (off, _, o), (col, a) in zip(stops, out):
        st = ET.SubElement(new, S+'stop')
        st.set('offset', off)
        st.set('style', f"stop-color:{col};stop-opacity:{max(0.0,min(1.0,a))*o:.4f}")
    gid = doc.uid(src_gid); new.set('id', gid)
    return doc.publish(gid, new)

def respin_alpha(doc, src_gid, stops, mode, axis='v', invert=False, panel=False,
                 band=None, panel_location=None):
    """Rebuild an alpha-ramp gradient under `flip` or `centre`."""
    src = doc.idx.get(src_gid)
    offs   = [float(o) for o, _, _ in stops]
    alphas = [a for _, _, a in stops]
    cols   = [c for _, c, _ in stops]
    new = None
    if mode == 'flip':
        new = ET.Element(src.tag if src is not None else S+'linearGradient')
        if src is not None:
            for k, v in src.attrib.items():
                if k not in ('id', X+'href', 'href'): new.set(k, v)
            href = src.get(X+'href') or src.get('href')
            if href and not any(a in src.attrib for a in ('x1','x2','y1','y2','cx','cy','r')):
                par = doc.idx.get(href[1:])
                if par is not None:
                    for k, v in par.attrib.items():
                        if k not in ('id', X+'href', 'href') and k not in new.attrib:
                            new.set(k, v)
        lo, hi = min(offs), max(offs)
        pairs = [(lo + hi - o, c, a) for o, c, a in zip(offs, cols, alphas)]
        pairs.sort(key=lambda t: t[0])
    if mode == 'titlebar':
        new = ET.Element(S+'linearGradient')
        new.set('gradientUnits', 'objectBoundingBox')
        new.set('x1','0'); new.set('y1','0')
        new.set('x2', '1' if axis == 'h' else '0')
        new.set('y2', '0' if axis == 'h' else '1')
        hi, lo = ((PANEL_TOP_ALPHA, PANEL_BOTTOM_ALPHA) if panel
                  else (TOP_ALPHA, 0.0))
        if panel_location == 'south':
            # Likewise, the bottom bar samples the field after it has faded.
            hi = lo
        field_band = panel_band(panel_location, band) if panel else None
        if field_band is not None:
            f0, f1 = field_band
            span = hi - lo
            hi, lo = hi - span * f0, hi - span * f1
        ramp = ((0.0, hi), (1.0, lo))
        if invert: ramp = ((0.0, lo), (1.0, hi))
        for off, a in ramp:
            st = ET.SubElement(new, S+'stop')
            st.set('offset', f"{off:.4f}")
            st.set('style', f"stop-color:#ffffff;stop-opacity:{a:.4f}")
        gid = doc.uid(src_gid); new.set('id', gid)
        new.set('data-oxysch', 'body')
        return doc.publish(gid, new)

    if mode == 'centre':
        # Emit a LINEAR objectBoundingBox gradient regardless of what the source
        # was. Oxygen's panel ramps are radialGradients with r=2.5 in user space;
        # Plasma stretches that 5px centre slice across the whole panel, which
        # blows the radial into a soft blob instead of an even gradient. A
        # titlebar's gradient is linear and even, so this makes it one.
        new = ET.Element(S+'linearGradient')
        new.set('gradientUnits', 'objectBoundingBox')
        new.set('x1', '0'); new.set('y1', '0')
        new.set('x2', '1' if axis == 'h' else '0')
        new.set('y2', '0' if axis == 'h' else '1')
        m = sum(alphas)/len(alphas)
        dev = max(abs(a - m) for a in alphas) or 1.0
        pairs = []
        lo, hi = min(offs), max(offs)
        span = (hi - lo) or 1.0
        for o, a in zip(offs, alphas):
            amt = abs(a - m)/dev * CENTRE_AMPLITUDE
            pairs.append(((o - lo)/span, '#000000' if a > m else '#ffffff', amt))
    for o, c, a in pairs:
        st = ET.SubElement(new, S+'stop')
        st.set('offset', f"{o:.4f}")
        a = max(0.0, min(1.0, a))
        rgb = parse_hex(c)
        if ACCENT_RAMPS and rgb is not None and luminance(rgb) < 0.5:
            # the dark end: let the accent supply the colour via the stylesheet
            a = ACCENT_FLOOR + (1.0 - ACCENT_FLOOR) * a
            st.set('class', ACCENT_ROLE)
            st.set('style', f"stop-opacity:{a:.4f}")
        else:
            st.set('style', f"stop-color:{c};stop-opacity:{a:.4f}")
    gid = doc.uid(src_gid); new.set('id', gid)
    return doc.publish(gid, new)

def obb_clone(doc, gid):
    """Re-express a gradient in objectBoundingBox units so it can be reused on a
    sibling slice of a different size and position, keeping its axis."""
    src = doc.idx.get(gid)
    if src is None: return None
    def num(k, d=0.0):
        try: return float(src.get(k))
        except (TypeError, ValueError): return d
    horizontal = abs(num('x2') - num('x1')) > abs(num('y2') - num('y1', 1.0))
    new = ET.Element(S+'linearGradient')
    new.set('gradientUnits', 'objectBoundingBox')
    new.set('x1', '0'); new.set('y1', '0')
    new.set('x2', '1' if horizontal else '0')
    new.set('y2', '0' if horizontal else '1')
    for st in src.findall(S+'stop'):
        c = ET.SubElement(new, S+'stop')
        for k, v in st.attrib.items(): c.set(k, v)
    nid = doc.uid('edge'); new.set('id', nid)
    return doc.publish(nid, new)

# ---------- raster glows ----------
def _alpha_profile(px, w, h, n):
    rows = [sum(px[y*w+x][3] for x in range(w))/w/255 for y in range(h)]
    cols = [sum(px[y*w+x][3] for y in range(h))/h/255 for x in range(w)]
    def var(v):
        m = sum(v)/len(v); return sum((q-m)**2 for q in v)/len(v)
    vr, vc = var(rows), var(cols)
    if vr > vc*3:   return 'v', None, _samp(rows, n)
    if vc > vr*3:   return 'h', None, _samp(cols, n)
    corners = {'tl': (0,0), 'tr': (w-1,0), 'bl': (0,h-1), 'br': (w-1,h-1)}
    best, ba = 'tl', -1
    for k, (cx, cy) in corners.items():
        xs = range(0,2) if cx == 0 else range(max(0,w-2), w)
        ys = range(0,2) if cy == 0 else range(max(0,h-2), h)
        a = sum(px[yy*w+xx][3] for yy in ys for xx in xs)/4
        if a > ba: ba, best = a, k
    cx, cy = corners[best]; R = math.hypot(w-1, h-1) or 1
    buckets = [[] for _ in range(n)]
    for y in range(h):
        for x in range(w):
            d = math.hypot(x-cx, y-cy)/R
            buckets[min(n-1, int(d*n))].append(px[y*w+x][3]/255)
    return 'r', best, [(sum(b)/len(b) if b else 0.0) for b in buckets]

def _samp(prof, n):
    return [prof[min(len(prof)-1, int(i*(len(prof)-1)/(n-1)))] for i in range(n)]

def _glow_gradient(doc, px, w, h, role, n=6):
    axis, corner, prof = _alpha_profile(px, w, h, n)
    if axis == 'r':
        g = ET.Element(S+'radialGradient')
        g.set('cx', '0' if corner in ('tl','bl') else '1')
        g.set('cy', '0' if corner in ('tl','tr') else '1'); g.set('r', '1')
    else:
        g = ET.Element(S+'linearGradient')
        g.set('x1','0'); g.set('y1','0')
        g.set('x2', '0' if axis == 'v' else '1'); g.set('y2', '1' if axis == 'v' else '0')
    g.set('gradientUnits', 'objectBoundingBox')
    for i, a in enumerate(prof):
        st = ET.SubElement(g, S+'stop')
        st.set('offset', f"{i/(len(prof)-1):.4f}")
        st.set('class', role); st.set('style', f"stop-opacity:{a:.4f}")
    gid = doc.uid('glow'); g.set('id', gid)
    return doc.publish(gid, g)

def convert_rasters(doc, root, parents, family, stats):
    for im in list(root.iter(S+'image')):
        href = im.get(X+'href') or im.get('href') or ''
        if not href.startswith('data:image/png;base64,'): continue
        try:
            dec = png_rgba(base64.b64decode(re.sub(r'\s+', '', href.split(',',1)[1])))
        except Exception:
            dec = None
        if dec is None: stats['raster_undecodable'] += 1; continue
        w, h, px = dec
        if mean_chroma(px) < CHROMA_RASTER:
            stats['raster_kept'] += 1; continue      # achromatic: already shading
        anc, node = [], im
        while node is not None:
            if node.get('id'): anc.append(node.get('id'))
            node = parents.get(node)
        gid = _glow_gradient(doc, px, w, h, role_for(list(reversed(anc)), family))
        rect = ET.Element(S+'rect')
        for a in ('x','y','width','height','transform'):
            if im.get(a) is not None: rect.set(a, im.get(a))
        rect.set('style', f"fill:url(#{gid})")
        if im.get('id'): rect.set('id', im.get('id'))
        p = parents.get(im)
        if p is not None:
            p[list(p).index(im)] = rect; stats['raster_glow'] += 1

# ---------- the main transform ----------
def convert(src, dst, report=None):
    root = ET.parse(gzip.open(src)).getroot()
    doc = Doc(root)
    family = role_family(src)
    stats = dict(based_alpha=0, based_colour=0, recoloured=0, untouched_art=0,
                 skipped_chromatic=0, no_body=0, edge_shaded=0, glow_damped=0,
                 raster_glow=0, raster_kept=0, raster_undecodable=0,
                 panel_shadows_removed=0, panel_inner_edge_flattened=0,
                 panel_surface_opaque=0)
    parents = {c: p for p in root.iter() for c in p}

    def ancestry(el):
        out, n = [], el
        while n is not None:
            if n.get('id'): out.append(n.get('id'))
            n = parents.get(n)
        return list(reversed(out))

    def is_base_paint(el):
        """Does this element paint a BODY, or is it shading drawn on top?

        A glow fades to nothing -- Oxygen's outlines are white 1 -> 0. A body
        ends opaque. Taking the first painted child instead gets corners wrong:
        `north-bottomright` opens with a white glow and keeps its black body at
        index 1, and basing the glow paints a solid block where the rounded
        corner should be."""
        fill, fop, _ = get_fill(el)
        if not fill or fill == 'none': return False
        if fill.startswith('url(#'):
            stops = doc.stops(fill[5:-1])
            if not stops: return False
            alphas = [a for _, _, a in stops]
            return max(alphas) >= 0.9 and alphas[-1] >= 0.5
        return parse_hex(fill) is not None and fop >= 0.9

    def _achromatic_paint(el):
        fill, _, _ = get_fill(el)
        if not fill or fill == 'none': return False
        if fill.startswith('url(#'):
            cols = [parse_hex(c) for _, c, _ in doc.stops(fill[5:-1])]
            return bool(cols) and all(c is not None and achromatic(c) for c in cols)
        rgb = parse_hex(fill)
        return rgb is not None and achromatic(rgb)

    def first_body(el):
        cands = [el] if el.tag in PAINTED else \
                [c for c in el.iter() if c.tag in PAINTED and c is not el]
        base = [c for c in cands if is_base_paint(c)]
        # Prefer an ACHROMATIC body. Oxygen parks opaque marker rects (#ffff00,
        # #008000) as the first child of some slices; taking one as the body got
        # it rejected as chromatic and left the real black body underneath with
        # no scheme colour behind it -- which is why the panel's bottom-left
        # corner stayed pure black.
        for c in base:
            if _achromatic_paint(c): return c
        return base[0] if base else None

    # INNERMOST addressable elements: the framesvg slice / glyph level.
    # Not outermost -- Oxygen nests the whole drawing under <g id="base">, and
    # treating that as the target excluded every slice underneath it.
    targets, seen = [], set()
    for el in root.iter():
        eid = el.get('id')
        if not addressable(eid) or skipped(eid) or eid in seen: continue
        if any(addressable(ch.get('id')) for ch in el.iter() if ch is not el):
            continue                      # has an addressable descendant
        seen.add(eid); targets.append(el)

    centre_ramp = {}     # framesvg prefix -> gradient the centre ended up with

    for el in targets:
        body = first_body(el)
        if body is None: stats['no_body'] += 1; continue
        fill, fop, sd = get_fill(body)
        if not fill or fill == 'none': stats['no_body'] += 1; continue
        role = role_for(ancestry(body), family)

        if fill.startswith('url(#'):
            stops = doc.stops(fill[5:-1])
            if not stops: stats['no_body'] += 1; continue
            cols = [parse_hex(c) for _, c, _ in stops]
            if any(c is None for c in cols): stats['no_body'] += 1; continue
            if not all(achromatic(c) for c in cols):
                stats['skipped_chromatic'] += 1; continue
            lums = [luminance(c) for c in cols]
            alphas = [a for _, _, a in stops]
            dl, da = max(lums)-min(lums), max(alphas)-min(alphas)
            if dl > LUM_SPREAD:
                is_panel = os.path.basename(src).startswith('panel-background')
                # Adaptive transparency swaps a panel to opaque/widgets, whose
                # body is an opaque colour ramp rather than the alpha ramp used
                # by the ordinary and solid variants.  Give it the SAME derived
                # white titlebar ramp instead of preserving Oxygen's dark gloss.
                if is_panel and ALPHA_MODE == 'titlebar':
                    eid_l = (el.get('id') or '').lower()
                    ax = 'h' if eid_l.startswith(('east-', 'west-')) else 'v'
                    inv = panel_gradient_invert(body, parents, ax,
                                                eid_l.split('-', 1)[0])
                    band = eid_l.rsplit('-', 1)[-1] if '-' in eid_l else None
                    gid = respin_alpha(doc, fill[5:-1], stops, ALPHA_MODE, ax,
                                       inv, True, band, eid_l.split('-', 1)[0])
                    base = copy.deepcopy(body); base.attrib.pop('id', None)
                    bd = style_dict(base); bd['fill'] = 'currentColor'
                    bd.pop('fill-opacity', None); set_style(base, bd)
                    base.set('class', role)
                    od = style_dict(body); od['fill'] = f'url(#{gid})'; set_style(body, od)
                    p = parents[body]; p.insert(list(p).index(body), base)
                    if eid_l.endswith('-center'):
                        centre_ramp[eid_l[:-len('-center')]] = gid
                    stats['based_colour'] += 1
                    continue
                # opaque colour ramp: split into role base + derived alpha gloss
                gid = gloss_gradient(doc, fill[5:-1], stops)
                base = copy.deepcopy(body); base.attrib.pop('id', None)
                bd = style_dict(base); bd['fill'] = 'currentColor'
                bd.pop('fill-opacity', None); set_style(base, bd)
                base.set('class', role)
                od = style_dict(body); od['fill'] = f'url(#{gid})'; set_style(body, od)
                p = parents[body]; p.insert(list(p).index(body), base)
                stats['based_colour'] += 1
            elif da > ALPHA_SPREAD:
                # alpha ramp: it IS the shading. Put the scheme colour
                # underneath so it tints instead of flattening, then treat the
                # ramp itself according to ALPHA_MODE.
                base = copy.deepcopy(body); base.attrib.pop('id', None)
                bd = style_dict(base); bd['fill'] = 'currentColor'
                bd.pop('fill-opacity', None); set_style(base, bd)
                base.set('class', role)
                p = parents[body]; p.insert(list(p).index(body), base)
                if ALPHA_MODE in ('flip', 'centre', 'titlebar'):
                    eid_l = (el.get('id') or '').lower()
                    is_panel = os.path.basename(src).startswith('panel-background')
                    ax = (('h' if eid_l.startswith(('east-', 'west-')) else 'v')
                          if is_panel else
                          ('h' if ('east' in eid_l or 'west' in eid_l) else 'v'))
                    loc = eid_l.split('-', 1)[0] if is_panel else None
                    inv = (panel_gradient_invert(body, parents, ax, loc)
                           if is_panel else gradient_screen_y_sign(body, parents, ax) < 0)
                    band = eid_l.rsplit('-', 1)[-1] if '-' in eid_l else None
                    gid = respin_alpha(doc, fill[5:-1], stops, ALPHA_MODE, ax,
                                       inv, is_panel, band, loc)
                    od = style_dict(body); od['fill'] = f'url(#{gid})'
                    set_style(body, od)
                else:
                    gid = fill[5:-1]
                eid = el.get('id') or ''
                if eid.endswith('-center'):
                    centre_ramp[eid[:-len('-center')]] = gid
                stats['based_alpha'] += 1
            else:
                stats['untouched_art'] += 1
            continue

        rgb = parse_hex(fill)
        if rgb is None: stats['no_body'] += 1; continue
        if not achromatic(rgb): stats['skipped_chromatic'] += 1; continue
        if fop >= 0.90:
            sd['fill'] = 'currentColor'; set_style(body, sd); body.set('class', role)
            stats['recoloured'] += 1
        else:
            base = copy.deepcopy(body); base.attrib.pop('id', None)
            bd = style_dict(base); bd['fill'] = 'currentColor'
            bd.pop('fill-opacity', None); set_style(base, bd)
            base.set('class', role)
            p = parents[body]; p.insert(list(p).index(body), base)
            stats['based_alpha'] += 1

    # A framesvg's edge slices whose body is a flat solid read as a lighter
    # flat block against the shaded centre -- that is the "blank space" at the
    # panel's right end. Stock hides it by painting every slice black. Give them
    # the centre's own ramp, re-expressed in objectBoundingBox units so it lands
    # correctly on a slice of a different size.
    is_panel_file = os.path.basename(src).startswith('panel-background')
    for prefix, gid in centre_ramp.items():
        centre_el = doc.idx.get(f"{prefix}-center")
        c_sx, c_sy = axis_signs(centre_el, parents) if centre_el is not None else (1, 1)
        ax = (('h' if prefix.lower() in ('east', 'west') else 'v')
              if is_panel_file else
              ('h' if ('east' in prefix.lower() or 'west' in prefix.lower()) else 'v'))
        for side in ('left', 'right', 'top', 'bottom'):
            el = doc.idx.get(f"{prefix}-{side}")
            if el is None: continue
            cands = [el] if el.tag in PAINTED else \
                    [c for c in el.iter() if c.tag in PAINTED and c is not el]
            body = next((c for c in cands if get_fill(c)[0] == 'currentColor'), None)
            if body is None:
                continue            # already carries its own art
            e_sx, e_sy = axis_signs(body, parents)
            inv = (panel_gradient_invert(body, parents, ax, prefix.lower())
                   if is_panel_file else gradient_screen_y_sign(body, parents, ax) < 0)
            if is_panel_file and ALPHA_MODE == 'titlebar':
                # give this edge its OWN band of the panel ramp, or the seam steps
                use = respin_alpha(doc, gid, doc.stops(gid), ALPHA_MODE, ax,
                                   inv, True, side, prefix.lower())
            else:
                use = obb_clone(doc, gid)
                if use is None: continue
                if (e_sy < 0) != (c_sy < 0):
                    g2 = doc.idx.get(use); sts = g2.findall(S+'stop')
                    offs = [st.get('offset') for st in sts]
                    for st, o in zip(sts, reversed(offs)): st.set('offset', o)
            over = copy.deepcopy(body)
            over.attrib.pop('id', None); over.attrib.pop('class', None)
            od = style_dict(over); od['fill'] = f'url(#{use})'
            od.pop('fill-opacity', None); set_style(over, od)
            p = parents.get(body)
            if p is not None:
                p.insert(list(p).index(body) + 1, over)
                stats['edge_shaded'] += 1

    if is_panel_file:
        # `west-right` and `east-left` are the screen-facing inner edges of a
        # vertical panel.  Oxygen puts a separate stack of decorative strokes
        # in those thin slices.  Once the panel is a window surface rather than
        # a dark floating bar, that stack becomes a full-height seam.  The
        # first paint is the slice body and the second is the ramp above; keep
        # those and discard only the old edge decoration.
        for edge_id in ('west-right', 'east-left'):
            edge = doc.idx.get(edge_id)
            if edge is None:
                continue
            for child in list(edge)[2:]:
                edge.remove(child)
                stats['panel_inner_edge_flattened'] += 1

    # Damp Oxygen's white edge highlights. They are alpha ramps of pure white at
    # full opacity -- right over a near-black panel, a hard line over a light
    # one. Scaling keeps the outline and loses the blowout. The panel needs a
    # harder damp because its surface IS the bright top of the ramp.
    gscale = (PANEL_GLOW_SCALE
              if os.path.basename(src).startswith('panel-background')
              else GLOW_SCALE)
    if gscale < 1.0:
        for gid, g in list(doc.idx.items()):
            if g.tag not in (S+'linearGradient', S+'radialGradient'): continue
            if g.get('data-oxysch') == 'body':
                continue                 # a body ramp we built, not a glow
            own = g.findall(S+'stop')
            resolved = doc.stops(gid)
            if not resolved: continue
            cols = [parse_hex(c) for _, c, _ in resolved]
            alphas = [a for _, _, a in resolved]
            if any(c is None for c in cols): continue
            if not all(achromatic(c) for c in cols): continue
            if not all(luminance(c) > 0.5 for c in cols): continue   # light only
            if max(alphas) - min(alphas) <= ALPHA_SPREAD: continue   # a ramp only
            if own:
                for st, a in zip(own, alphas):
                    sd = style_dict(st)
                    sd['stop-color'] = sd.get('stop-color') or st.get('stop-color') or '#ffffff'
                    sd['stop-opacity'] = f"{a*gscale:.4f}"
                    st.attrib.pop('stop-opacity', None); st.attrib.pop('stop-color', None)
                    set_style(st, sd); stats['glow_damped'] += 1
            else:
                # No stops of its own: it inherits them through xlink:href. Six
                # of the glows in `north-bottom` do exactly that, which is how
                # they escaped damping and left a 1px near-white line at the
                # panel's foot. Materialise damped stops here rather than edit
                # the shared parent, which body ramps also point at.
                g.attrib.pop(X+'href', None); g.attrib.pop('href', None)
                for (off, col, a) in resolved:
                    st = ET.SubElement(g, S+'stop')
                    st.set('offset', off)
                    st.set('style', f"stop-color:{col};stop-opacity:{a*gscale:.4f}")
                    stats['glow_damped'] += 1

    convert_rasters(doc, root, parents, family, stats)

    if is_panel_file:
        # Plasma's stock panel surface is deliberately 70% transparent so the
        # dark Oxygen bar can float above a wallpaper.  This theme instead uses
        # the panel as a continuation of an empty window: the Background role
        # must therefore be opaque, with only the white titlebar tint varying.
        for el in root.iter():
            fill, _, _ = get_fill(el)
            surface = (fill == 'currentColor' and
                       'ColorScheme-Background' in (el.get('class') or ''))
            if fill and fill.startswith('url(#'):
                gradient = doc.idx.get(fill[5:-1])
                surface = surface or (gradient is not None and
                                      gradient.get('data-oxysch') == 'body')
            if surface:
                sd = style_dict(el)
                if sd.get('opacity') != '1':
                    sd['opacity'] = '1'
                    set_style(el, sd)
                    stats['panel_surface_opaque'] += 1

        # Panel shadows are a separate nine-slice frame (`shadow-*`), not part
        # of the panel body's shading.  Remove the whole frame so a panel reads
        # as one continuous window surface, with no floating halo or drop.
        for el in list(root.iter()):
            if (el.get('id') or '').startswith('shadow-'):
                parent = parents.get(el)
                if parent is not None:
                    parent.remove(el)
                    stats['panel_shadows_removed'] += 1

    st = None
    for e in root.iter(S+'style'):
        if e.get('id') == 'current-color-scheme': st = e; break
    if st is None:
        st = ET.Element(S+'style')
        st.set('type', 'text/css'); st.set('id', 'current-color-scheme')
        doc.defs.insert(0, st)
    st.text = stylesheet()

    with gzip.open(dst, 'wb') as f:
        f.write(ET.tostring(root, encoding='utf-8', xml_declaration=True))
    if report is not None: report.update(stats)
    return stats

if __name__ == '__main__':
    print(os.path.basename(sys.argv[1]), convert(sys.argv[1], sys.argv[2]))

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
ALPHA_MODE = os.environ.get('OXYSCHEME_ALPHA_MODE', 'centre')
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

def respin_alpha(doc, src_gid, stops, mode, axis='v'):
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
                 skipped_chromatic=0, no_body=0, edge_shaded=0,
                 raster_glow=0, raster_kept=0, raster_undecodable=0)
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
                if ALPHA_MODE in ('flip', 'centre'):
                    eid_l = (el.get('id') or '').lower()
                    ax = 'h' if ('east' in eid_l or 'west' in eid_l) else 'v'
                    gid = respin_alpha(doc, fill[5:-1], stops, ALPHA_MODE, ax)
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
    for prefix, gid in centre_ramp.items():
        obb = obb_clone(doc, gid)
        if obb is None: continue
        for side in ('left', 'right', 'top', 'bottom'):
            el = doc.idx.get(f"{prefix}-{side}")
            if el is None: continue
            # the body we recoloured, found by its paint -- NOT first_body(),
            # which no longer recognises it now that its fill is currentColor
            cands = [el] if el.tag in PAINTED else \
                    [c for c in el.iter() if c.tag in PAINTED and c is not el]
            body = next((c for c in cands if get_fill(c)[0] == 'currentColor'), None)
            if body is None:
                continue            # already carries its own art
            over = copy.deepcopy(body)
            over.attrib.pop('id', None); over.attrib.pop('class', None)
            od = style_dict(over); od['fill'] = f'url(#{obb})'
            od.pop('fill-opacity', None); set_style(over, od)
            p = parents.get(body)
            if p is not None:
                p.insert(list(p).index(body) + 1, over)
                stats['edge_shaded'] += 1

    convert_rasters(doc, root, parents, family, stats)

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

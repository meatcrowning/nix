#!/usr/bin/env python3
"""Convert an Oxygen Plasma-theme SVG so it follows the user's colour scheme.

Oxygen bakes base colour and gloss into one gradient, which is why it cannot
follow a scheme.  Breeze separates them: a flat ColorScheme-* base with the
gloss expressed as black/white alpha on top.  This applies that split
mechanically.

Only achromatic paint is touched -- saturated colour is Oxygen's identity and
stays baked.  Plasma hint-* elements are metadata (never drawn) and are never
touched.
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

CHROMA_MAX = 0.12       # above this, treat the colour as chromatic and leave it
                        # absolute (max-min), NOT relative saturation: Oxygen's
                        # greys are blue-tinted and dark, so relative saturation
                        # reads #2b2f34 as 17% coloured when its real chroma is 3.5%
OPAQUE_MIN = 0.90       # fill-opacity below this is already a shading layer

# every role, with both color: and stop-color: so gradient stops recolour too
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
    out = []
    for name, col in ROLES:
        out.append("      .ColorScheme-%s {\n        color:%s;\n        stop-color:%s;\n      }"
                   % (name, col, col))
    return "\n" + "\n".join(out) + "\n    "

# ---------- colour helpers ----------
def parse_hex(c):
    c = c.strip().lstrip('#')
    if len(c) == 3: c = ''.join(ch*2 for ch in c)
    if len(c) != 6: return None
    try: return tuple(int(c[i:i+2], 16)/255 for i in (0, 2, 4))
    except ValueError: return None

def chroma(rgb):
    return max(rgb) - min(rgb)

def luminance(rgb):
    r, g, b = rgb
    return 0.2126*r + 0.7152*g + 0.0722*b

def achromatic(rgb):
    return chroma(rgb) <= CHROMA_MAX

# ---------- style string helpers ----------
def style_dict(el):
    d = {}
    for part in (el.get('style') or '').split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            d[k.strip()] = v.strip()
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

# ---------- gradient resolution ----------
class Doc:
    def __init__(self, root):
        self.root = root
        self.idx = {e.get('id'): e for e in root.iter() if e.get('id')}
        self.defs = root.find(S+'defs')
        if self.defs is None:
            self.defs = ET.Element(S+'defs')
            root.insert(0, self.defs)
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

    def uid(self, base):
        self.n += 1
        return f"{base}-oxysch{self.n}"

def gloss_gradient(doc, src_gid, stops):
    """A copy of the source gradient with every stop rewritten as black/white
    alpha representing its deviation from the ramp's mean luminance."""
    lums, alphas = [], []
    for _, c, _ in stops:
        rgb = parse_hex(c)
        lums.append(luminance(rgb) if rgb else 0.0)
    mid = sum(lums)/len(lums)
    for L in lums:
        if L >= mid:
            a = 0.0 if mid >= 1.0 else (L-mid)/(1.0-mid)   # white over base
            alphas.append(('#ffffff', min(1.0, max(0.0, a))))
        else:
            a = 0.0 if mid <= 0.0 else 1.0 - L/mid          # black over base
            alphas.append(('#000000', min(1.0, max(0.0, a))))

    src = doc.idx.get(src_gid)
    new = ET.Element(src.tag if src is not None else S+'linearGradient')
    if src is not None:
        for k, v in src.attrib.items():
            if k not in ('id', X+'href', 'href'):
                new.set(k, v)
        # a gradient that only href'd another still needs its geometry
        href = src.get(X+'href') or src.get('href')
        if href and not any(a in src.attrib for a in ('x1','x2','y1','y2','cx','cy','r')):
            par = doc.idx.get(href[1:])
            if par is not None:
                for k, v in par.attrib.items():
                    if k not in ('id', X+'href', 'href') and k not in new.attrib:
                        new.set(k, v)
    for (off, _, o), (col, a) in zip(stops, alphas):
        st = ET.SubElement(new, S+'stop')
        st.set('offset', off)
        st.set('style', f"stop-color:{col};stop-opacity:{a*o:.4f}")
    gid = doc.uid(src_gid)
    new.set('id', gid)
    doc.defs.append(new)
    return gid


# ---------- embedded raster glows ----------
CHROMA_RASTER = 0.10    # below this the raster is a shadow/gloss: scheme-agnostic

def _alpha_profile(px, w, h, n):
    """mean alpha sampled at n points along the dominant falloff axis"""
    rows = [sum(px[y*w+x][3] for x in range(w))/w/255 for y in range(h)]
    cols = [sum(px[y*w+x][3] for y in range(h))/h/255 for x in range(w)]
    def var(v):
        m = sum(v)/len(v); return sum((q-m)**2 for q in v)/len(v)
    vr, vc = var(rows), var(cols)
    if vr > vc*3:   axis, prof = 'v', rows
    elif vc > vr*3: axis, prof = 'h', cols
    else:           axis, prof = 'r', None
    if axis == 'r':
        # radial: find the corner with most alpha, sample along its diagonal
        corners = {'tl': (0,0), 'tr': (w-1,0), 'bl': (0,h-1), 'br': (w-1,h-1)}
        best, ba = 'tl', -1
        for k,(cx,cy) in corners.items():
            a = sum(px[(cy if cy<2 else cy)*w + (cx if cx<2 else cx)][3] for _ in (0,))
            # average a 2x2 patch at that corner
            xs = range(0,2) if cx == 0 else range(w-2,w)
            ys = range(0,2) if cy == 0 else range(h-2,h)
            a = sum(px[yy*w+xx][3] for yy in ys for xx in xs)/4
            if a > ba: ba, best = a, k
        cx, cy = corners[best]
        R = math.hypot(w-1, h-1)
        buckets = [[] for _ in range(n)]
        for y in range(h):
            for x in range(w):
                d = math.hypot(x-cx, y-cy)/R
                buckets[min(n-1, int(d*n))].append(px[y*w+x][3]/255)
        prof = [(sum(b)/len(b) if b else 0.0) for b in buckets]
        return 'r', best, prof
    step = max(1, len(prof)//n)
    samp = [prof[min(len(prof)-1, int(i*(len(prof)-1)/(n-1)))] for i in range(n)]
    return axis, None, samp

def _glow_gradient(doc, px, w, h, role, n=6):
    axis, corner, prof = _alpha_profile(px, w, h, n)
    if axis == 'r':
        g = ET.Element(S+'radialGradient')
        cx, cy = (0 if corner in ('tl','bl') else 1), (0 if corner in ('tl','tr') else 1)
        g.set('cx', str(cx)); g.set('cy', str(cy)); g.set('r', '1')
    else:
        g = ET.Element(S+'linearGradient')
        if axis == 'v': g.set('x1','0'); g.set('y1','0'); g.set('x2','0'); g.set('y2','1')
        else:           g.set('x1','0'); g.set('y1','0'); g.set('x2','1'); g.set('y2','0')
    g.set('gradientUnits', 'objectBoundingBox')
    for i, a in enumerate(prof):
        st = ET.SubElement(g, S+'stop')
        st.set('offset', f"{i/(len(prof)-1):.4f}")
        st.set('class', role)
        st.set('style', f"stop-opacity:{a:.4f}")
    gid = doc.uid('glow')
    g.set('id', gid); doc.defs.append(g)
    return gid

def convert_rasters(doc, root, parent_map, family, stats):
    for im in list(root.iter(S+'image')):
        href = im.get(X+'href') or im.get('href') or ''
        if not href.startswith('data:image/png;base64,'):
            continue
        try:
            data = base64.b64decode(re.sub(r'\s+', '', href.split(',',1)[1]))
            dec = png_rgba(data)
        except Exception:
            dec = None
        if dec is None:
            stats['raster_undecodable'] += 1; continue
        w, h, px = dec
        if mean_chroma(px) < CHROMA_RASTER:
            # achromatic shadow / gloss: already survives any scheme
            stats['raster_kept'] += 1; continue
        # role from ancestry
        anc, node = [], im
        while node is not None:
            if node.get('id'): anc.append(node.get('id'))
            node = parent_map.get(node)
        role = role_for('', list(reversed(anc)), family)
        gid = _glow_gradient(doc, px, w, h, role)
        rect = ET.Element(S+'rect')
        for a in ('x','y','width','height','transform'):
            if im.get(a) is not None: rect.set(a, im.get(a))
        rect.set('style', f"fill:url(#{gid})")
        if im.get('id'): rect.set('id', im.get('id'))
        p = parent_map.get(im)
        if p is not None:
            p[list(p).index(im)] = rect
            stats['raster_glow'] += 1

# ---------- role inference ----------
def role_family(filename):
    n = os.path.basename(filename)
    if n.startswith(('button', 'actionbutton')):        return 'Button'
    if n.startswith(('lineedit', 'viewitem', 'listitem')): return 'View'
    return None

def role_for(eid, ancestry, family):
    ctx = ' '.join(filter(None, ancestry + [eid])).lower()
    # state words that carry their own meaning whatever the file's family
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
    if 'focus' in ctx: return 'ColorScheme-Highlight'
    if 'hover' in ctx: return 'ColorScheme-Highlight'
    return 'ColorScheme-Background'

def is_hint(eid):
    return bool(eid) and ('hint-' in eid)

PAINTED = {S+'path', S+'rect', S+'circle', S+'ellipse', S+'polygon'}

def convert(src, dst, report=None):
    root = ET.parse(gzip.open(src)).getroot()
    doc = Doc(root)
    family = role_family(src)
    stats = dict(grad=0, solid=0, skipped_chromatic=0, skipped_hint=0, shading=0,
                 raster_glow=0, raster_kept=0, raster_undecodable=0)

    # walk with parent + ancestry so we can wrap elements and infer role context
    def walk(parent, ancestry):
        for el in list(parent):
            eid = el.get('id') or ''
            anc = ancestry + [eid] if eid else ancestry
            if el.tag in PAINTED:
                handle(parent, el, eid, ancestry, stats)
            elif el.tag not in (S+'defs',):
                walk(el, anc)

    def handle(parent, el, eid, ancestry, stats):
        if is_hint(eid):
            stats['skipped_hint'] += 1; return
        fill, fop, sd = get_fill(el)
        if not fill or fill == 'none': return
        role = role_for(eid, ancestry, family)

        if fill.startswith('url(#'):
            gid = fill[5:-1]
            stops = doc.stops(gid)
            if not stops: return
            cols = [parse_hex(c) for _, c, _ in stops]
            if any(c is None for c in cols): return
            if not all(achromatic(c) for c in cols):
                stats['skipped_chromatic'] += 1; return
            # split: flat role base + derived gloss overlay, inside a <g> that
            # keeps the original id (Plasma renders sub-elements BY ID)
            gloss = gloss_gradient(doc, gid, stops)
            base = copy.deepcopy(el)
            over = copy.deepcopy(el)
            for e in (base, over):
                e.attrib.pop('id', None)
            bd = style_dict(base); bd['fill'] = 'currentColor'; bd.pop('fill-opacity', None)
            set_style(base, bd); base.set('class', role)
            od = style_dict(over); od['fill'] = f'url(#{gloss})'
            set_style(over, od)
            g = ET.Element(S+'g'); g.set('id', eid) if eid else None
            g.append(base); g.append(over)
            parent[list(parent).index(el)] = g
            stats['grad'] += 1
            return

        rgb = parse_hex(fill)
        if rgb is None: return
        if not achromatic(rgb):
            stats['skipped_chromatic'] += 1; return
        if fop < OPAQUE_MIN:
            # already a translucent shading layer -- survives any scheme as-is
            stats['shading'] += 1; return
        sd['fill'] = 'currentColor'
        set_style(el, sd); el.set('class', role)
        stats['solid'] += 1

    walk(root, [])

    parent_map = {c: p for p in root.iter() for c in p}
    convert_rasters(doc, root, parent_map, family, stats)

    # inject / replace the stylesheet Plasma substitutes into
    st = None
    for e in root.iter(S+'style'):
        if e.get('id') == 'current-color-scheme': st = e; break
    if st is None:
        st = ET.Element(S+'style')
        st.set('type', 'text/css'); st.set('id', 'current-color-scheme')
        doc.defs.insert(0, st)
    st.text = stylesheet()

    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with gzip.open(dst, 'wb') as f: f.write(data)
    if report is not None: report.update(stats)
    return stats

if __name__ == '__main__':
    s = convert(sys.argv[1], sys.argv[2])
    print(f"{os.path.basename(sys.argv[1])}: {s}")

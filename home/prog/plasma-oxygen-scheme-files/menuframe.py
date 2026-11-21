"""Draw Plasma popups (tooltips, dialogs) like Oxygen's QMenu frame.

Measured from an offscreen QMenu under the Oxygen style: an opaque rounded
body (radius 5) in the window colour, lighter at the top and darker at the
bottom, with a 1px light inner outline that fades out towards the bottom.
The shadow-* and hint-* elements of the converted theme are kept as they are.
"""
import gzip
from pathlib import Path
import xml.etree.ElementTree as ET

SVG = 'http://www.w3.org/2000/svg'
S = '{%s}' % SVG
ET.register_namespace('', SVG)
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')

SLICES = ('topleft', 'top', 'topright', 'left', 'center', 'right',
          'bottomleft', 'bottom', 'bottomright')
X0 = Y0 = 14.0   # where the old frame sat; any spot works, ids are rendered alone
C = 7.0          # corner slice size
E = 7.0          # edge/center prototype length (stretched by FrameSvg)
R = 5.0          # outer radius
X1 = X0 + 2 * C + E
Y1 = Y0 + 2 * C + E

# Gradient positions over the stretched middle span; corners pad the ends.
BODY_STOPS = (('#ffffff', 0.078, 0.0), ('#ffffff', 0.0, 0.37),
              ('#000000', 0.0, 0.37), ('#000000', 0.083, 0.73),
              ('#000000', 0.083, 1.0))
LINE_STOPS = (('#ffffff', 0.17, 0.0), ('#ffffff', 0.12, 0.5),
              ('#ffffff', 0.0, 1.0))


def _gradient(defs, gid, stops):
    g = ET.SubElement(defs, S + 'linearGradient', id=gid,
                      gradientUnits='userSpaceOnUse',
                      x1='0', x2='0', y1=str(Y0 + C), y2=str(Y1 - C))
    for colour, alpha, offset in stops:
        ET.SubElement(g, S + 'stop', offset=str(offset),
                      style='stop-color:%s;stop-opacity:%s' % (colour, alpha))


def _corner(cx, cy, sx, sy):
    """Body and outline paths for the corner whose outer point is (cx, cy)."""
    sweep = 1 if sx * sy > 0 else 0
    p = lambda dx, dy: '%g,%g' % (cx + sx * dx, cy + sy * dy)
    body = 'M%s L%s A%g,%g 0 0 %d %s L%s L%s Z' % (
        p(0, C), p(0, R), R, R, sweep, p(R, 0), p(C, 0), p(C, C))
    line = 'M%s L%s A4,4 0 0 %d %s L%s L%s L%s A3,3 0 0 %d %s L%s Z' % (
        p(1, C), p(1, R), sweep, p(R, 1), p(C, 1), p(C, 2), p(R, 2),
        1 - sweep, p(2, R), p(2, C))
    return body, line


def _rect(x, y, w, h):
    return 'M%g,%g h%g v%g h%g Z' % (x, y, w, h, -w)


def _shapes():
    """slice -> (body path, outline path or None)."""
    mid_x, mid_y = X0 + C, Y0 + C
    return {
        'topleft': _corner(X0, Y0, 1, 1),
        'topright': _corner(X1, Y0, -1, 1),
        'bottomleft': _corner(X0, Y1, 1, -1),
        'bottomright': _corner(X1, Y1, -1, -1),
        'top': (_rect(mid_x, Y0, E, C), _rect(mid_x, Y0 + 1, E, 1)),
        'bottom': (_rect(mid_x, Y1 - C, E, C), _rect(mid_x, Y1 - 2, E, 1)),
        'left': (_rect(X0, mid_y, C, E), _rect(X0 + 1, mid_y, 1, E)),
        'right': (_rect(X1 - C, mid_y, C, E), _rect(X1 - 2, mid_y, 1, E)),
        'center': (_rect(mid_x, mid_y, E, E), None),
    }


def build(path):
    root = ET.fromstring(gzip.decompress(Path(path).read_bytes()))
    doomed = set(SLICES) | {'mask-' + s for s in SLICES}
    for parent in list(root.iter()):
        for child in list(parent):
            if child.get('id') in doomed:
                parent.remove(child)

    defs = root.find(S + 'defs')
    if defs is None:
        defs = ET.Element(S + 'defs')
        root.insert(0, defs)
    _gradient(defs, 'menuframe-body', BODY_STOPS)
    _gradient(defs, 'menuframe-line', LINE_STOPS)

    for name, (body, line) in _shapes().items():
        g = ET.SubElement(root, S + 'g', id=name)
        ET.SubElement(g, S + 'path', d=body, attrib={
            'class': 'ColorScheme-Background',
            'style': 'fill:currentColor;fill-opacity:1;stroke:none'})
        ET.SubElement(g, S + 'path', d=body,
                      style='fill:url(#menuframe-body);stroke:none')
        if line:
            ET.SubElement(g, S + 'path', d=line,
                          style='fill:url(#menuframe-line);stroke:none')
        m = ET.SubElement(root, S + 'g', id='mask-' + name)
        ET.SubElement(m, S + 'path', d=body, style='fill:#000000;stroke:none')

    with gzip.GzipFile(path, 'wb', mtime=0) as stream:
        stream.write(ET.tostring(root, encoding='utf-8', xml_declaration=True))

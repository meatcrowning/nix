"""Give Plasma task states full Oxygen button frames with live palette roles."""
import copy
import gzip
import re
from pathlib import Path
import xml.etree.ElementTree as ET

SLICES = ('center', 'top', 'bottom', 'left', 'right',
          'topleft', 'topright', 'bottomleft', 'bottomright')


def build(button, output):
    root = ET.fromstring(gzip.decompress(Path(button).read_bytes()))
    normal = {part: next(e for e in root if e.get('id') == 'normal-' + part)
              for part in SLICES}
    # Button focus artwork is only a glow; tasks need a complete selected fill.
    for element in list(root):
        if element.get('id', '').startswith('focus-'):
            root.remove(element)

    states = {'normal': ('ColorScheme-ButtonBackground', 1.0),
              'focus': ('ColorScheme-Highlight', 1.0),
              'minimized': ('ColorScheme-Background', 0.55),
              'attention': ('ColorScheme-NeutralText', 1.0)}
    for state, (role, opacity) in states.items():
        for hovered in (False, True):
            if state == 'normal' and not hovered:
                continue
            prefix = state + ('-hover' if hovered else '')
            for part, original in normal.items():
                frame = copy.deepcopy(original)
                ids = {e.get('id'): prefix + '-' + e.get('id')
                       for e in frame.iter() if e.get('id')}
                ids[original.get('id')] = prefix + '-' + part
                for e in frame.iter():
                    for attr, value in list(e.attrib.items()):
                        if attr == 'id':
                            e.set(attr, ids[value])
                        else:
                            e.set(attr, re.sub(r'url\(#([^)]*)\)',
                                              lambda m: 'url(#' + ids.get(m[1], m[1]) + ')', value))
                    if e.get('class') == 'ColorScheme-ButtonBackground':
                        e.set('class', role)
                # Tint the same body beneath the original Oxygen relief on
                # hover, rather than replacing all states with one hover frame.
                if hovered:
                    for parent in list(frame.iter()):
                        for i, child in reversed(list(enumerate(list(parent)))):
                            if child.get('class') == role:
                                tint = copy.deepcopy(child)
                                tint.attrib.pop('id', None)
                                tint.set('class', 'ColorScheme-ButtonHover')
                                tint.set('opacity', '0.15')
                                parent.insert(i + 1, tint)
                frame.set('opacity', str(opacity))
                root.append(frame)

    with gzip.GzipFile(output, 'wb', mtime=0) as stream:
        stream.write(ET.tostring(root, encoding='utf-8', xml_declaration=True))

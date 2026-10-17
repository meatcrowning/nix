# -*- coding: utf-8 -*-
"""MOSS layout document, geometry and prompt compiler; Python 2/3, no GUI.

Editor boxes use normalized xywh. Only compile() emits centered pixel yxyx.
Editor-only state never enters conditioning. This module is shared by both faces.
"""
from __future__ import division, unicode_literals
import copy
import json
import math
import textwrap
import uuid
from xml.sax.saxutils import escape

KINDS = ['object', 'character', 'text']
CANVASES = ['single', 'multi_panel', 'collage']
POLICIES = ['stretch', 'fit', 'keep sizes']
TYPE_FIELDS = [('family', 'Lettering', ['', 'sans serif', 'serif', 'monospace', 'handwritten']),
               ('weight', 'Weight', ['', 'light', 'regular', 'bold', 'heavy']),
               ('align', 'Alignment', ['', 'left', 'center', 'right']),
               ('color', 'Text colour', None), ('outline', 'Outline', None),
               ('shadow', 'Shadow', None), ('surface', 'Text on surface', None)]


def fresh(width=1024, height=1024, caption=''):
    return dict(version=1, width=width, height=height, enabled=False,
                summary=dict(caption=caption, meta=[], palette=[], canvas='single'), items=[],
                resize_policy='fit', reference='', opacity=.3, grid=True, snap=True,
                grid_step=.05, margin=.05, guides='thirds', custom_x=[], custom_y=[])


def strings(value):
    return [s.strip() for s in value.split(',') if s.strip()]


def valid(doc):
    d = copy.deepcopy(doc)
    if not isinstance(d, dict) or d.get('version') != 1:
        raise ValueError('Unsupported layout document')
    for key in ('width', 'height'):
        n = d.get(key, 0)
        if not isinstance(n, (int, float)) or not 16 <= n <= 16384 or n % 16:
            raise ValueError('Canvas dimensions must be multiples of 16 (16–16384)')
        d[key] = int(n)
    if not .05 <= d['width'] * d['height'] / 1000000 <= 16:
        raise ValueError('Canvas must be between 0.05 and 16 megapixels')
    if not isinstance(d.get('summary'), dict):
        raise ValueError('Invalid scene description')
    a, b = d['width'], d['height']
    while b:
        a, b = b, a % b
    if max(d['width'] // a, d['height'] // a) > 999:
        raise ValueError('Canvas aspect numbers must reduce to 999 or less')
    if d.get('resize_policy') not in POLICIES or d.get('summary', {}).get('canvas') not in CANVASES:
        raise ValueError('Invalid canvas options')
    if not isinstance(d.get('items'), list) or len(d['items']) > 256:
        raise ValueError('A layout supports at most 256 regions')
    seen = set()
    for item in d['items']:
        if not isinstance(item, dict) or not isinstance(item.get('typography', {}), dict):
            raise ValueError('Invalid region')
        if item.get('label') not in KINDS or not item.get('id') or item['id'] in seen:
            raise ValueError('Invalid region type or identifier')
        seen.add(item['id'])
        box = item.get('box', [])
        if len(box) != 4 or any(not isinstance(x, (int, float)) or math.isnan(x) or math.isinf(x) for x in box):
            raise ValueError('Invalid region coordinates')
        x, y, w, h = box
        if min(x, y) < -1e-8 or min(w, h) <= 0 or x + w > 1.00000001 or y + h > 1.00000001:
            raise ValueError('Regions must fit inside the canvas')
        for key in ('caption', 'text'):
            if not isinstance(item.get(key, ''), type(u'')):
                # Python 2 GTK may also provide UTF-8 bytes.
                try:
                    item[key] = item[key].decode('utf-8')
                except (KeyError, AttributeError, UnicodeError):
                    raise ValueError('Invalid region text')
    return d


def resize(doc, width, height, policy=None):
    d = copy.deepcopy(doc)
    width, height = int(width), int(height)
    ow, oh = d['width'], d['height']
    policy = policy or d['resize_policy']
    # Same aspect means a pure resolution change: preserve composition.
    if abs(width / height - ow / oh) > 1e-6 and policy != 'stretch':
        scale = min(width / ow, height / oh) if policy == 'fit' else 1
        for item in d['items']:
            x, y, w, h = item['box']
            fit = min(1, width / (w * ow * scale), height / (h * oh * scale))
            nw, nh = w * ow * scale * fit / width, h * oh * scale * fit / height
            cx = .5 + (x + w / 2 - .5) * ow * scale / width
            cy = .5 + (y + h / 2 - .5) * oh * scale / height
            item['box'] = [max(0, min(1 - nw, cx - nw / 2)), max(0, min(1 - nh, cy - nh / 2)), nw, nh]
    d.update(width=width, height=height, resize_policy=policy)
    return valid(d)


def description(item):
    parts = [item.get('caption', '').strip()]
    style = item.get('typography', {})
    for key, title, _ in TYPE_FIELDS:
        value = style.get(key, '').strip()
        if value:
            parts.append('%s: %s.' % (title, value))
    return ' '.join(p for p in parts if p)


def compile(doc, width=None, height=None, caption=None):
    d = valid(doc)
    d = resize(d, width or d['width'], height or d['height'])
    width, height = d['width'], d['height']
    summary = copy.deepcopy(d['summary'])
    if caption is not None:
        summary['caption'] = caption
    if not summary.get('caption', '').strip():
        raise ValueError('Describe the overall scene before generating a layout')
    summary = {k: summary[k] for k in ('caption', 'canvas', 'meta', 'palette') if summary.get(k)}
    items = []
    for item in d['items']:
        if not item.get('enabled', True):
            continue
        if not description(item):
            raise ValueError('Describe every included region')
        x, y, w, h = item['box']
        out = dict(label=item['label'], caption=description(item),
                   bbox=[int(math.floor(y * height)) - height // 2,
                         int(math.floor(x * width)) - width // 2,
                         int(math.ceil(round((y + h) * height, 8))) - height // 2,
                         int(math.ceil(round((x + w) * width, 8))) - width // 2])
        if item['label'] == 'text':
            if not item.get('text', '').strip():
                raise ValueError('Enter exact wording for each text region')
            out['text'] = item['text']
        for key in ('tags', 'palette'):
            if item.get(key):
                out[key] = item[key]
        items.append(out)
    if not items:
        raise ValueError('Include at least one region in the layout')
    return json.dumps(dict(summary=summary, items=items, bbox_coord_space='abs_centralized',
                           bbox_format='yxyx'), ensure_ascii=False, separators=(',', ':'))


class Editor(object):
    def __init__(self, doc):
        self.doc = valid(doc)
        self.selected = []
        self.undo_stack, self.redo_stack = [], []
        self.drag = None
        self.tool = 'select'
        self.marquee = None
        self.units = 'percent'

    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.doc))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack = []

    def undo(self, redo=False):
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if source:
            target.append(self.doc)
            self.doc = source.pop()
            self.selected = [i for i in self.selected if any(r['id'] == i for r in self.doc['items'])]

    def chosen(self):
        return [i for i in self.doc['items'] if i['id'] in self.selected]

    def select(self, identity, toggle=False, include_locked=True):
        row = next((r for r in self.doc['items'] if r['id'] == identity), None)
        ids = [r['id'] for r in self.doc['items'] if row and (include_locked or not r.get('locked')) and (r['id'] == identity or
               (row.get('group') and r.get('group') == row['group']))]
        if toggle:
            self.selected = [i for i in self.selected if i not in ids] if identity in self.selected else list(set(self.selected + ids))
        else:
            self.selected = ids

    def add(self, kind='object', box=None):
        self.checkpoint()
        row = dict(id=uuid.uuid4().hex, label=kind, caption='', text='', box=box or [.25, .25, .5, .5],
                   enabled=True, locked=False, tags=[], palette=[], typography={})
        self.doc['items'].append(row)
        self.selected = [row['id']]
        return row

    def delete(self):
        self.checkpoint()
        self.doc['items'] = [i for i in self.doc['items'] if i['id'] not in self.selected]
        self.selected = []

    def clear(self):
        if not self.doc['items']:
            return
        self.checkpoint()
        self.doc['items'] = []
        self.doc['enabled'] = False
        self.selected = []
        self.drag = None
        self.tool = 'select'

    def copy(self):
        return json.dumps(dict(painter_layout_regions=1, items=self.chosen()), ensure_ascii=False)

    def paste(self, raw):
        payload = json.loads(raw)
        if payload.get('painter_layout_regions') != 1:
            raise ValueError('Clipboard does not contain Painter regions')
        rows = copy.deepcopy(payload['items'])
        groups = {}
        for row in rows:
            row['id'] = uuid.uuid4().hex
            if row.get('group'):
                row['group'] = groups.setdefault(row['group'], uuid.uuid4().hex)
        candidate = copy.deepcopy(self.doc)
        candidate['items'].extend(rows)
        valid(candidate)
        self.checkpoint()
        self.doc = candidate
        self.selected = [r['id'] for r in rows]

    def duplicate(self):
        self.paste(self.copy())
        self.move(.02, .02)

    def group(self, remove=False):
        self.checkpoint()
        group = '' if remove else uuid.uuid4().hex
        for row in self.chosen():
            row['group'] = group

    def move(self, dx, dy):
        rows = [r for r in self.chosen() if not r.get('locked')]
        if not rows:
            return
        dx = max(-min(r['box'][0] for r in rows), min(dx, 1 - max(r['box'][0] + r['box'][2] for r in rows)))
        dy = max(-min(r['box'][1] for r in rows), min(dy, 1 - max(r['box'][1] + r['box'][3] for r in rows)))
        for r in rows:
            r['box'][0] += dx
            r['box'][1] += dy

    def align(self, action):
        rows = [r for r in self.chosen() if not r.get('locked')]
        if not rows:
            return
        self.checkpoint()
        axis = 1 if action in ('top', 'middle', 'bottom', 'distribute vertical') else 0
        low = min(r['box'][axis] for r in rows) if len(rows) > 1 else 0
        high = max(r['box'][axis] + r['box'][axis + 2] for r in rows) if len(rows) > 1 else 1
        if action.startswith('distribute'):
            if len(rows) < 3:
                return
            rows.sort(key=lambda r: r['box'][axis])
            gap = (high - low - sum(r['box'][axis + 2] for r in rows)) / (len(rows) - 1)
            pos = low
            for r in rows:
                r['box'][axis] = pos
                pos += r['box'][axis + 2] + gap
        else:
            for r in rows:
                size = r['box'][axis + 2]
                r['box'][axis] = low if action in ('left', 'top') else high - size if action in ('right', 'bottom') else (low + high - size) / 2

    def guides(self, axis):
        d = self.doc
        points = [0, .5, 1, d['margin'], 1 - d['margin']]
        if d['guides'] == 'thirds':
            points += [1 / 3, 2 / 3]
        points += d.get('custom_x' if axis == 0 else 'custom_y', [])
        if d['grid']:
            step = max(.01, d['grid_step'])
            points += [i * step for i in range(1, int(1 / step))]
        for r in d['items']:
            if r['id'] not in self.selected and r.get('enabled', True):
                a, size = r['box'][axis], r['box'][axis + 2]
                points += [a, a + size / 2, a + size]
        return points

    def snap(self, value, axis, threshold):
        if not self.doc['snap']:
            return value
        target = min(self.guides(axis), key=lambda x: abs(x - value))
        return target if abs(target - value) < threshold else value

    def press(self, x, y, toggle=False, threshold=.01):
        self.marquee = None
        if self.tool != 'select':
            self.add(self.tool, [x, y, .001, .001])
            self.drag = ('draw', x, y, copy.deepcopy(self.doc['items']))
            return
        # Handles take priority over overlapping regions.
        for row in reversed(self.chosen()):
            if row.get('locked'):
                continue
            bx, by, bw, bh = row['box']
            for hx, hy in [(0, 0), (.5, 0), (1, 0), (0, .5), (1, .5), (0, 1), (.5, 1), (1, 1)]:
                if abs(x - bx - hx * bw) < threshold and abs(y - by - hy * bh) < threshold:
                    self.checkpoint()
                    self.drag = ('resize', x, y, copy.deepcopy(self.doc['items']), row['id'], hx, hy)
                    return
        hit = next((r for r in reversed(self.doc['items']) if not r.get('locked') and r['box'][0] <= x <= r['box'][0] + r['box'][2]
                    and r['box'][1] <= y <= r['box'][1] + r['box'][3]), None)
        if hit:
            if toggle or hit['id'] not in self.selected or (hit.get('group') and any(r.get('group') == hit['group'] and r['id'] not in self.selected for r in self.doc['items'])):
                self.select(hit['id'], toggle, include_locked=False)
            self.checkpoint()
            self.drag = ('move', x, y, copy.deepcopy(self.doc['items']))
        else:
            if not toggle:
                self.selected = []
            self.drag = ('marquee', x, y, copy.deepcopy(self.doc['items']), list(self.selected))

    def motion(self, x, y, threshold=.01):
        if not self.drag:
            return
        mode, sx, sy, original = self.drag[:4]
        self.doc['items'] = copy.deepcopy(original)
        if mode != 'draw':
            x, y = max(0, min(1, x)), max(0, min(1, y))
        if mode == 'move':
            rows = [r for r in self.chosen() if not r.get('locked')]
            if not rows:
                return
            dx, dy = x - sx, y - sy
            for axis, delta in [(0, dx), (1, dy)]:
                lo = min(r['box'][axis] for r in rows)
                hi = max(r['box'][axis] + r['box'][axis + 2] for r in rows)
                offsets = [self.snap(a + delta, axis, threshold) - a for a in (lo, (lo + hi) / 2, hi)]
                snapped = min(offsets, key=lambda v: abs(v - delta) if v != delta else 100)
                if axis == 0:
                    dx = snapped
                else:
                    dy = snapped
            self.move(dx, dy)
        elif mode in ('draw', 'resize'):
            x, y = self.snap(x, 0, threshold), self.snap(y, 1, threshold)
            if mode == 'draw':
                row = self.chosen()[0]
                left, top, right, bottom = min(sx, x), min(sy, y), max(sx, x), max(sy, y)
            else:
                row = next(r for r in self.doc['items'] if r['id'] == self.drag[4])
                left, top, w, h = row['box']
                right, bottom = left + w, top + h
                hx, hy = self.drag[5:]
                if hx == 0: left = min(x, right - .001)
                if hx == 1: right = max(x, left + .001)
                if hy == 0: top = min(y, bottom - .001)
                if hy == 1: bottom = max(y, top + .001)
            if mode != 'draw':
                left, top = min(.999, left), min(.999, top)
            row['box'] = [left, top, max(.001, right - left), max(.001, bottom - top)]
        else:
            self.marquee = [min(sx, x), min(sy, y), abs(x - sx), abs(y - sy)]
            self.selected = list(self.drag[4])
            for r in self.doc['items']:
                bx, by, bw, bh = r['box']
                if not r.get('locked') and min(sx, x) <= bx and bx + bw <= max(sx, x) and min(sy, y) <= by and by + bh <= max(sy, y):
                    if r['id'] not in self.selected:
                        self.selected.append(r['id'])

    def release(self):
        self.marquee = None
        if self.drag and self.drag[0] == 'draw':
            row = self.chosen()[0]
            x, y, w, h = row['box']
            left, top = max(0, x), max(0, y)
            right, bottom = min(1, x + w), min(1, y + h)
            if right > left and bottom > top:
                row['box'] = [left, top, right - left, bottom - top]
            else:
                # A gesture wholly outside the canvas must not create an edge sliver.
                self.doc = self.undo_stack.pop()
                self.selected = []
        self.drag = None
        self.tool = 'select'


def text_warning(item, width, height):
    if item['label'] != 'text' or not item.get('text'):
        return ''
    box = item['box']
    lines = item['text'].split('\n')
    estimate = min(box[2] * width / max(1, max(len(s) for s in lines)) * 1.6,
                   box[3] * height / max(1, len(lines)) / 1.25)
    return 'Text may be too small or crowded at this output size.' if estimate < 16 else ''


def view_rect(d, vw, vh, zoom=1, pan=(0, 0)):
    scale = min((vw - 24) / d['width'], (vh - 24) / d['height']) * zoom
    w, h = max(1, d['width'] * scale), max(1, d['height'] * scale)
    return (vw - w) / 2 + pan[0], (vh - h) / 2 + pan[1], w, h


def preview_lines(text, width, font_size):
    """Conservative character widths for the toolkit-independent SVG sketch."""
    columns = max(1, int(width / (font_size * .65)))
    return [line for paragraph in text.split('\n')
            for line in (textwrap.wrap(paragraph, columns) or [''])]


def svg(editor, vw, vh, reference='', zoom=1, pan=(0, 0), font=None):
    """Portable rough composition preview; not a prediction of generated pixels."""
    d = editor.doc
    font = font or dict(family='sans-serif', size=11, height=13, weight=400, style='normal')
    fs, leading = font['size'], font['height']
    font_attrs = 'font-family="%s" font-size="%f" font-weight="%s" font-style="%s"' % (
        escape(font['family'], {'"': '&quot;'}), fs, font['weight'], font['style'])
    ox, oy, w, h = view_rect(d, vw, vh, zoom, pan)
    s = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="%d" height="%d">' % (vw, vh),
         '<g transform="translate(%f,%f)"><rect width="%f" height="%f" fill="none" stroke="#bbbbbb"/>' % (ox, oy, w, h)]
    if reference:
        s.append('<image width="%f" height="%f" opacity="%f" preserveAspectRatio="xMidYMid meet" xlink:href="data:image/png;base64,%s"/>' % (w, h, d['opacity'], reference))
    if d['grid']:
        for axis, dim in [(0, w), (1, h)]:
            step = max(.01, d['grid_step'])
            for n in range(1, int(1 / step)):
                v = n * step * dim
                s.append('<path d="M %f %f L %f %f" stroke="#666666"/>' % ((v, 0, v, h) if axis == 0 else (0, v, w, v)))
    for axis, custom in [(0, d.get('custom_x', [])), (1, d.get('custom_y', []))]:
        pts = list(custom)
        if d['guides'] == 'thirds': pts += [1 / 3, 2 / 3]
        elif d['guides'] == 'center': pts += [.5]
        for v in pts:
            s.append('<path d="M %f %f L %f %f" stroke="#e8b85e" stroke-dasharray="4 4"/>' % ((v * w, 0, v * w, h) if axis == 0 else (0, v * h, w, v * h)))
    margin = d['margin']
    s.append('<rect x="%f" y="%f" width="%f" height="%f" fill="none" stroke="#999" stroke-dasharray="3 3"/>' % (margin * w, margin * h, (1 - 2 * margin) * w, (1 - 2 * margin) * h))
    s.append('<defs><clipPath id="canvas"><rect width="%f" height="%f"/></clipPath></defs><g clip-path="url(#canvas)">' % (w, h))
    for n, item in enumerate(d['items']):
        x, y, bw, bh = item['box']
        x, y, bw, bh = x * w, y * h, bw * w, bh * h
        selected = item['id'] in editor.selected
        colour = '#ffb454' if selected else '#79bfff'
        s.append('<g><rect x="%f" y="%f" width="%f" height="%f" fill="none" stroke="%s" stroke-width="%s" stroke-opacity="%s"/>' % (x, y, bw, bh, colour, 2 if selected else 1, '1' if item.get('enabled', True) else '.6'))
        title = '%d %s' % (n + 1, item['label'])
        label_offset = 14 if item.get('locked') else 3
        if item.get('locked'):
            s.append('<g transform="translate(%f,%f)" fill="none" stroke="%s" stroke-width="1.3"><path d="M2 5V3a3 3 0 0 1 6 0v2"/><rect x="1" y="5" width="8" height="6" fill="black"/></g>' % (x + 3, y + 3, colour))
        caption = ' '.join(item.get('caption', '').split())
        if caption:
            title += ' — ' + caption
        labels = preview_lines(title, bw - label_offset - 3, fs)
        s.append('<defs><clipPath id="label%d"><rect x="%f" y="%f" width="%f" height="%f"/></clipPath></defs>' % (n, x, y, bw, bh))
        for j, line in enumerate(labels):
            s.append('<text clip-path="url(#label%d)" x="%f" y="%f" fill="white" %s>%s</text>' % (n, x + label_offset, y + fs + 2 + leading * j, font_attrs, escape(line)))
        if item['label'] == 'text':
            style = item.get('typography', {})
            label_height = leading * len(labels) + 5
            lines = preview_lines(item.get('text', ''), bw - 6, fs)
            align = style.get('align', 'left')
            tx = x + bw / 2 if align == 'center' else x + bw - 3 if align == 'right' else x + 3
            for j, line in enumerate(lines):
                s.append('<text clip-path="url(#label%d)" x="%f" y="%f" fill="white" %s text-anchor="%s">%s</text>' % (n, tx, y + label_height + fs + leading * j, font_attrs, {'center': 'middle', 'right': 'end'}.get(align, 'start'), escape(line)))
        s.append('</g>')
        if selected and not item.get('locked'):
            for hx, hy in [(0, 0), (.5, 0), (1, 0), (0, .5), (1, .5), (0, 1), (.5, 1), (1, 1)]:
                s.append('<rect x="%f" y="%f" width="6" height="6" fill="white" stroke="%s"/>' % (x + hx * bw - 3, y + hy * bh - 3, colour))
    if editor.marquee:
        x, y, bw, bh = editor.marquee
        s.append('<rect x="%f" y="%f" width="%f" height="%f" fill="none" stroke="white" stroke-dasharray="4 3"/>' % (x * w, y * h, bw * w, bh * h))
    s.append('</g></g></svg>')
    return ''.join(s).encode('utf-8'), (ox, oy, w, h)

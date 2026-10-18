# -*- coding: utf-8 -*-
"""Toolkit-independent layout editor actions and native form construction."""
from __future__ import division, unicode_literals
import copy
import math
import moss_layout as M


class LayoutUI(object):
    def __init__(self, toolkit, doc, accepted):
        self.ui, self.model, self.accepted = toolkit, M.Editor(doc), accepted
        self.syncing = False
        self.fields = {}
        self.reference = ''
        self.reference_path = None
        self.rect = (0, 0, 1, 1)
        self.viewport = (100, 100)
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self.panning = None
        u = self.ui
        root = u.root
        self.last_doc = copy.deepcopy(self.model.doc)
        self.buttons = {}
        tools = u.toolbar(root)
        self.add_button = u.button(tools, 'Add', self.arm_add)
        self.new_kind = 'object'
        self.tool = u.field(tools, '', 'combo', ['object', 'character', 'text'], self.type_changed)
        u.set(self.tool, 'object')
        self.buttons['Clear all'] = u.button(tools, 'Clear all', self.clear)
        for title, fn in [('Undo', lambda: self.model.undo()), ('Redo', lambda: self.model.undo(True))]:
            self.buttons[title] = u.button(tools, title, lambda fn=fn: self.command(fn))
        self.buttons['Hide'] = u.button(tools, 'Hide', lambda: self.command(self.toggle_hidden))
        u.spacer(tools)
        coordinates = u.compact_fields(tools)
        self.fields['box.position'] = u.field(coordinates, 'Position (X, Y)', 'pair', None, lambda: self.geometry_pair('position'))
        self.fields['box.size'] = u.field(coordinates, 'Size (W, H)', 'pair', None, lambda: self.geometry_pair('size'))
        self.units = u.field(coordinates, '', 'combo', ['percent', 'pixels'], self.units_changed)
        u.spacer(tools)
        for title, fn in [('Lock', self.toggle_lock), ('Delete', lambda: self.model.delete()), ('Duplicate', lambda: self.model.duplicate())]:
            self.buttons[title] = u.button(tools, title, lambda fn=fn: self.command(fn))
        self.canvas = u.canvas(root, self)
        self.side = u.column(root)
        tabs = u.tabs(self.side)
        region = u.tab(tabs, 'Region')
        self.list = u.region_list(region, self.selection_changed)
        scene = u.tab(tabs, 'Scene')
        canvas = u.tab(tabs, 'Canvas')
        menu = u.menu(canvas, 'Edit')
        for title, command in [('Group', lambda: self.model.group()), ('Ungroup', lambda: self.model.group(True)),
                               ('Copy', self.copy), ('Paste', self.paste)]:
            self.buttons[title] = u.menu_item(menu, title, lambda fn=command: self.command(fn))
        self.align = u.field(canvas, 'Align / distribute selected regions', 'combo', ['left', 'center', 'right', 'top', 'middle', 'bottom', 'distribute horizontal', 'distribute vertical'], lambda: None)
        u.set(self.align, 'left')
        u.button(canvas, 'Align / distribute', lambda: self.command(lambda: self.model.align(u.get(self.align))))
        self.add(scene, 'enabled', 'Use layout for generation', 'check')
        self.add(scene, 'summary.canvas', 'Composition', 'combo', M.CANVASES)
        self.add(scene, 'summary.meta', 'Medium / genre tags (comma-separated)')
        self.add(scene, 'summary.palette', 'Scene palette', 'palette')
        u.label(scene, 'Layout is experimental placement guidance. The preview is a composition sketch, not a generated result.')
        self.add(region, 'item.caption', 'Prompt', 'text')
        self.add(region, 'item.text', 'Exact wording', 'text')
        self.add(region, 'item.tags', 'Tags (comma-separated)')
        self.add(region, 'item.palette', 'Palette', 'palette')
        for key, title, choices in M.TYPE_FIELDS:
            self.add(region, 'type.' + key, title, 'combo' if choices else 'palette' if key == 'color' else 'entry', choices)
        self.warning = u.label(region, '')
        self.add(canvas, 'width', 'Output width', 'number', (16, 16384, 16), change=False)
        self.add(canvas, 'height', 'Output height', 'number', (16, 16384, 16), change=False)
        self.add(canvas, 'resize_policy', 'When aspect ratio changes', 'combo', M.POLICIES)
        u.label(canvas, 'Stretch follows the new proportions. Fit preserves the composition. Keep sizes preserves pixel sizes; oversized regions shrink to fit.')
        u.button(canvas, 'Apply canvas size', self.resize)
        self.add(canvas, 'grid', 'Show grid', 'check')
        self.add(canvas, 'snap', 'Snap to edges, centres, guides and grid', 'check')
        self.add(canvas, 'grid_step', 'Grid spacing (%)', 'number', (1, 50, 1))
        self.add(canvas, 'margin', 'Safe margin (%)', 'number', (0, 45, 1))
        self.add(canvas, 'guides', 'Composition guides', 'combo', ['none', 'center', 'thirds'])
        self.add(canvas, 'custom_x', 'Vertical guides (%; comma-separated)')
        self.add(canvas, 'custom_y', 'Horizontal guides (%; comma-separated)')
        u.button(canvas, 'Choose reference underlay…', self.choose_reference)
        u.button(canvas, 'Remove reference', lambda: self.command(lambda: self.set_reference('')))
        self.reference_label = u.label(canvas, '')
        self.add(canvas, 'opacity', 'Reference opacity (%)', 'number', (0, 100, 5))
        u.label(canvas, 'Reference is a tracing aid only; it is not sent as image conditioning.')
        self.status = u.label(root, '')
        self.refresh()

    def toggle_hidden(self):
        rows = self.model.chosen()
        if rows:
            enabled = all(not row.get('enabled', True) for row in rows)
            self.model.checkpoint()
            for row in rows:
                row['enabled'] = enabled

    def toggle_lock(self):
        rows = self.model.chosen()
        if rows:
            locked = not all(row.get('locked') for row in rows)
            self.model.checkpoint()
            for row in rows:
                row['locked'] = locked
            if locked:
                self.model.selected = []

    def type_changed(self):
        if self.syncing:
            return
        kind = self.ui.get(self.tool)
        if not kind:
            return
        self.new_kind = kind
        if self.model.tool != 'select':
            self.model.tool = kind
        if self.model.chosen():
            def change():
                self.model.checkpoint()
                for row in self.model.chosen():
                    row['label'] = kind
            self.command(change)

    def arm_add(self):
        self.new_kind = self.ui.get(self.tool) or self.new_kind
        self.model.selected = []
        self.model.tool = self.new_kind
        self.refresh()
        self.ui.drawing_cursor(self.canvas, True)

    def clear(self):
        self.command(self.model.clear)
        self.ui.drawing_cursor(self.canvas, False)

    def publish(self):
        if not self.model.drag and self.model.doc != self.last_doc:
            self.last_doc = copy.deepcopy(self.model.doc)
            self.accepted(copy.deepcopy(self.model.doc))

    def load(self, doc):
        if self.model.drag or doc == self.model.doc:
            return
        selected = list(self.model.selected)
        self.model = M.Editor(doc)
        self.model.selected = [row['id'] for row in self.model.doc['items'] if row['id'] in selected]
        self.last_doc = copy.deepcopy(doc)
        self.refresh()

    def add(self, parent, key, title, kind='entry', options=None, change=True):
        self.fields[key] = self.ui.field(parent, title, kind, options, lambda: self.changed(key) if change else None)

    def row(self):
        rows = self.model.chosen()
        return rows[0] if len(rows) == 1 else None

    def get_value(self, key):
        if key.startswith('item.'):
            return (self.row() or {}).get(key[5:], '')
        if key.startswith('type.'):
            return (self.row() or {}).get('typography', {}).get(key[5:], '')
        if key.startswith('summary.'):
            return self.model.doc['summary'].get(key[8:], '')
        return self.model.doc.get(key, '')

    def changed(self, key):
        if self.syncing:
            return
        try:
            value = self.ui.get(self.fields[key])
            if key.endswith(('.palette', '.tags', '.meta')):
                value = M.strings(value)
            elif key in ('grid_step', 'margin', 'opacity'):
                value /= 100
            elif key in ('custom_x', 'custom_y'):
                value = [float(v) / 100 for v in M.strings(value)]
                if any(not 0 <= v <= 1 for v in value):
                    raise ValueError('Guides must be between 0 and 100 percent')
            self.model.checkpoint()
            if key.startswith(('item.', 'type.')):
                row = self.row()
                if not row:
                    return
                if key.startswith('type.'):
                    row.setdefault('typography', {})[key[5:]] = value
                else:
                    row[key[5:]] = value
            elif key.startswith('summary.'):
                self.model.doc['summary'][key[8:]] = value
            else:
                self.model.doc[key] = value
            self.paint()
            self.refresh_list()
            self.region_visibility()
            self.ui.set_label(self.status, '')
            self.publish()
        except (ValueError, TypeError) as exc:
            self.ui.set_label(self.status, str(exc))

    def geometry_pair(self, part):
        row = self.row()
        if self.syncing or not row or row.get('locked'):
            return
        try:
            values = [float(v.strip()) for v in self.ui.get(self.fields['box.' + part]).split(',')]
            if len(values) != 2 or any((math.isnan(v) or math.isinf(v)) for v in values):
                raise ValueError('Enter two numbers separated by a comma.')
            offset = 0 if part == 'position' else 2
            box = list(row['box'])
            for axis, value in enumerate(values):
                scale = 100 if self.model.units == 'percent' else self.model.doc['width' if axis == 0 else 'height']
                box[offset + axis] = max(0 if offset == 0 else .001, min(value / scale, 1 - box[axis + 2 if offset == 0 else axis]))
            self.model.checkpoint()
            row['box'] = box
            self.refresh()
        except ValueError as exc:
            self.ui.set_label(self.status, str(exc))

    def units_changed(self):
        if not self.syncing:
            self.model.units = self.ui.get(self.units)
            self.refresh()

    def selection_changed(self, ids):
        if self.syncing:
            return
        self.model.selected = ids
        self.refresh()

    def refresh_list(self):
        previous = self.syncing
        self.syncing = True
        rows = [(r['id'], '%d. %s%s%s — %s' % (n + 1, r['label'], ' [off]' if not r.get('enabled', True) else '',
                 (' [locked]' if r.get('locked') else '') + (' [grouped]' if r.get('group') else ''), (r.get('text') or r.get('caption') or 'Describe this region').replace('\n', ' ')[:70])) for n, r in enumerate(self.model.doc['items'])]
        self.ui.set_list(self.list, rows, self.model.selected)
        self.syncing = previous

    def region_visibility(self):
        row = self.row()
        for key, field in self.fields.items():
            region = key.startswith(('item.', 'type.', 'box.'))
            if region:
                self.ui.sensitive(field, row is not None and not (key.startswith('box.') and row.get('locked')))
            if key.startswith('type.') or key == 'item.text':
                self.ui.visible(field, bool(row and row['label'] == 'text'))
        self.ui.set_label(self.warning, M.text_warning(row, self.model.doc['width'], self.model.doc['height']) if row else 'Select one region to edit its fields.')

    def refresh(self):
        self.syncing = True
        chosen = self.model.chosen()
        kinds = set(row['label'] for row in chosen)
        self.ui.set(self.tool, next(iter(kinds)) if len(kinds) == 1 else self.new_kind if not chosen else '')
        for key, field in self.fields.items():
            if key.startswith('box.'):
                offset = 0 if key == 'box.position' else 2
                values = [(self.row()['box'][offset + axis] if self.row() else 0) *
                          (100 if self.model.units == 'percent' else self.model.doc['width' if axis == 0 else 'height']) for axis in (0, 1)]
                value = ', '.join('%g' % v for v in values)
            else:
                value = self.get_value(key)
                if key in ('grid_step', 'margin', 'opacity'):
                    value *= 100
                elif key in ('custom_x', 'custom_y'):
                    value = ', '.join('%g' % (v * 100) for v in value)
                elif isinstance(value, list):
                    value = ', '.join(value)
            self.ui.set(field, value)
        self.ui.set(self.units, self.model.units)
        self.refresh_list()
        self.region_visibility()
        self.syncing = False
        self.paint()
        self.publish()

    def paint(self):
        chosen = self.model.chosen()
        self.ui.button_checked(self.buttons['Hide'], bool(chosen) and all(not row.get('enabled', True) for row in chosen))
        self.ui.button_checked(self.buttons['Lock'], bool(chosen) and all(row.get('locked') for row in chosen))
        for title, button in self.buttons.items():
            enabled = bool(self.model.undo_stack) if title == 'Undo' else bool(self.model.redo_stack) if title == 'Redo' else True if title == 'Paste' else bool(self.model.selected)
            if title == 'Clear all':
                enabled = bool(self.model.doc['items'])
            elif title == 'Group':
                enabled = len(self.model.selected) > 1
            elif title == 'Ungroup':
                enabled = any(r.get('group') for r in self.model.chosen())
            self.ui.enable_widget(button, enabled)
        path = self.model.doc.get('reference', '')
        if path != self.reference_path:
            self.reference_path = path
            try:
                self.reference = self.ui.reference(path) if path else ''
            except Exception as exc:
                self.reference = ''
                self.ui.set_label(self.status, 'Reference unavailable: ' + str(exc))
        self.ui.set_label(self.reference_label, path or 'No reference underlay')
        self.ui.redraw(self.canvas)

    def render(self, w, h, font=None):
        self.viewport = (max(100, w), max(100, h))
        data, self.rect = M.svg(self.model, self.viewport[0], self.viewport[1], self.reference, self.zoom, self.pan, font)
        return data

    def zoom_at(self, x, y, steps):
        if self.model.drag or self.panning:
            return
        ox, oy, w, h = self.rect
        zoom = max(.25, min(16, self.zoom * 1.2 ** max(-10, min(10, steps))))
        factor = zoom / self.zoom
        nw, nh = w * factor, h * factor
        self.pan = [x - (x - ox) * factor - (self.viewport[0] - nw) / 2,
                    y - (y - oy) * factor - (self.viewport[1] - nh) / 2]
        self.zoom = zoom
        self.rect = M.view_rect(self.model.doc, self.viewport[0], self.viewport[1], self.zoom, self.pan)
        self.paint()

    def pan_pointer(self, action, x, y):
        if action == 'press':
            self.panning = (x, y, list(self.pan))
        if self.panning:
            sx, sy, origin = self.panning
            self.pan = [origin[0] + x - sx, origin[1] + y - sy]
            self.rect = M.view_rect(self.model.doc, self.viewport[0], self.viewport[1], self.zoom, self.pan)
            self.paint()
        if action == 'release':
            self.panning = None

    def pointer(self, action, x, y, shift=False):
        ox, oy, w, h = self.rect
        x, y = (x - ox) / w, (y - oy) / h
        if action == 'press':
            drawing = self.model.tool != 'select'
            self.model.press(x, y, shift, 7 / min(w, h))
            if drawing:
                self.model.doc['enabled'] = True
        elif action == 'move':
            if not self.model.drag:
                return
            self.model.motion(x, y, 7 / min(w, h))
        else:
            self.model.motion(x, y, 7 / min(w, h))
            self.model.release()
            self.ui.drawing_cursor(self.canvas, False)
        if action == 'move':
            self.paint()
        else:
            self.refresh()

    def key(self, name, control=False, shift=False):
        if not name:
            return False
        if len(name) == 1:
            name = name.lower()
        actions = {'Delete': self.model.delete, 'BackSpace': self.model.delete}
        if control:
            actions = {'z': lambda: self.model.undo(shift), 'y': lambda: self.model.undo(True),
                       'c': self.copy, 'v': self.paste, 'd': self.model.duplicate,
                       'g': lambda: self.model.group(shift),
                       'a': lambda: setattr(self.model, 'selected', [r['id'] for r in self.model.doc['items'] if not r.get('locked')])}
        if name in actions:
            self.command(actions[name])
            return True
        if name in ('Left', 'Right', 'Up', 'Down'):
            def nudge():
                self.model.checkpoint()
                step = 10 if shift else 1
                self.model.move((step if name == 'Right' else -step if name == 'Left' else 0) / self.model.doc['width'],
                                (step if name == 'Down' else -step if name == 'Up' else 0) / self.model.doc['height'])
            self.command(nudge)
            return True
        return False

    def command(self, callback):
        try:
            callback()
            self.refresh()
            self.ui.set_label(self.status, '')
        except (ValueError, TypeError, KeyError) as exc:
            self.ui.set_label(self.status, str(exc))

    def resize(self):
        def change():
            candidate = M.resize(self.model.doc, self.ui.get(self.fields['width']), self.ui.get(self.fields['height']))
            self.model.checkpoint()
            self.model.doc = candidate
        self.command(change)

    def set_reference(self, path):
        self.model.checkpoint()
        self.model.doc['reference'] = path

    def choose_reference(self):
        path = self.ui.choose_file()
        if path:
            self.command(lambda: self.set_reference(path))

    def copy(self):
        self.ui.copy(self.model.copy())

    def paste(self):
        self.model.paste(self.ui.paste())

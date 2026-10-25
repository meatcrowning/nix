# -*- coding: utf-8 -*-
"""Read-only token decorations for GTK 3.6 editable prompt buffers."""
from __future__ import unicode_literals
from gi.repository import Gtk, GLib, Gdk
from token_style import colours


class TokenMarks(object):
    def __init__(self, view, count, send, hover=False, region=None):
        self.view, self.count, self.send = view, count, send
        self.region = region
        self.hovered = None
        self.picking = False
        if hover:
            view.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
            view.connect("motion-notify-event", self.hover)
            view.connect("leave-notify-event", self.leave)
            view.connect("button-press-event", self.pick)
        self.identity = 'gtk-tokens-%s' % id(self)
        self.active, self.ready, self.timer = False, False, None
        self.boundaries = []
        self.marked = False
        self.tags = [view.get_buffer().create_tag(None) for _ in range(2)]
        self.separator = (0, 0, 0)
        view.connect('style-updated', self.style_changed)
        self.style_changed()
        self.request = None
        view.get_buffer().connect('changed', self.changed)
        view.connect_after('draw', self.draw)
        view.connect('destroy', self.destroy)
        count.set_no_show_all(True)
        count.hide()

    def style_changed(self, *_):
        context = self.view.get_style_context()
        foreground = context.get_color(Gtk.StateFlags.NORMAL)
        background = context.get_background_color(Gtk.StateFlags.NORMAL)
        selection = context.get_background_color(Gtk.StateFlags.SELECTED)
        for name in ('theme_base_color', 'theme_selected_bg_color'):
            found, color = context.lookup_color(name)
            if found:
                if name == 'theme_base_color': background = color
                else: selection = color
        rgb = lambda c: tuple(round(v * 255) for v in (c.red, c.green, c.blue))
        style = colours(rgb(foreground), rgb(background), rgb(selection))
        for tag, color in zip(self.tags, style['bands']):
            tag.set_property('background', color)
        self.separator = tuple(int(style['separator'][i:i+2], 16) / 255.0 for i in (1, 3, 5))
        self.view.queue_draw()

    def paint_bands(self):
        buf = self.view.get_buffer()
        start, end = buf.get_start_iter(), buf.get_end_iter()
        for tag in self.tags:
            buf.remove_tag(tag, start, end)
        if self.marked:
            cuts = [0] + self.boundaries + [buf.get_char_count()]
            for index, (a, b) in enumerate(zip(cuts, cuts[1:])):
                buf.apply_tag(self.tags[index % 2], buf.get_iter_at_offset(a), buf.get_iter_at_offset(b))

    def leave(self, *_):
        self.hovered = None
        self.send('heatmap_hover_end', owner='region:' + self.region() if self.region else 'prompt')
        return False

    def pick(self, view, event):
        if not self.picking or event.button != 1 or not self.marked:
            return False
        x, y = view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(event.x), int(event.y))
        result = view.get_iter_at_location(x, y)
        iterator = result[-1] if isinstance(result, tuple) else result
        text = self.text()
        position = iterator.get_offset()
        self.send('heatmap_pick', text=text, position=len(text[:position].encode('utf-16-le')) // 2,
                  region=self.region() if self.region else '')
        return True

    def hover(self, view, event):
        if not self.marked:
            return False
        x, y = view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(event.x), int(event.y))
        result = view.get_iter_at_location(x, y)
        iterator = result[-1] if isinstance(result, tuple) else result
        position = iterator.get_offset()
        token = sum(position >= boundary for boundary in self.boundaries)
        if token != self.hovered:
            self.hovered = token
            text = self.text()
            self.send('heatmap_hover', text=text, position=len(text[:position].encode('utf-16-le')) // 2,
                      region=self.region() if self.region else '')
        return False

    def text(self):
        buf = self.view.get_buffer()
        value = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        return value.decode('utf-8') if isinstance(value, bytes) else value

    def destroy(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def changed(self, *_):
        self.destroy()
        self.hovered = None
        self.boundaries, self.request, self.marked = [], None, False
        self.paint_bands()
        self.count.set_text('— tok')
        self.view.queue_draw()
        if self.active:
            self.timer = GLib.timeout_add(350, self.submit)

    def submit(self):
        self.timer = None
        self.request = self.text()
        self.send('moss_tokenize', identity=self.identity, text=self.request)
        return False

    def update(self, state):
        self.picking = bool(state.get('heatmap', {}).get('picking'))
        active = bool(state.get('flags', {}).get('layoutSupport'))
        if self.region:
            active = active and bool(self.region())
        ready = bool(state.get('ready'))
        self.count.set_visible(active)
        if (active, ready) != (self.active, self.ready):
            self.active, self.ready = active, ready
            self.changed()
        entry = state.get('tokenResults', {}).get(self.identity)
        if active and entry and entry['text'] == self.request == self.text():
            result = entry['result']
            count = max(0, result['count'] - result.get('template_tokens', 0)) if 'count' in result else '—'
            self.count.set_text('%s tok' % count)
            self.count.set_tooltip_text(result.get('error') or
                'Prompt tokens only; excludes the MOSS chat wrapper. Before weighting, wildcard expansion or layout compilation.')
            boundaries = result.get('boundaries', [])
            marked = 'count' in result
            if boundaries != self.boundaries or marked != self.marked:
                self.boundaries, self.marked = boundaries, marked
                self.paint_bands()
                self.view.queue_draw()

    def draw(self, view, cr):
        cr.set_source_rgb(*self.separator)
        cr.set_line_width(1)
        buf = view.get_buffer()
        for index in self.boundaries:
            rect = view.get_iter_location(buf.get_iter_at_offset(index))
            x, y = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, rect.x, rect.y)
            cr.move_to(x + .5, y + 2)
            cr.line_to(x + .5, y + rect.height - 2)
        cr.stroke()
        return False

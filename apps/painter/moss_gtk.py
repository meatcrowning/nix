# -*- coding: utf-8 -*-
"""Read-only token decorations for GTK 3.6 editable prompt buffers."""
from __future__ import unicode_literals
from gi.repository import Gtk, GLib


class TokenMarks(object):
    def __init__(self, view, count, send):
        self.view, self.count, self.send = view, count, send
        self.identity = 'gtk-tokens-%s' % id(self)
        self.active, self.ready, self.timer = False, False, None
        self.boundaries = []
        self.request = None
        view.get_buffer().connect('changed', self.changed)
        view.connect_after('draw', self.draw)
        view.connect('destroy', self.destroy)
        count.set_no_show_all(True)
        count.hide()

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
        self.boundaries, self.request = [], None
        self.count.set_text('— tokens')
        self.view.queue_draw()
        if self.active:
            self.timer = GLib.timeout_add(350, self.submit)

    def submit(self):
        self.timer = None
        self.request = self.text()
        self.send('moss_tokenize', identity=self.identity, text=self.request)
        return False

    def update(self, state):
        active = bool(state.get('flags', {}).get('layoutSupport'))
        ready = bool(state.get('ready'))
        self.count.set_visible(active)
        if (active, ready) != (self.active, self.ready):
            self.active, self.ready = active, ready
            self.changed()
        entry = state.get('tokenResults', {}).get(self.identity)
        if active and entry and entry['text'] == self.request == self.text():
            result = entry['result']
            self.count.set_text('%s tokens' % result.get('count', '—'))
            self.count.set_tooltip_text(result.get('error') or
                'Unweighted MOSS tokens. Includes %s prompt-template tokens; before wildcard expansion or layout compilation.' % result.get('template_tokens', 0))
            boundaries = result.get('boundaries', [])
            if boundaries != self.boundaries:
                self.boundaries = boundaries
                self.view.queue_draw()

    def draw(self, view, cr):
        color = view.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(color.red, color.green, color.blue, .4)
        cr.set_line_width(1)
        buf = view.get_buffer()
        for index in self.boundaries:
            rect = view.get_iter_location(buf.get_iter_at_offset(index))
            x, y = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, rect.x, rect.y)
            cr.move_to(x + .5, y + 2)
            cr.line_to(x + .5, y + rect.height - 2)
        cr.stroke()
        return False

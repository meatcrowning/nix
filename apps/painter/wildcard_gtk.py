# -*- coding: utf-8 -*-
"""A hover card with clickable wildcard lines for GTK 3.6 (pre-Popover)."""
from __future__ import unicode_literals
from gi.repository import Gtk, Gdk, GLib


class WildcardCard(object):
    def __init__(self, button, changed, editable=True):
        self.button, self.changed, self.editable = button, changed, editable
        self.rows, self.checks = [], []
        self.inside_button, self.inside_card = False, False
        self.open_timer, self.close_timer = None, None
        self.updating = False
        self.window = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.window.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.window.set_accept_focus(False)
        self.window.set_resizable(False)
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.OUT)
        self.window.add(frame)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        frame.add(scroll)
        self.scroll = scroll
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.set_border_width(6)
        scroll.add_with_viewport(self.box)
        for widget, card in ((button, False), (self.window, True)):
            widget.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            widget.connect('enter-notify-event', self.cross, card, True)
            widget.connect('leave-notify-event', self.cross, card, False)
        button.connect('destroy', self.destroy)
        button.connect('unmap', lambda *_: self.hide())

    def cross(self, widget, event, card, inside):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if card: self.inside_card = inside
        else: self.inside_button = inside
        if inside:
            if self.close_timer:
                GLib.source_remove(self.close_timer)
                self.close_timer = None
            if not card and not self.window.get_visible() and not self.open_timer:
                self.open_timer = GLib.timeout_add(400, self.show)
        else:
            if self.open_timer:
                GLib.source_remove(self.open_timer)
                self.open_timer = None
            if not self.close_timer:
                self.close_timer = GLib.timeout_add(300, self.maybe_hide)
        return False

    def maybe_hide(self):
        self.close_timer = None
        if not self.inside_button and not self.inside_card:
            self.window.hide()
        return False

    def show(self):
        self.open_timer = None
        if not self.button.get_mapped():
            return False
        parent = self.button.get_toplevel()
        self.window.set_transient_for(parent)
        self.window.show_all()
        x, y = self.button.translate_coordinates(parent, 0, self.button.get_allocated_height())
        ox, oy = parent.get_window().get_origin()[-2:]
        x, y = x + ox, y + oy
        screen = self.button.get_screen()
        geometry = screen.get_monitor_geometry(screen.get_monitor_at_point(x, y))
        width, height = self.window.get_size()
        x = max(geometry.x, min(x, geometry.x + geometry.width - width))
        y = max(geometry.y, min(y, geometry.y + geometry.height - height))
        self.window.move(x, y)
        return False

    def set_rows(self, rows):
        if rows == self.rows:
            return
        rebuild = [r['text'] for r in rows] != [r['text'] for r in self.rows] or not self.box.get_children()
        self.rows = [dict(row) for row in rows]
        self.updating = True
        if rebuild:
            for child in self.box.get_children(): child.destroy()
            self.checks = []
            if not rows:
                self.box.pack_start(Gtk.Label(label='No usable lines in this wildcard.'), False, False, 0)
            for index, row in enumerate(rows):
                check = Gtk.CheckButton(label=row['text'])
                check.set_focus_on_click(False)
                check.set_sensitive(self.editable)
                check.get_child().set_line_wrap(True)
                check.get_child().set_max_width_chars(48)
                check.connect('toggled', self.toggled, index)
                self.box.pack_start(check, False, False, 0)
                self.checks.append(check)
            self.scroll.set_size_request(360, min(320, max(42, len(rows) * 32)))
            self.box.show_all()
        for check, row in zip(self.checks, rows): check.set_active(row['enabled'])
        self.updating = False

    def toggled(self, check, index):
        if not self.updating:
            self.rows[index]['enabled'] = check.get_active()
            self.changed(index, check.get_active())

    def hide(self):
        for name in ('open_timer', 'close_timer'):
            timer = getattr(self, name)
            if timer: GLib.source_remove(timer)
            setattr(self, name, None)
        self.inside_button = self.inside_card = False
        self.window.hide()

    def destroy(self, *_):
        self.hide()
        self.window.destroy()

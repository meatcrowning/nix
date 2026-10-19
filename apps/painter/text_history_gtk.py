# -*- coding: utf-8 -*-
"""Per-editor undo for GTK 3.6, which has no native text undo stack."""
from __future__ import unicode_literals
from gi.repository import Gtk, Gdk, GLib


def snapshot(control):
    if isinstance(control, Gtk.TextView):
        buf = control.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        cursor = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        anchor = buf.get_iter_at_mark(buf.get_selection_bound()).get_offset()
    else:
        text, cursor = control.get_text(), control.get_position()
        bounds = control.get_selection_bounds()
        anchor = (bounds[0] if cursor == bounds[-1] else bounds[-1]) if bounds else cursor
    return (text.decode('utf-8') if isinstance(text, bytes) else text, cursor, anchor)


class History(object):
    def __init__(self, control, changed):
        self.control, self.notify = control, changed
        self.undo, self.redo = [], []
        self.last = snapshot(control)
        self.scope = self.document()
        self.pending, self.applying = None, False
        source = control.get_buffer() if isinstance(control, Gtk.TextView) else control
        source.connect('changed', self.changed)
        control.connect('destroy', self.destroy)
        control.connect('key-press-event', self.key)

    def destroy(self, *_):
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = None

    def document(self):
        return getattr(self.control, '_text_history_scope', lambda: None)()

    def reset(self):
        self.destroy()
        self.undo[:], self.redo[:] = [], []
        self.last = snapshot(self.control)
        self.scope = self.document()
        self.notify()

    def changed(self, *_):
        if not self.applying and not self.pending:
            # A single edit can emit delete+insert and trigger layout refreshes.
            # Commit the final text after that event, never the transient blank.
            self.pending = GLib.idle_add(self.flush)

    def flush(self):
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = None
        current = snapshot(self.control)
        if self.scope != self.document():
            self.reset()
            return False
        if current[0] != self.last[0]:
            if self.control.is_focus():
                self.undo.append(self.last)
                self.undo = self.undo[-100:]
                while len(self.undo) > 1 and sum(len(s[0]) for s in self.undo) > 1000000:
                    self.undo.pop(0)
            else:
                # Loading another model/region into an unfocused field starts
                # a new document; its predecessor must not be undoable here.
                self.undo[:] = []
            self.redo[:] = []
        self.last = current
        self.notify()
        return False

    def apply(self, redo=False):
        self.flush()
        source, target = (self.redo, self.undo) if redo else (self.undo, self.redo)
        if not source or not self.control.get_editable() or not self.control.is_sensitive():
            return
        target.append(snapshot(self.control))
        text, cursor, anchor = source.pop()
        self.applying = True
        try:
            if isinstance(self.control, Gtk.TextView):
                buf = self.control.get_buffer()
                buf.set_text(text)
                buf.select_range(buf.get_iter_at_offset(cursor), buf.get_iter_at_offset(anchor))
            else:
                self.control.set_text(text)
                self.control.select_region(anchor, cursor)
                if anchor == cursor: self.control.set_position(cursor)
            self.last = snapshot(self.control)
        finally:
            self.applying = False
        self.notify()

    def key(self, control, event):
        if not event.state & Gdk.ModifierType.CONTROL_MASK or event.state & Gdk.ModifierType.MOD1_MASK:
            return False
        key = Gdk.keyval_name(event.keyval).lower()
        if key not in ('z', 'y'):
            return False
        self.apply(key == 'y' or bool(event.state & Gdk.ModifierType.SHIFT_MASK))
        return True


class TextHistory(object):
    def __init__(self, changed):
        self.changed, self.focus = changed, None

    def watch(self, window):
        window.connect('set-focus', self.focused)
        self.focused(window, window.get_focus())

    def focused(self, window, control):
        if isinstance(control, (Gtk.TextView, Gtk.Entry)):
            if not hasattr(control, '_text_history'):
                control._text_history = History(control, self.changed)
                control.connect('destroy', self.forgotten)
            self.focus = control
            control._text_history.flush()
        elif control is not None:
            self.focus = None
        self.changed()

    def forgotten(self, control):
        if self.focus is control:
            self.focus = None
            self.changed()

    def history(self):
        control = self.focus
        if control is not None and control.get_editable() and control.is_sensitive():
            return control._text_history
        return None

    def available(self, redo=False):
        history = self.history()
        return bool(history and (history.redo if redo else history.undo))

    def apply(self, redo=False):
        history = self.history()
        if history:
            history.apply(redo)

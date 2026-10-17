# -*- coding: utf-8 -*-
"""GTK spelling presentation; the modern engine owns the shared checker."""
from __future__ import unicode_literals
from gi.repository import Gtk, GLib, Pango
from xml.sax.saxutils import escape


def text(control):
    if isinstance(control, Gtk.TextView):
        b = control.get_buffer()
        value = b.get_text(b.get_start_iter(), b.get_end_iter(), True)
        return value.decode('utf-8') if isinstance(value, bytes) else value
    value = control.get_text()
    return value.decode('utf-8') if isinstance(value, bytes) else value


class Spelling(object):
    def __init__(self, send):
        self.send, self.fields, self.serial = send, {}, 0

    def attach(self, control):
        self.serial += 1
        field = Field(self, self.serial, control)
        self.fields[self.serial] = field
        return field

    def receive(self, state):
        field = self.fields.get(state.get('field'))
        if field and text(field.control) == state.get('text'):
            field.apply(state.get('words', []))


class Field(object):
    def __init__(self, owner, identity, control):
        self.owner, self.identity, self.control = owner, identity, control
        self.timer, self.words, self.checked, self.position = None, [], '', None
        self.multiline = isinstance(control, Gtk.TextView)
        if self.multiline:
            self.buffer = control.get_buffer()
            self.tag = self.buffer.create_tag(None, underline=Pango.Underline.ERROR)
            self.buffer.connect('changed', self.schedule)
        else:
            control.connect('changed', self.schedule)
        control.connect('button-press-event', self.press)
        control.connect('populate-popup', self.menu)
        control.connect('destroy', self.destroy)
        self.schedule()

    def destroy(self, *_):
        if self.timer: GLib.source_remove(self.timer)
        self.owner.fields.pop(self.identity, None)

    def schedule(self, *_):
        if self.timer: GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(350, self.check)

    def check(self):
        self.timer = None
        self.owner.send(dict(op='spell', field=self.identity, text=text(self.control)))
        return False

    def apply(self, words):
        self.words, self.checked = words, text(self.control)
        if self.multiline:
            self.buffer.remove_tag(self.tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())
            for word in words:
                self.buffer.apply_tag(self.tag, self.buffer.get_iter_at_offset(word['start']), self.buffer.get_iter_at_offset(word['end']))
        else:
            # Quantal's introspection lacks Pango.attr_underline_new.
            parts, end = [], 0
            for word in words:
                parts.append(escape(self.checked[end:word['start']]))
                parts.append('<span underline="error">%s</span>' % escape(self.checked[word['start']:word['end']]))
                end = word['end']
            parts.append(escape(self.checked[end:]))
            parsed = Pango.parse_markup(''.join(parts), -1, '\x00')
            self.control.set_attributes(parsed[-3])

    def press(self, control, event):
        self.position = None
        if event.button != 3: return False
        control.grab_focus()
        if self.multiline:
            x, y = control.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(event.x), int(event.y))
            result = control.get_iter_at_location(x, y)
            iterator = result[-1] if isinstance(result, tuple) else result
            self.position = iterator.get_offset()
        else:
            x, y = control.get_layout_offsets()
            found, index, trailing = control.get_layout().xy_to_index(int((event.x-x)*Pango.SCALE), int((event.y-y)*Pango.SCALE))
            index = control.layout_index_to_text_index(index)
            self.position = len(text(control).encode('utf-8')[:index].decode('utf-8')) + trailing
        return False

    def correct(self, word, replacement):
        if text(self.control) != self.checked: return
        start, end = word['start'], word['end']
        if self.multiline:
            self.buffer.begin_user_action()
            self.buffer.delete(self.buffer.get_iter_at_offset(start), self.buffer.get_iter_at_offset(end))
            self.buffer.insert(self.buffer.get_iter_at_offset(start), replacement)
            self.buffer.end_user_action()
        else:
            self.control.delete_text(start, end)
            self.control.insert_text(replacement, start)
        self.control.grab_focus()

    def learn(self, word):
        self.owner.send(dict(op='spell_learn', word=word['word']))
        for field in list(self.owner.fields.values()): field.schedule()

    def menu(self, control, menu):
        if text(control) != self.checked: return
        pos = self.position
        self.position = None
        if pos is None:
            pos = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset() if self.multiline else control.get_position()
        word = next((w for w in self.words if w['start'] <= pos <= w['end']), None)
        if not word: return
        items = []
        for suggestion in word['suggestions']:
            item = Gtk.MenuItem(label=suggestion)
            item.connect('activate', lambda _, value=suggestion: self.correct(word, value))
            items.append(item)
        if not items:
            item = Gtk.MenuItem(label='No suggestions'); item.set_sensitive(False); items.append(item)
        item = Gtk.MenuItem(label='Add to dictionary')
        item.connect('activate', lambda _: self.learn(word)); items.append(item)
        items.append(Gtk.SeparatorMenuItem())
        for i, item in enumerate(items): menu.insert(item, i)
        menu.show_all()

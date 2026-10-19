# -*- coding: utf-8 -*-
"""Run only inside unity-test.sh, with its scratch display and main window."""
from __future__ import unicode_literals
import os
assert os.environ['HOME'] == '/home/test' and os.environ['DISPLAY'] == ':93'
from gi.repository import Gtk, Gdk
from text_history_gtk import snapshot


def drain():
    while Gtk.events_pending(): Gtk.main_iteration()


def run(window):
    dialog = Gtk.Dialog('Text history fixture', window)
    window.text_history.watch(dialog)
    fields = [Gtk.TextView(), Gtk.Entry(), Gtk.SpinButton.new_with_range(0, 100, 1)]
    for field in fields: dialog.get_content_area().pack_start(field, False, False, 0)
    dialog.show_all()
    try:
        for field in fields:
            field.grab_focus()
            drain()
            history = field._text_history
            before = snapshot(field)[0]
            if isinstance(field, Gtk.TextView):
                field.get_buffer().insert_at_cursor('hello café')
            else:
                field.set_text('42' if isinstance(field, Gtk.SpinButton) else 'hello café')
            drain()
            after = snapshot(field)[0]
            assert before != after and window.actions['undo'][0].get_sensitive()
            window.actions['undo'][0].activate()
            assert snapshot(field)[0] == before
            assert window.actions['redo'][0].get_sensitive()
            window.actions['redo'][0].activate()
            assert snapshot(field)[0] == after
            event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
            event.key.keyval, event.key.state = Gdk.KEY_z, Gdk.ModifierType.CONTROL_MASK
            assert field.emit('key-press-event', event)
            assert snapshot(field)[0] == before
            event.key.state |= Gdk.ModifierType.SHIFT_MASK
            assert field.emit('key-press-event', event)
            assert snapshot(field)[0] == after
            history.apply()
            if isinstance(field, Gtk.TextView): field.get_buffer().set_text('new branch')
            else: field.set_text('13' if isinstance(field, Gtk.SpinButton) else 'new branch')
            drain()
            assert not history.redo
        # Polling/refreshing a field with identical text must not add an undo.
        field = fields[0]
        field.grab_focus()
        drain()
        history = field._text_history
        count = len(history.undo)
        field.get_buffer().set_text(snapshot(field)[0])
        drain()
        assert len(history.undo) == count
        # A different region loaded while the field is unfocused is a new document.
        fields[1].grab_focus()
        field.get_buffer().set_text('another region')
        drain()
        field.grab_focus()
        drain()
        assert not history.undo and not history.redo
        scope = ['region a']
        field._text_history_scope = lambda: scope[0]
        history.reset()
        field.get_buffer().insert_at_cursor(' edit')
        drain()
        assert history.undo
        scope[0] = 'region b'
        history.apply()
        assert not history.undo and snapshot(field)[0] == 'another region edit'
        field.set_editable(False)
        window.update_text_actions()
        assert not window.actions['undo'][0].get_sensitive()
    finally:
        dialog.destroy()
        window.text_history.focus = None
        window.update_text_actions()
    print('PASS: text undo/redo menus and shortcuts, Unicode, entries, multiline, branching and field isolation')

run(parent)

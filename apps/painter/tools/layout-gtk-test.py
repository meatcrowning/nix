# -*- coding: utf-8 -*-
"""Loaded only by unity-gtk-test.py in its private display namespace."""
from __future__ import unicode_literals
import os
assert os.environ['HOME'] == '/home/test' and os.environ['DISPLAY'] == ':93'
from gi.repository import Gtk, Gdk
import moss_layout as M
from layout_gtk import open_editor


def run(parent):
    accepted = []
    initial_width = parent.get_allocated_width()
    before_windows = [w for w in Gtk.Window.list_toplevels() if w.get_visible()]
    parent.layout_box.show()
    e = open_editor(parent.layout_box, M.fresh(caption='A travel poster'), accepted.append)
    assert [w for w in Gtk.Window.list_toplevels() if w.get_visible()] == before_windows
    assert e.canvas.get_toplevel() is parent
    assert e.side.get_visible()
    assert e.add_button.get_image() is not None
    assert e.add_button.get_tooltip_text() == 'Add region'
    assert not e.list.region_box.get_visible()
    u = e.ui
    from spelling_gtk import Spelling, text
    requests = []
    checker = Spelling(requests.append)
    for control in (Gtk.TextView(), Gtk.Entry()):
        field = checker.attach(control)
        if isinstance(control, Gtk.TextView): control.get_buffer().set_text('é helo world')
        else: control.set_text('é helo world')
        field.check()
        assert requests[-1]['text'] == 'é helo world'
        result = dict(field=field.identity, text='é helo world', words=[dict(start=2, end=6, word='helo', suggestions=['hello'])])
        checker.receive(result)
        if isinstance(control, Gtk.TextView):
            assert field.tag in control.get_buffer().get_iter_at_offset(3).get_tags()
        else:
            assert control.get_attributes() is not None
        field.position = 3
        menu = Gtk.Menu()
        field.menu(control, menu)
        assert menu.get_children()[0].get_label() == 'hello'
        menu.get_children()[0].activate()
        assert text(control) == 'é hello world'
        checker.receive(result)
        assert field.checked == 'é helo world', 'stale result changed the checked text'
        menu.destroy()
        control.destroy()
    assert all(any(f.control is parent.controls[key] for f in parent.spelling.fields.values()) for key in ('positive', 'negative', 'system_prompt'))
    while Gtk.events_pending(): Gtk.main_iteration()
    assert e.side.get_allocation().y >= e.canvas.get_allocation().y + e.canvas.get_allocated_height()
    original_height = e.canvas.get_allocated_height()
    for signal, kind, y in [('button-press-event', Gdk.EventType.BUTTON_PRESS, 100),
                            ('motion-notify-event', Gdk.EventType.MOTION_NOTIFY, 180),
                            ('button-release-event', Gdk.EventType.BUTTON_RELEASE, 180)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY:
            event.motion.y_root = y
        else:
            event.button.button = 1
            event.button.y_root = y
        e.canvas.resize_handle.emit(signal, event)
    assert e.canvas.get_size_request()[1] == original_height + 80
    assert not e.canvas.resize_handle.has_grab()
    assert parent.layout_height == original_height + 80
    reopened = open_editor(parent.layout_box, M.fresh(), accepted.append)
    assert reopened.canvas.get_size_request()[1] == original_height + 80
    reopened.ui.close()
    e.canvas.set_size_request(180, original_height)
    while Gtk.events_pending(): Gtk.main_iteration()
    parent.params_scroll.get_vadjustment().set_value(parent.layout_box.get_allocation().y)
    u.set(e.tool, 'text')
    e.add_button.clicked()
    assert e.model.tool == 'text'
    ox, oy, w, h = e.rect
    for kind, x, y in [(Gdk.EventType.BUTTON_PRESS, -5 / w, .2), (Gdk.EventType.MOTION_NOTIFY, 1.2, .5), (Gdk.EventType.BUTTON_RELEASE, .7, .5)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY:
            event.motion.x, event.motion.y = ox + x * w, oy + y * h
            event.motion.state = Gdk.ModifierType.BUTTON1_MASK
            e.canvas.emit('motion-notify-event', event)
        else:
            event.button.button = 1
            event.button.x, event.button.y = ox + x * w, oy + y * h
            e.canvas.emit('button-press-event' if kind == Gdk.EventType.BUTTON_PRESS else 'button-release-event', event)
    assert len(e.model.doc['items']) == 1
    assert e.list.region_box.get_visible()
    assert e.list.region_scroll.get_size_request()[1] < 80
    assert e.model.tool == 'select' and e.side.get_visible()
    e.buttons['Lock'].clicked()
    assert not e.model.selected and e.model.doc['items'][0]['locked']
    e.selection_changed([e.model.doc['items'][0]['id']])
    e.buttons['Lock'].clicked()
    assert not e.model.chosen()[0]['locked']
    e.buttons['Hide'].clicked()
    assert not e.model.chosen()[0]['enabled']
    e.buttons['Hide'].clicked()
    assert e.model.chosen()[0]['enabled']
    assert 'item.locked' not in e.fields and 'item.enabled' not in e.fields
    for signal, kind, y in [('button-press-event', Gdk.EventType.BUTTON_PRESS, 100),
                            ('motion-notify-event', Gdk.EventType.MOTION_NOTIFY, 180),
                            ('button-release-event', Gdk.EventType.BUTTON_RELEASE, 180)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY: event.motion.y_root = y
        else:
            event.button.button = 1
            event.button.y_root = y
        e.list.resize_handle.emit(signal, event)
    assert parent.region_list_height >= 80
    assert e.list.region_scroll.get_size_request()[1] == parent.region_list_height

    toolbar = e.add_button.get_parent()
    assert e.buttons['Duplicate'].get_parent() is toolbar
    assert e.buttons['Undo'].get_parent() is toolbar
    assert e.buttons['Delete'].get_parent() is toolbar
    row = e.model.doc['items'][0]
    assert row['label'] == 'text' and abs(row['box'][2] - .7) < .02
    u.set(e.tool, 'character')
    assert e.model.chosen()[0]['label'] == 'character'
    u.set(e.tool, 'text')
    assert e.model.chosen()[0]['label'] == 'text'
    u.set(e.fields['summary.meta'], 'poster, illustration')
    u.set(e.fields['summary.palette'], '#ffffff, #123456')
    u.set(e.fields['item.caption'], 'Large heading')
    prompt = e.fields['item.caption'][1]
    for signal, kind, y in [('button-press-event', Gdk.EventType.BUTTON_PRESS, 100),
                            ('motion-notify-event', Gdk.EventType.MOTION_NOTIFY, 180),
                            ('button-release-event', Gdk.EventType.BUTTON_RELEASE, 180)]:
        event = Gdk.Event.new(kind)
        if kind == Gdk.EventType.MOTION_NOTIFY: event.motion.y_root = y
        else:
            event.button.button = 1
            event.button.y_root = y
        prompt.resize_handle.emit(signal, event)
    assert parent.region_prompt_height > 95
    u.set(e.fields['item.text'], 'HELLO\n世界')
    u.set(e.fields['type.family'], 'serif')
    u.set(e.fields['type.color'], '#123456')
    u.set(e.fields['type.outline'], 'thin white outline')
    u.set(e.fields['type.shadow'], 'soft grey shadow')
    u.set(e.fields['type.surface'], 'painted wooden sign')
    u.set(e.fields['item.palette'], '#abcdef')
    u.set(e.fields['item.tags'], 'title, lettering')
    u.set(e.fields['enabled'], True)
    u.set(e.units, 'pixels')
    u.set(e.fields['box.position'], '128, 256')
    e.fields['box.position'][1].emit('activate')
    assert e.model.doc['items'][0]['box'][0] == .125
    e.buttons['Lock'].clicked()
    assert not e.fields['box.position'][2].get_sensitive()
    e.selection_changed([e.model.doc['items'][0]['id']])
    e.set_reference('/home/test/out/fixture.png')
    e.refresh()
    assert e.reference, 'reference image must load in GTK 3.6'
    assert b'data:image/png;base64,' in e.render(700, 600)
    copied = []
    u.copy = copied.append
    u.paste = lambda: copied[0]
    e.copy(); e.paste()
    assert len(e.model.doc['items']) == 2
    e.model.undo(); assert len(e.model.doc['items']) == 1
    u.set(e.fields['custom_x'], '20, 80')
    u.set(e.fields['custom_y'], '25, 75')
    assert e.model.doc['custom_x'] == [.2,.8]
    while Gtk.events_pending(): Gtk.main_iteration()
    assert parent.get_allocated_width() == initial_width, 'inline inspector enlarged the main window'
    window = u.window.get_window()
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, u.window.get_allocated_width(), u.window.get_allocated_height())
    pixbuf.savev('/home/test/layout.png', 'png', [], [])
    e.publish()
    assert accepted and accepted[-1]['enabled']
    compiled = M.compile(accepted[-1])
    assert 'HELLO' in compiled and 'reference' not in compiled
    doc = M.valid(e.model.doc)
    doc['summary']['caption'] = 'Reloaded scene'
    e.load(doc)
    e.selection_changed([e.model.doc['items'][0]['id']])
    e.buttons['Delete'].clicked()
    assert not e.model.doc['items']
    e.ui.close()
    parent.browse()
    print('PASS: GTK inline layout drawing, text, palettes, geometry locks, guides, underlay, copy and autosave')

if 'parent' in globals():
    run(parent)

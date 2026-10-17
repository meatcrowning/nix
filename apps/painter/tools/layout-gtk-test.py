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
    e = open_editor(parent, M.fresh(), accepted.append)
    u = e.ui
    while Gtk.events_pending(): Gtk.main_iteration()
    u.set(e.tool, 'text')
    ox, oy, w, h = e.rect
    for kind, x, y in [(Gdk.EventType.BUTTON_PRESS, .15, .2), (Gdk.EventType.MOTION_NOTIFY, .7, .5), (Gdk.EventType.BUTTON_RELEASE, .7, .5)]:
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
    row = e.model.doc['items'][0]
    assert row['label'] == 'text' and abs(row['box'][2] - .55) < .02
    u.set(e.fields['summary.caption'], 'A travel poster')
    u.set(e.fields['summary.meta'], 'poster, illustration')
    u.set(e.fields['summary.palette'], '#ffffff, #123456')
    u.set(e.fields['item.caption'], 'Large heading')
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
    u.set(e.fields['box.x'], 128)
    assert e.model.doc['items'][0]['box'][0] == .125
    u.set(e.fields['item.locked'], True)
    assert not e.fields['box.x'][2].get_sensitive()
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
    window = u.window.get_window()
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, u.window.get_allocated_width(), u.window.get_allocated_height())
    pixbuf.savev('/home/test/layout.png', 'png', [], [])
    e.apply()
    assert accepted and accepted[0]['enabled']
    compiled = M.compile(accepted[0])
    assert 'HELLO' in compiled and 'reference' not in compiled
    print('PASS: GTK layout drawing, text, palettes, geometry locks, guides, underlay, copy and apply')

if 'parent' in globals():
    run(parent)

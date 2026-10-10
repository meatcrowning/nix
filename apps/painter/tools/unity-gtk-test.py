#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Real Quantal GTK controls, only inside unity-test.sh's private X server."""
from __future__ import unicode_literals
import os
import sys
import traceback
assert os.environ['HOME'] == '/home/test'
assert os.environ['DISPLAY'] == ':93'
sys.path.insert(0, '/home/test/nix/apps/painter')
from unity_frontend import Gtk, GLib, GObject, Window
from gi.repository import Gdk
GObject.threads_init()
assert (Gtk.get_major_version(), Gtk.get_minor_version()) == (3, 6)
assert Gtk.Settings.get_default().get_property('gtk-theme-name') == 'Ambiance'

# A private global-menu registrar proves GTK exports real menu actions. There
# is no Unity shell, focus change, notification daemon, or session manager.
registrations = []
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
owner = dbus.service.BusName('com.canonical.AppMenu.Registrar', bus)
class Registrar(dbus.service.Object):
    @dbus.service.method('com.canonical.AppMenu.Registrar', in_signature='uo', out_signature='', sender_keyword='sender')
    def RegisterWindow(self, xid, path, sender=None):
        registrations.append((int(xid), sender, str(path)))
    @dbus.service.method('com.canonical.AppMenu.Registrar', in_signature='u', out_signature='')
    def UnregisterWindow(self, xid):
        pass
    @dbus.service.method('com.canonical.AppMenu.Registrar', in_signature='', out_signature='a(uso)')
    def GetMenus(self):
        return registrations
registrar = Registrar(bus, '/com/canonical/AppMenu/Registrar')
window = Window(sys.argv[1])
step = [0]
failed = [False]
video_tick = ['']

def select(name):
    for i, row in enumerate(window.tiles):
        if row[2].endswith('/' + name):
            window.gallery.select_path(Gtk.TreePath.new_from_string(str(i)))
            return
    raise AssertionError('missing output: ' + name)

def test():
    try:
        if not window.state.get('model'):
            return True
        if step[0] == 0:
            assert len(window.state['models']) == 2
            assert window.get_title() == 'Painter'
            assert window.actions['generate'][0].get_sensitive()
            shot = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, window.get_allocated_width(), window.get_allocated_height())
            shot.savev('/home/test/window.png', 'png', [], [])
            assert window.text_boxes['positive'].height == 210
            # Exercise the handle's press/motion/release contract using local
            # events only, inside this private X server.
            class Event:
                button = 1
                y_root = 100
            for key, delta, expected in [('positive', 75, 285), ('negative', -1000, 40),
                                         ('system_prompt', 1000, 600)]:
                box = window.text_boxes[key]
                event = Event()
                box.press(box.handle, event)
                event.y_root += delta
                box.motion(box.handle, event)
                box.release(box.handle, event)
                assert box.height == expected
            window.controls['aspectW'].set_value(16)
            window.controls['aspectH'].set_value(9)
            window.controls['megapixels'].set_value(.8)
            window.controls['positive'].get_buffer().set_text('a native GTK prompt')
            window.controls['count'].set_value(2)
            window.controls['seedPolicy'].set_active_id('Fixed')
            window.controls['seed'].set_text('1234')
            window.generate()
        elif step[0] == 1:
            assert window.state['settings']['positive'] == 'a native GTK prompt'
            assert window.state['settings']['aspectW'] == 16
            assert window.state['settings']['aspectH'] == 9
            assert window.state['settings']['megapixels'] == .8
            assert len(window.tiles) == 3
            select('fixture.png')
            window.view()
            assert window.pages.get_current_page() == 1
            window.restore()
        elif step[0] == 2:
            assert window.values()['positive'] == 'restored prompt'
            assert window.values()['seed'] == 42
            assert window.values()['aspectW'] == 5
            assert window.values()['aspectH'] == 6
            assert registrations, 'GTK global menu did not register'
            assert window.picture.get_pixbuf() is not None
            assert window.viewer.scale == 1.0, ('fit size', window.viewer.scale, window.viewer.scroll.get_allocated_width(), window.viewer.scroll.get_allocated_height())
            window.zoom_by(1.25)
            assert window.viewer.scale == 1.25
            window.fit_image()
            assert window.viewer.zoom == 0
            window.viewer.set_zoom(1)
            assert window.picture.get_pixbuf().get_width() == 80
            window.browse()
            assert window.viewer.get_parent() == window.preview_box
            assert window.picture.get_pixbuf() is not None
            select('edit.png')
        elif step[0] == 3:
            assert window.viewer.before is not None
            window.viewer.compare.set_value(0)
            red = window.picture.get_pixbuf().get_pixels()
            window.viewer.compare.set_value(100)
            blue = window.picture.get_pixbuf().get_pixels()
            assert red != blue, 'comparison slider did not reveal before image'
            select('clip.mp4')
        elif step[0] == 4:
            assert window.viewer.video
            assert window.picture.get_pixbuf() is not None
            assert window.viewer.natural_size == [96, 64]
            assert window.viewer.duration > 0
            video_tick[0] = window.frame_tick
            window.viewer.set_zoom(2)
            assert window.viewer.zoom == 0, 'video zoom must be disabled'
            window.view()
        elif step[0] == 5:
            assert video_tick[0] != window.frame_tick, 'clip frames did not advance/loop'
            window.send('playback')
        elif step[0] == 6:
            video_tick[0] = window.frame_tick
        elif step[0] == 7:
            assert video_tick[0] == window.frame_tick, 'paused clip still advancing'
            select('fixture.png')
        elif step[0] == 8:
            assert not window.viewer.video
            assert window.viewer.original.get_width() == 80
            window.view()
            window.viewer.set_zoom(16)
        elif step[0] == 9:
            view = window.viewer
            assert view.scale == 16
            assert view.picture.get_pixbuf().get_width() <= view.scroll.get_allocated_width()
            class Event:
                button = 1
                x_root = 400
                y_root = 300
            event = Event()
            view.press(view.events, event)
            event.x_root -= 60
            event.y_root -= 40
            view.motion(view.events, event)
            view.release(view.events, event)
            assert view.scroll.get_hadjustment().get_value() == 60
            assert view.scroll.get_vadjustment().get_value() == 40
            old = window.selection
            index = next(i for i, row in enumerate(window.tiles) if row[2] == old)
            window.walk(-1 if index else 1)
            assert window.selection != old
            select('fixture.png')
            window.controls['positive'].get_buffer().set_text('last edit before closing')
            window.close_window()
            print('PASS: GTK 3.6 controls, resized prompts, fit/zoom/compare, muted video, Browse/View, global menu')
            return False
        step[0] += 1
        return True
    except Exception:
        traceback.print_exc()
        failed[0] = True
        window.connection.close()
        Gtk.main_quit()
        return False
GLib.timeout_add(1200, test)
Gtk.main()
if not failed[0]:
    window = Window(sys.argv[1])
    def reopened():
        if not window.state.get('model'):
            return True
        try:
            assert window.text_boxes['positive'].height == 285
            assert window.text_boxes['negative'].height == 40
            assert window.text_boxes['system_prompt'].height == 600
            assert window.values()['positive'] == 'last edit before closing'
            print('PASS: prompt heights and text survive closing and reopening')
        except Exception:
            traceback.print_exc()
            failed[0] = True
        window.close_window()
        return False
    GLib.timeout_add(500, reopened)
    Gtk.main()
raise SystemExit(1 if failed[0] else 0)

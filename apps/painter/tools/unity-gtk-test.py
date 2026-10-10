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
            window.controls['positive'].get_buffer().set_text('a native GTK prompt')
            window.controls['count'].set_value(2)
            window.controls['seedPolicy'].set_active_id('Fixed')
            window.controls['seed'].set_text('1234')
            window.generate()
        elif step[0] == 1:
            assert window.state['settings']['positive'] == 'a native GTK prompt'
            assert len(window.tiles) == 1
            window.gallery.select_path(Gtk.TreePath.new_from_string('0'))
            window.view()
            assert window.pages.get_current_page() == 1
            window.restore()
        elif step[0] == 2:
            assert window.values()['positive'] == 'restored prompt'
            assert window.values()['seed'] == 42
            assert window.values()['width'] == 640
            assert registrations, 'GTK global menu did not register'
            assert window.picture.get_pixbuf() is not None
            window.browse()
            window.controls['positive'].get_buffer().set_text('last edit before closing')
            window.close_window()
            print('PASS: GTK 3.6 / Ambiance, native controls, preview and global menu registration')
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
raise SystemExit(1 if failed[0] else 0)

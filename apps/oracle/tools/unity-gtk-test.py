#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Real Quantal GTK controls, only inside unity-test.sh's private X server."""
from __future__ import unicode_literals
import os
import sys
import traceback
assert os.environ['HOME'] == '/home/test'
assert os.environ['DISPLAY'] == ':93'
sys.path.insert(0, '/home/test/nix/apps/oracle')
from unity_frontend import Gtk, GLib, GObject, Window, buffer_text
from gi.repository import Gdk
GObject.threads_init()
assert (Gtk.get_major_version(), Gtk.get_minor_version()) == (3, 6)
assert Gtk.Settings.get_default().get_property('gtk-theme-name') in ('Ambiance', 'Ambiance-Dark')

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
saved_id = ['']

def test():
    try:
        if not window.state.get('model'):
            return True
        if step[0] == 0:
            assert window.get_title() == 'Chatter'
            assert window.send_button.get_sensitive()
            assert not window.stop_button.get_sensitive()
            assert window.models.get_active_text() == 'fixture:latest'
            with open('/home/test/attachment.txt', 'w') as f:
                f.write('A fixture attachment')
            window.send('attach', path='/home/test/attachment.txt')
            step[0] = 1
        elif step[0] == 1 and window.state['attachments']:
            window.compose.get_buffer().set_text('A test message')
            window.submit()
            step[0] = 2
        elif step[0] == 2 and len(window.turns) == 2 and not window.state['busy']:
            assert buffer_text(window.turns[1].body) == 'Hello from the shared engine.'
            assert 'A little reasoning' in buffer_text(window.turns[1].detail_text)
            assert not window.turns[1].details.get_expanded()
            assert buffer_text(window.compose) == ''
            assert not window.state['attachments']
            assert registrations, 'global menu not registered'
            shot = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0,
                                             window.get_allocated_width(), window.get_allocated_height())
            shot.savev('/home/test/window.png', 'png', [], [])
            saved_id[0] = window.state['session']
            window.send('new')
            step[0] = 3
        elif step[0] == 3 and not window.state['rows'] and window.state['sessions']:
            window.send('session', id=saved_id[0])
            step[0] = 4
        elif step[0] == 4 and window.state['session'] == saved_id[0]:
            assert buffer_text(window.turns[1].body) == 'Hello from the shared engine.'
            window.close()
            return False
        return True
    except Exception:
        traceback.print_exc()
        failed[0] = True
        window.close()
        return False
GLib.timeout_add(100, test)
Gtk.main()
sys.exit(1 if failed[0] else 0)

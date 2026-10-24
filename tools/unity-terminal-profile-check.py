"""Run with original GTK only inside unity-quantal-test.sh's namespace."""
from __future__ import print_function
import subprocess
import sys
import time
from gi.repository import Gio, GLib, Gtk
sys.path.insert(0, sys.argv[1])
from terminal_profile import ROOT, PROFILE, command

settings = Gio.Settings.new('org.gnome.desktop.interface')
original = settings.get_string('gtk-theme')
original_default = command('--get', ROOT + '/global/default_profile')
entry = Gtk.Entry()

def expected():
    style = entry.get_style_context()
    def color(value):
        return '#%04x%04x%04x' % tuple(int(round(channel * 65535)) for channel in (value.red, value.green, value.blue))
    return color(style.get_color(Gtk.StateFlags.NORMAL)), color(style.lookup_color('base_color')[1])

try:
    seen = []
    for theme in ('Radiance', 'Ambiance-Dark'):
        settings.set_string('gtk-theme', theme)
        deadline = time.time() + 15
        while time.time() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            colors = (command('--get', PROFILE + '/foreground_color'), command('--get', PROFILE + '/background_color'))
            if Gtk.Settings.get_default().get_property('gtk-theme-name') == theme and colors == expected():
                break
            time.sleep(.1)
        else:
            raise AssertionError((theme, colors, expected()))
        seen.append(colors)
    assert seen[0] != seen[1], seen
    assert command('--get', PROFILE + '/visible_name') == 'Desktop Theme'
    assert command('--get', PROFILE + '/use_theme_colors') == 'false'
    assert command('--get', ROOT + '/global/profile_list').count('DesktopTheme') == 1
    assert command('--get', ROOT + '/global/default_profile') == original_default
    print('PASS: original Terminal profile follows light/dark GTK colours without changing the default')
finally:
    settings.set_string('gtk-theme', original)

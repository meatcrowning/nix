"""Wallpaper focus color controller for the existing display service (GTK 3.6)."""
from __future__ import print_function
import json
import os
import re
import subprocess
import threading

from gi.repository import Gio, GLib

HERE = os.path.dirname(os.path.abspath(__file__))
GENERATED = re.compile(r'^Unity-Focus-(Ambiance-Dark|Ambiance|Radiance)-[0-9a-f]{16}$')


def base_theme(name):
    match = GENERATED.match(name)
    return match.group(1) if match else name


def base_icons(name):
    if name.startswith('Unity-Focus-Icons-'):
        try:
            with open(os.path.join(os.path.expanduser('~/.icons'), name, '.complete')) as stream:
                return json.load(stream)['base']
        except (IOError, ValueError, KeyError):
            pass
    return name


class FocusColor(object):
    def __init__(self, enabled, brightness=100):
        self.enabled = enabled
        self.brightness = brightness
        self.serial = 0
        self.interface = Gio.Settings.new('org.gnome.desktop.interface')
        self.background = Gio.Settings.new('org.gnome.desktop.background')
        self.wm = Gio.Settings.new('org.gnome.desktop.wm.preferences')
        self.interface.connect('changed::gtk-theme', self.changed)
        self.interface.connect('changed::icon-theme', self.changed)
        self.background.connect('changed', self.changed)
        self.wm.connect('changed::theme', self.changed)
        self.file_monitor = None
        self.applying = False
        self.changed()

    def configure(self, enabled, brightness):
        if self.enabled != enabled or self.brightness != brightness:
            self.enabled = enabled
            self.brightness = brightness
            self.changed()

    def changed(self, *_args):
        if self.applying:
            return
        self.serial += 1
        serial = self.serial
        current = self.interface.get_string('gtk-theme')
        base = base_theme(current)
        current_icons = self.interface.get_string('icon-theme')
        icons = base_icons(current_icons)
        if not self.enabled:
            if current != base or current_icons != icons:
                self.apply(base, icons)
            return
        if base not in ('Ambiance', 'Ambiance-Dark', 'Radiance'):
            return
        uri = self.background.get_string('picture-uri')
        file_ = Gio.File.new_for_uri(uri) if uri else None
        path = file_.get_path() if file_ else None
        if self.file_monitor:
            self.file_monitor.cancel()
            self.file_monitor = None
        if path:
            try:
                self.file_monitor = file_.monitor_file(Gio.FileMonitorFlags.NONE, None)
                self.file_monitor.connect('changed', self.changed)
            except GLib.Error:
                pass
        if not path or not os.path.isfile(path):
            self.apply(base, icons)
            return

        brightness = self.brightness

        def generate():
            try:
                with open(os.path.join(HERE, 'config.json')) as stream:
                    config = json.load(stream)
                result = json.loads(subprocess.check_output([config['focusPython'], os.path.join(HERE, 'focus-theme.py'),
                                                base, path, icons, str(brightness)]).decode('utf-8'))
            except Exception as error:
                print('Dynamic focus color: %s' % error)
                result = {'theme': base, 'icons': icons}
            GLib.idle_add(self.ready, serial, result)
        worker = threading.Thread(target=generate)
        worker.daemon = True
        worker.start()

    def ready(self, serial, result):
        if serial == self.serial:
            self.apply(result['theme'], result['icons'])
        return False

    def apply(self, name, icons):
        self.applying = True
        try:
            self.interface.set_string('gtk-theme', name)
            self.interface.set_string('icon-theme', icons)
            # Appearance can leave Ambiance decorations with Ambiance Dark
            # widgets. All shipped variants should follow the accent; retain
            # unrelated custom decoration themes.
            if base_theme(self.wm.get_string('theme')) in ('Ambiance', 'Ambiance-Dark', 'Radiance'):
                self.wm.set_string('theme', name)
        finally:
            self.applying = False

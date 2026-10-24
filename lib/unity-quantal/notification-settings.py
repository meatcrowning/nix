#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
"""Native Notification settings; Notify OSD reloads this preference live."""
import os
from gi.repository import GLib, Gtk

PATH = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'),
                    'unity-quantal', 'notifications.ini')


def main():
    settings = GLib.KeyFile()
    active = False
    try:
        settings.load_from_file(PATH, GLib.KeyFileFlags.NONE)
        active = settings.get_boolean('Notifications', 'click-through')
    except GLib.GError:
        pass
    window = Gtk.Window(title='Notifications')
    window.set_border_width(18)
    window.set_default_size(390, -1)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    toggle = Gtk.CheckButton.new_with_mnemonic('Enable toast click-_through')
    toggle.set_active(active)
    box.pack_start(toggle, False, False, 0)
    description = Gtk.Label(label='Let clicks pass to the window beneath a toast.\nTurn off to open notifications or dismiss them with ×.')
    description.set_alignment(0, .5)
    box.pack_start(description, False, False, 0)

    def save(button):
        settings.set_boolean('Notifications', 'click-through', button.get_active())
        directory = os.path.dirname(PATH)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        data = settings.to_data()[0]
        with open(PATH + '.tmp', 'w') as stream:
            stream.write(data)
        os.rename(PATH + '.tmp', PATH)

    toggle.connect('toggled', save)
    window.add(box)
    window.connect('destroy', Gtk.main_quit)
    window.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()

"""A theme-following profile for the original GNOME Terminal 3.6."""
import subprocess
import threading
from gi.repository import GLib, Gtk

ROOT = '/apps/gnome-terminal'
PROFILE = ROOT + '/profiles/DesktopTheme'


def command(*args):
    return subprocess.check_output(['/usr/bin/gconftool-2'] + list(args)).decode('utf-8').strip()


def save_profile(foreground, background):
    # Initialize before publishing it in the profile list. Leave the user's
    # default and every other profile alone.
    profiles = command('--get', ROOT + '/global/profile_list')
    names = [name.strip() for name in profiles.strip('[]').split(',') if name.strip()] or ['Default']
    for key, kind, value in [('visible_name', 'string', 'Desktop Theme'),
                             ('foreground_color', 'string', foreground),
                             ('background_color', 'string', background),
                             ('use_theme_colors', 'bool', 'false')]:
        command('--type', kind, '--set', PROFILE + '/' + key, value)
    # Ambiance styles VteTerminal aubergine even with use_theme_colors enabled.
    # Explicit colours copied from a native entry bypass that terminal-specific
    # override, while style updates below keep the profile following the theme.
    if 'DesktopTheme' not in names:
        names.append('DesktopTheme')
        command('--type', 'list', '--list-type', 'string', '--set', ROOT + '/global/profile_list',
                '[' + ','.join(names) + ']')


class DesktopThemeProfile(object):
    def __init__(self):
        self.entry = Gtk.Entry()
        self.pending = None
        self.writing = False
        self.dirty = False
        self.entry.connect('style-updated', self.changed)
        Gtk.Settings.get_default().connect('notify::gtk-theme-name', self.changed)
        self.changed()

    def changed(self, *_args):
        self.dirty = True
        if self.pending is None and not self.writing:
            self.pending = GLib.timeout_add(300, self.update)

    def update(self):
        self.pending = None
        self.dirty = False
        style = self.entry.get_style_context()
        def color(value):
            return '#%04x%04x%04x' % tuple(int(round(channel * 65535)) for channel in (value.red, value.green, value.blue))
        foreground = color(style.get_color(Gtk.StateFlags.NORMAL))
        background = color(style.lookup_color('base_color')[1])
        self.writing = True
        def write():
            try:
                save_profile(foreground, background)
            except (OSError, subprocess.CalledProcessError) as error:
                print('Terminal theme profile: %s' % error)
            GLib.idle_add(self.finished)
        worker = threading.Thread(target=write)
        worker.daemon = True
        worker.start()
        return False

    def finished(self):
        self.writing = False
        if self.dirty:
            self.changed()
        return False

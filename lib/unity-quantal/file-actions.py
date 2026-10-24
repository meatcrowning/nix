"""Native handlers for the original Files application's context menu."""
import configparser
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def install(data_home, package, python, config_home):
    # Nautilus-Actions otherwise wraps native file actions in its own submenu.
    preferences = Path(config_home) / 'nautilus-actions/nautilus-actions.conf'
    settings = configparser.ConfigParser(interpolation=None)
    settings.optionxform = str
    settings.read(preferences)
    if not settings.has_section('runtime'):
        settings.add_section('runtime')
    settings['runtime']['items-create-root-menu'] = 'false'
    settings['runtime']['items-add-about-item'] = 'false'
    preferences.parent.mkdir(parents=True, exist_ok=True)
    temporary = preferences.with_suffix('.tmp')
    with temporary.open('w') as stream:
        settings.write(stream)
    temporary.replace(preferences)

    directory = Path(data_home) / 'unity-quantal-session/file-manager/actions'
    directory.mkdir(parents=True, exist_ok=True)
    command = '/usr/local/bin/unity-host-launch -- ' + python + ' ' + str(package / 'libexec/unity-quantal/file-actions.py')
    for key, label, mode, mime, count, icon in [
        ('phone', 'Send to Galaxy Phone', 'phone', '*;!inode/directory;', '>0', 'phone'),
        ('wallpaper', 'Set as Wallpaper', 'wallpaper', 'image/*;', '=1', 'preferences-desktop-wallpaper'),
    ]:
        text = ('[Desktop Entry]\nType=Action\nName=' + label + '\nIcon=' + icon +
                '\nProfiles=default;\nTargetLocation=false\nTargetToolbar=false\n'
                '\n[X-Action-Profile default]\nName=Default\nSchemes=file;\n'
                'MimeTypes=' + mime + '\nSelectionCount=' + count +
                '\nCapabilities=Readable;\nExec=' + command + ' ' + mode + ' %F\n')
        path = directory / ('unity-' + key + '.desktop')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(text)
        temporary.replace(path)


def perform(mode, paths, config, run=subprocess.run):
    if mode == 'browse-phone':
        browse_phone(config, run)
        return
    files = [Path(path).resolve(strict=True) for path in paths]
    if not files or any(not path.is_file() for path in files):
        raise ValueError('Select regular files to use this action.')
    if mode == 'wallpaper':
        if len(files) != 1:
            raise ValueError('Select one image to use as wallpaper.')
        runtime = HERE.parent.parent / 'bin/unity-quantal-runtime'
        # Selecting an image must also turn a disabled wallpaper back on.
        options = run([str(runtime), '/usr/bin/gsettings', 'get', 'org.gnome.desktop.background',
                       'picture-options'], capture_output=True, text=True, check=True, timeout=15)
        if options.stdout.strip() == "'none'":
            run([str(runtime), '/usr/bin/gsettings', 'set', 'org.gnome.desktop.background',
                 'picture-options', 'zoom'], check=True, timeout=15)
        run([str(runtime), '/usr/bin/gsettings', 'set', 'org.gnome.desktop.background',
             'picture-uri', files[0].as_uri()], check=True, timeout=15)
    elif mode == 'phone':
        result = run([config['kdeconnect'], '--list-available', '--id-name-only'],
                     capture_output=True, text=True, check=True, timeout=10)
        devices = [line.split(' ', 1) for line in result.stdout.splitlines() if ' ' in line]
        devices = [(identifier, name) for identifier, name in devices if 'galaxy' in name.lower()]
        if not devices:
            raise ValueError('Your Galaxy phone is not connected. Open KDE Connect on the phone and try again.')
        if len(devices) != 1:
            raise ValueError('More than one Galaxy phone is connected. Choose a device in KDE Connect.')
        for path in files:
            run([config['kdeconnect'], '--device', devices[0][0], '--share', str(path)],
                check=True, timeout=30)
    else:
        raise ValueError('Unknown file action.')


def browse_phone(config, run=subprocess.run, call=None):
    result = run([config['kdeconnect'], '--list-available', '--id-name-only'],
                 capture_output=True, text=True, check=True, timeout=10)
    devices = [line.split(' ', 1) for line in result.stdout.splitlines() if ' ' in line]
    devices = [(identifier, name) for identifier, name in devices if 'galaxy' in name.lower()]
    if len(devices) != 1:
        raise ValueError('Your Galaxy phone is not connected, or more than one is available. '
                         'Open KDE Connect on the phone and try again.')
    identifier = devices[0][0]
    if call is None:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def call(method):
            try:
                return bus.call_sync('org.kde.kdeconnect',
                    '/modules/kdeconnect/devices/' + identifier + '/sftp',
                    'org.kde.kdeconnect.device.sftp', method, None, None,
                    Gio.DBusCallFlags.NONE, 30000, None).unpack()[0]
            except GLib.Error as error:
                raise ValueError('Could not browse the phone. Enable Filesystem expose in '
                                 'KDE Connect on the phone. ' + str(error)) from error

    if not call('mountAndWait'):
        raise ValueError('Could not mount your phone: ' + call('getMountError'))
    mount = Path(call('mountPoint'))
    if not mount.is_absolute() or not mount.is_dir():
        raise ValueError('KDE Connect did not provide an accessible phone folder.')
    run([str(HERE.parent.parent / 'bin/unity-quantal-runtime'),
         '/usr/bin/nautilus', '--no-default-window', mount.as_uri()], check=True, timeout=15)


if __name__ == '__main__':
    config = json.loads((HERE / 'config.json').read_text())
    try:
        perform(sys.argv[1], sys.argv[2:], config)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        subprocess.run([config['zenity'], '--error', '--title=Files', '--text=' + str(error)])
        sys.exit(1)

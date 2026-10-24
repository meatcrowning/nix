#!/usr/bin/python2.7
"""Native WiZ menu; network requests run through Unity's host launcher.

Read the existing tray's literal LIGHTS assignment without importing Qt or
executing user code. Addresses and saved colours remain host-local.
"""
from __future__ import print_function
import ast
import fcntl
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'),
                        'wizlight-tray', 'settings.json')


def read_json(path):
    try:
        with open(path) as stream:
            return json.load(stream)
    except (IOError, ValueError):
        return {}


def write_json(path, data):
    with open(path + '.tmp', 'w') as stream:
        json.dump(data, stream)
    os.rename(path + '.tmp', path)


def lights():
    path = os.path.expanduser('~/.local/bin/wizlight-tray.py')
    try:
        with open(path) as stream:
            tree = ast.parse(stream.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'LIGHTS' for t in node.targets):
                values = ast.literal_eval(node.value)
                return [{'name': str(v['name']), 'ip': str(v['ip'])} for v in values]
    except (IOError, SyntaxError, ValueError, KeyError, TypeError):
        pass
    return []


def call(ip, method, params):
    for _ in range(2):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(1)
            sock.connect((ip, 38899))
            sock.send(json.dumps({'method': method, 'params': params}).encode('utf-8'))
            reply = json.loads(sock.recv(4096).decode('utf-8'))
            result = reply.get('result')
            if isinstance(result, dict) and not reply.get('error'):
                return result
        except (OSError, ValueError):
            pass
        finally:
            sock.close()
    return None


def fetch(report_path, request):
    # Serialize commands and polling; skip a redundant poll while work is active.
    with open(report_path + '.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if not request else 0))
        except OSError:
            return
        settings = read_json(SETTINGS)
        original_settings = json.dumps(settings, sort_keys=True)
        saved = settings.setdefault('lights', {})
        records = []
        for index, light in enumerate(lights()):
            state = call(light['ip'], 'getPilot', {})
            rgb = saved.get(light['ip'], {}).get('rgb', settings.get('rgb', [255, 255, 255]) if index == 0 else [255, 255, 255])
            record = dict(light, online=state is not None, state=False, dimming=10, rgb=rgb)
            if state is not None:
                record.update(state=bool(state.get('state')), dimming=int(state.get('dimming', 10)))
                if state.get('state') and all(k in state for k in ('r', 'g', 'b')):
                    record['rgb'] = [int(state[k]) for k in ('r', 'g', 'b')]
            records.append(record)
        selected = [v for v in records if request.get('target') in ('all', v['ip'])]
        turn_on = not any(v['state'] for v in selected)
        error = ''
        for record in selected:
            if not record['online']:
                error = 'A light is unavailable'
                continue
            action = request.get('action')
            params = {}
            if action == 'toggle':
                params = {'state': turn_on}
            elif action == 'brightness':
                params = {'state': True, 'dimming': max(10, min(100, record['dimming'] + int(request['value'])))}
            elif action == 'color':
                record['rgb'] = [max(0, min(255, int(v))) for v in request['value']]
                if record['state']:
                    params = {'state': True}
            if params.get('state'):
                params.setdefault('dimming', record['dimming'])
                params.update(dict(zip(('r', 'g', 'b'), record['rgb'])))
            if params:
                result = call(record['ip'], 'setPilot', params)
                if result is None or result.get('success') is False:
                    error = 'A light did not accept the change'
                else:
                    record.update(params)
        for record in records:
            saved.setdefault(record['ip'], {})['rgb'] = record['rgb']
        if records and json.dumps(settings, sort_keys=True) != original_settings:
            directory = os.path.dirname(SETTINGS)
            if not os.path.isdir(directory):
                os.makedirs(directory)
            write_json(SETTINGS, settings)
        write_json(report_path, {'time': time.time(), 'lights': records, 'error': error})


def indicator():
    from gi.repository import AppIndicator3, Gio, GLib, GObject, Gtk, Gdk
    host_python = read_json(os.path.join(HERE, 'config.json'))['python']
    report_path = os.path.join(os.environ['UNITY_QUANTAL_SESSION_DIR'], 'wizlights.json')

    class Indicator(Gtk.Application):
        def __init__(self):
            Gtk.Application.__init__(self, application_id='org.unity_quantal.Wizlights',
                                     flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.started = False
            self.records = []
            self.rows = {}
            self.dialogs = {}
            self.updating = False
            self.stamp = None
            self.requested = 0

        def do_activate(self):
            if self.started:
                return
            self.started = True
            self.hold()
            self.indicator = AppIndicator3.Indicator.new('unity-quantal-wizlights',
                os.path.join(HERE, 'display-icons/unity-wizlights-off.svg'),
                AppIndicator3.IndicatorCategory.HARDWARE)
            self.indicator.set_title('WiZ Lights')
            self.menu = Gtk.Menu()
            self.indicator.set_menu(self.menu)
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.build()
            self.tick()
            GLib.timeout_add_seconds(1, self.tick)

        def add(self, menu, label, callback=None):
            row = Gtk.MenuItem(label)
            if callback:
                row.connect('activate', callback)
            else:
                row.set_sensitive(False)
            menu.append(row)
            return row

        def controls(self, menu, target):
            if target == 'all':
                self.add(menu, 'Toggle All', lambda *_: self.request(target, 'toggle'))
            else:
                row = Gtk.CheckMenuItem('On')
                row.connect('activate', lambda *_: None if self.updating else self.request(target, 'toggle'))
                menu.append(row)
                self.rows[target] = row
            self.add(menu, 'Increase Brightness (+5%)', lambda *_: self.request(target, 'brightness', 5))
            self.add(menu, 'Decrease Brightness (-5%)', lambda *_: self.request(target, 'brightness', -5))
            self.add(menu, 'Choose Color...', lambda *_: self.color(target))

        def build(self):
            for child in self.menu.get_children():
                self.menu.remove(child)
                child.destroy()
            self.rows = {}
            self.add(self.menu, 'All Lights')
            self.controls(self.menu, 'all')
            for record in self.records:
                self.menu.append(Gtk.SeparatorMenuItem())
                row = Gtk.MenuItem(record['name'])
                submenu = Gtk.Menu()
                row.set_submenu(submenu)
                self.menu.append(row)
                self.controls(submenu, record['ip'])
            self.menu.append(Gtk.SeparatorMenuItem())
            self.status = self.add(self.menu, 'Connecting to lights...')
            self.menu.show_all()

        def request(self, target=None, action=None, value=None):
            self.requested = time.time()
            request = {'target': target, 'action': action, 'value': value} if action else {}
            subprocess.Popen(['/usr/local/bin/unity-host-launch', '--', host_python,
                              os.path.abspath(__file__), 'fetch', report_path, json.dumps(request)])

        def tick(self):
            report = read_json(report_path)
            if report.get('time') != self.stamp:
                self.stamp = report.get('time')
                records = report.get('lights', [])
                changed = [(v['ip'], v['name']) for v in records] != [(v['ip'], v['name']) for v in self.records]
                self.records = records
                if changed:
                    self.build()
                self.updating = True
                for record in records:
                    row = self.rows[record['ip']]
                    row.set_active(record['state'])
                    row.set_label('On (%d%%)' % record['dimming'] if record['online'] else 'Unavailable')
                self.updating = False
                on = any(v['state'] and v['online'] for v in records)
                self.indicator.set_icon(os.path.join(HERE, 'display-icons/unity-wizlights-%s.svg' % ('on' if on else 'off')))
                self.status.set_label(report.get('error') or ('No lights configured' if not records else
                    'Some lights are unavailable' if any(not v['online'] for v in records) else 'WiZ Lights'))
            if time.time() - self.requested >= 3:
                self.request()
            return True

        def color(self, target):
            if target in self.dialogs:
                self.dialogs[target].present()
                return
            record = next((v for v in self.records if target in ('all', v['ip'])), None)
            if record is None:
                return
            dialog = Gtk.ColorSelectionDialog(('All Lights' if target == 'all' else record['name']) + ' Color')
            self.dialogs[target] = dialog
            selection = dialog.get_color_selection()
            selection.set_has_opacity_control(False)
            rgb = record['rgb']
            selection.set_current_color(Gdk.Color(*[int(v) * 257 for v in rgb]))

            def respond(_dialog, response):
                if response == Gtk.ResponseType.OK:
                    color = selection.get_current_color()
                    self.request(target, 'color', [color.red // 257, color.green // 257, color.blue // 257])
                del self.dialogs[target]
                dialog.destroy()
            dialog.connect('response', respond)
            dialog.show()

    GLib.set_prgname('unity-wizlights')
    GObject.threads_init()
    return Indicator().run(sys.argv[:1])


if __name__ == '__main__':
    if sys.argv[1:2] == ['fetch'] and len(sys.argv) == 4:
        fetch(sys.argv[2], json.loads(sys.argv[3]))
    elif sys.argv[1:] == ['indicator']:
        sys.exit(indicator())
    else:
        raise SystemExit('usage: wizlights.py indicator | fetch REPORT REQUEST')

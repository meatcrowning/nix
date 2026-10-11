#!/usr/bin/python2.7
"""Load, temperature and recent-notification menus in Quantal's panel runtime."""
from __future__ import division, print_function
import csv
import glob
import json
import os
import re
import subprocess
import sys
import textwrap
import time


def read(path):
    try:
        with open(path) as stream:
            return stream.read().strip()
    except IOError:
        return ''


def gpu_fetch(path):
    # Run through the host launcher: NVIDIA's current libraries cannot be
    # loaded inside the original GTK runtime. Bound each read to one second.
    report = {'time': time.time()}
    try:
        output = subprocess.check_output(['nvidia-smi',
            '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu',
            '--format=csv,noheader,nounits'], timeout=1, stderr=subprocess.DEVNULL).decode()
        values = next(csv.reader(output.splitlines(), skipinitialspace=True))
        report.update(name=values[0], usage=float(values[1]), used=float(values[2]),
                      total=float(values[3]), temperature=float(values[4]))
    except (OSError, subprocess.SubprocessError, ValueError, StopIteration, IndexError):
        # DRM drivers with a utilization counter need no external utility.
        for device in sorted(glob.glob('/sys/class/drm/card[0-9]*/device')):
            try:
                usage = float(read(device + '/gpu_busy_percent'))
                used = float(read(device + '/mem_info_vram_used')) / 1048576
                total = float(read(device + '/mem_info_vram_total')) / 1048576
            except ValueError:
                continue
            report.update(name='GPU', usage=usage, used=used, total=total)
            break
    temporary = path + '.tmp'
    with open(temporary, 'w') as stream:
        json.dump(report, stream)
    os.replace(temporary, path)


def cpu_sample():
    values = [int(v) for v in read('/proc/stat').splitlines()[0].split()[1:9]]
    return sum(values), sum(values[3:5])


def counters():
    network = [line.split(':', 1)[1].split() for line in read('/proc/net/dev').splitlines()[2:]
               if ':' in line and line.split(':', 1)[0].strip() != 'lo']
    receive, send = sum(int(v[0]) for v in network), sum(int(v[8]) for v in network)
    # Whole devices only; partitions would count every operation twice.
    disks = [line.split() for line in read('/proc/diskstats').splitlines()]
    disks = [v for v in disks if os.path.exists('/sys/block/' + v[2])
             and not v[2].startswith(('loop', 'ram', 'dm-'))]
    return receive, send, sum(int(v[5]) * 512 for v in disks), sum(int(v[9]) * 512 for v in disks)


def temperatures():
    result = []
    for path in sorted(glob.glob('/sys/class/hwmon/hwmon*/temp*_input')):
        value = read(path)
        if not value:
            continue
        try:
            degrees = int(value) / 1000
        except ValueError:
            continue
        if not -20 <= degrees <= 150:
            continue
        chip = read(os.path.dirname(path) + '/name') or 'Sensor'
        label = read(path.replace('_input', '_label')) or os.path.basename(path).replace('_input', '')
        result.append((chip + ': ' + label, degrees))
    if not result:
        for path in sorted(glob.glob('/sys/class/thermal/thermal_zone*/temp')):
            try:
                result.append((read(os.path.dirname(path) + '/type') or 'Temperature', int(read(path)) / 1000))
            except ValueError:
                continue
    return result


def item(menu, text):
    row = Gtk.MenuItem(label=text)
    row.set_sensitive(False)
    menu.append(row)
    return row


def rate(value):
    for unit in ('B/s', 'KiB/s', 'MiB/s', 'GiB/s'):
        if value < 1024 or unit == 'GiB/s':
            return '%.1f %s' % (value, unit)
        value /= 1024


class Indicator:
    def __init__(self, kind):
        self.kind = kind
        icon, title = {'load': ('utilities-system-monitor', 'System Load'),
                       'gpu': ('utilities-system-monitor', 'GPU Load'),
                       'temperature': (os.path.join(os.path.dirname(__file__), 'display-icons/unity-temperature.svg'), 'Temperatures'),
                       'notifications': ('indicator-messages', 'Recent Notifications')}[kind]
        self.indicator = AppIndicator3.Indicator.new('unity-quantal-' + kind, icon,
                                                   AppIndicator3.IndicatorCategory.SYSTEM_SERVICES)
        self.indicator.set_title(title)
        if kind in ('load', 'gpu'):
            # Quantal sorts descending after integer division by two.
            self.indicator.set_ordering_index(100002 if kind == 'load' else 100000)
        self.menu = Gtk.Menu()
        self.indicator.set_menu(self.menu)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.PASSIVE if kind == 'notifications'
                                  else AppIndicator3.IndicatorStatus.ACTIVE)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        Gio.bus_own_name_on_connection(self.bus, 'org.unity_quantal.' +
            {'load': 'Load', 'gpu': 'Gpu', 'temperature': 'Temperature', 'notifications': 'NotificationIndicator'}[kind],
            Gio.BusNameOwnerFlags.NONE, None, None)
        self.previous_cpu = cpu_sample() if kind == 'load' else None
        self.previous_io = counters() if kind == 'load' else None
        self.previous_time = time.time()
        self.fingerprint = None
        self.samples = []
        self.serial = 0
        self.update()
        if kind == 'load':
            from cpufreq import PowerMenu
            self.power = PowerMenu(self.menu)
        GLib.timeout_add_seconds(2, self.update)

    def replace(self):
        for child in self.menu.get_children():
            self.menu.remove(child)
            child.destroy()

    def rows(self, labels):
        # Preserve menu item IDs while readings change, including when the
        # user has the menu open. Rebuild only if sensor topology changes.
        children = self.menu.get_children()
        if self.kind == 'load' and hasattr(self, 'power'):
            children = children[:8]
        if len(children) != len(labels):
            self.replace()
            for label in labels:
                item(self.menu, label)
        else:
            for child, label in zip(children, labels):
                if child.get_label() != label:
                    child.set_label(label)

    def update(self):
        if self.kind == 'load':
            total, idle = cpu_sample()
            old_total, old_idle = self.previous_cpu
            cpu = 100 * (1 - (idle - old_idle) / (total - old_total)) if total > old_total else 0
            self.previous_cpu = total, idle
            memory = dict((line.split(':')[0], int(line.split()[1]))
                          for line in read('/proc/meminfo').splitlines())
            used = memory['MemTotal'] - memory.get('MemAvailable', memory['MemFree'] + memory['Cached'] + memory['Buffers'])
            io, now = counters(), time.time()
            speed = [max(0, new - old) / max(.1, now - self.previous_time) for new, old in zip(io, self.previous_io)]
            self.previous_io, self.previous_time = io, now
            self.indicator.set_label('%.0f%%' % cpu, '100%')
            self.graph(cpu, 100 * used / memory['MemTotal'])
            self.rows(['CPU: %.0f%%' % cpu,
                'Memory: %.1f / %.1f GiB' % (used / 1048576, memory['MemTotal'] / 1048576),
                'Network receive: ' + rate(speed[0]), 'Network send: ' + rate(speed[1]),
                'Disk read: ' + rate(speed[2]), 'Disk write: ' + rate(speed[3]),
                'Load average: ' + ' / '.join(read('/proc/loadavg').split()[:3]),
                'Graph: CPU solid, memory dotted (last 80 seconds)'])
        elif self.kind == 'gpu':
            path = os.path.join(os.environ['UNITY_QUANTAL_SESSION_DIR'], 'gpu.json')
            try:
                report = json.loads(read(path) or '{}')
            except ValueError:
                report = {}
            if 'usage' in report and time.time() - report.get('time', 0) < 10:
                usage, used, total = report['usage'], report['used'], report['total']
                self.indicator.set_label('%.0f%%' % usage, '100%')
                self.graph(usage, 100 * used / total if total else 0)
                self.rows([report['name'], 'GPU: %.0f%%' % usage,
                    'VRAM: %.1f / %.1f GiB' % (used / 1024, total / 1024),
                    ('Temperature: %.0f C' % report['temperature']) if 'temperature' in report else 'Temperature: unavailable',
                    'Graph: GPU solid, VRAM dotted (last 80 seconds)'])
            else:
                self.indicator.set_label('--', '100%')
                self.samples = []
                self.rows(['GPU readings unavailable'])
            config = json.loads(read(os.path.join(os.path.dirname(__file__), 'config.json')))
            subprocess.Popen(['/usr/local/bin/unity-host-launch', '--', config['python'],
                              os.path.abspath(__file__), 'gpu-fetch', path])
        elif self.kind == 'temperature':
            values = temperatures()
            # Panel shows the CPU die temperature; an unconnected board
            # thermistor can read hot and would otherwise win a plain max().
            cpu = [v for label, v in values if label in ('k10temp: Tctl', 'coretemp: Package id 0')]
            shown = cpu or [v for _, v in values]
            self.indicator.set_label((u'%.0f\u00b0C' % max(shown)) if shown else '--', '100 C')
            self.rows([u'%s: %.1f\u00b0C' % (label, value) for label, value in values]
                      or ['No temperature sensors available'])
        else:
            # Entries are session-local, bounded and cleared by the owning
            # notification service; no second daemon intercepts notifications.
            path = os.path.join(os.environ['UNITY_QUANTAL_SESSION_DIR'], 'notification-history.json')
            text = read(path)
            if text == self.fingerprint:
                return True
            self.fingerprint = text
            try:
                entries = json.loads(text) if text else []
            except ValueError:
                entries = []
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE if entries
                                      else AppIndicator3.IndicatorStatus.PASSIVE)
            self.indicator.set_label(str(len(entries)) if entries else '', '30')
            self.replace()
            if not entries:
                item(self.menu, 'No recent notifications')
            for entry in reversed(entries):
                title = u'%s  %s: %s' % (time.strftime('%H:%M', time.localtime(entry['time'])), entry['app'], entry['summary'])
                row = Gtk.MenuItem(label=title[:140])
                submenu = Gtk.Menu()
                body = re.sub('<[^>]*>', '', entry['body'])
                for line in textwrap.wrap(body, 65) or [entry['summary']]:
                    item(submenu, line)
                row.set_submenu(submenu)
                self.menu.append(row)
            self.menu.append(Gtk.SeparatorMenuItem())
            clear = Gtk.MenuItem(label='Clear History')
            clear.connect('activate', self.clear)
            clear.set_sensitive(bool(entries))
            self.menu.append(clear)
        self.menu.show_all()
        if self.kind == 'load' and hasattr(self, 'power'):
            self.power.show_profile()
        return True

    def graph(self, cpu, memory):
        self.samples = (self.samples + [(cpu, memory)])[-40:]
        directory = os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), self.kind + '-meter')
        if not os.path.isdir(directory):
            os.makedirs(directory)
        self.serial += 1
        path = os.path.join(directory, (self.kind + '-%d.svg') % self.serial)
        lines = []
        for series, style in [(0, ''), (1, ' stroke-dasharray="1 2"')]:
            points = ' '.join('%.1f,%.1f' % (i + 40 - len(self.samples), 20 - max(0, min(100, v[series])) * .18)
                              for i, v in enumerate(self.samples))
            lines.append('<polyline points="%s" fill="none" stroke="#dfdbd2" stroke-width="1.5"%s/>' % (points, style))
        with open(path, 'w') as stream:
            stream.write('<svg xmlns="http://www.w3.org/2000/svg" width="42" height="22">' + ''.join(lines) + '</svg>')
        self.indicator.set_icon(path)
        # Keep the current image and two predecessors while the panel reads it.
        old = os.path.join(directory, (self.kind + '-%d.svg') % (self.serial - 3))
        if os.path.isfile(old):
            os.unlink(old)

    def clear(self, *_):
        self.bus.call('org.freedesktop.Notifications', '/org/unity_quantal/NotificationHistory',
            'org.unity_quantal.NotificationHistory', 'Clear', None, None, Gio.DBusCallFlags.NONE, 2000, None, None, None)


if __name__ == '__main__':
    if sys.argv[1] == 'gpu-fetch':
        gpu_fetch(sys.argv[2])
    else:
        from gi.repository import AppIndicator3, Gio, GLib, Gtk
        indicator = Indicator(sys.argv[1])
        Gtk.main()

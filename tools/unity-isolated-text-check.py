"""Exercise worker settings with original GTK on a private display, without audio."""
import json
import os
from pathlib import Path
import subprocess

assert os.environ['HOME'] == '/home/test' and Path('/work/inside.sh').is_file()
run = Path('/work/text')
run.mkdir()
for name in ['input', 'output', 'transport']:
    (run / name).mkdir()
(run / 'passwd').write_text(f'legacy:x:{os.getuid()}:{os.getgid()}:Legacy:/home/legacy:/bin/sh\n')
(run / 'group').write_text(f'legacy:x:{os.getgid()}:legacy\n')
(run / 'machine-id').write_text('a' * 32 + '\n')
(run / 'transport/text-settings').write_text(json.dumps({
    'antialiasing': 'rgba', 'hinting': 'slight', 'rgba-order': 'rgb'}))
m.media_paths()[0].mkdir(parents=True, exist_ok=True)
# This is the original Python/GTK stack used by Rhythmbox, launched by worker().
probe = '''
from gi.repository import Gtk, Pango
import sys
settings = Gtk.Settings.get_default()
window = Gtk.OffscreenWindow()
label = Gtk.Label('Historical Ubuntu text: Rhythmbox 12.10')
label.override_font(Pango.FontDescription('Ubuntu 11'))
window.add(label)
window.show_all()
while Gtk.events_pending(): Gtk.main_iteration()
window.get_pixbuf().savev('/transport/' + sys.argv[1] + '.png', 'png', [], [])
with open('/transport/' + sys.argv[1] + '.json', 'w') as stream:
    import json
    json.dump({k: settings.get_property(k) for k in
        ['gtk-xft-antialias', 'gtk-xft-hinting', 'gtk-xft-hintstyle', 'gtk-xft-rgba']}, stream)
'''
(run / 'transport/probe.py').write_text(probe)
script = '''
import os, sys, subprocess, time
from pathlib import Path
sys.path.insert(0, '/runner')
import isolated as m
server = subprocess.Popen([m.CONFIG['xvfb'], ':94', '-screen', '0', '800x600x24', '-nolisten', 'tcp', '-ac', '-noreset'])
try:
    for _ in range(100):
        if Path('/tmp/.X11-unix/X94').exists(): break
        if server.poll() is not None: raise RuntimeError('private X server failed')
        time.sleep(.05)
    else: raise RuntimeError('private X server did not start')
    os.environ['DISPLAY'] = ':94'
    original = subprocess.call
    captured = []
    def render(command, **kwargs):
        command = [s for s in command if not s.startswith('GTK_MODULES=')]
        command[-4:] = ['/usr/bin/python', '/transport/probe.py', 'fixed']
        captured.append((command, kwargs))
        return original(command, **kwargs)
    subprocess.call = render
    try: m.worker('rhythmbox', [])
    except SystemExit as error: assert error.code == 0
    # Reproduce the previous worker's missing Xft settings on the same stack.
    settings = Path.home() / '.config/gtk-3.0/settings.ini'
    settings.write_text('\\n'.join(line for line in settings.read_text().splitlines()
                                  if not line.startswith('gtk-xft-')) + '\\n')
    subprocess.run([m.CONFIG['xrdb'], '-remove'], env={'DISPLAY': ':94'}, check=True)
    command, kwargs = captured[0]
    command[-1] = 'before'
    assert original(command, **kwargs) == 0
finally:
    server.terminate()
    server.wait(timeout=5)
'''
subprocess.run(m.base_namespace(run, app='rhythmbox') + [m.CONFIG['python'], '-c', script], check=True)
fixed = json.loads((run / 'transport/fixed.json').read_text())
before = json.loads((run / 'transport/before.json').read_text())
assert fixed == {'gtk-xft-antialias': 1, 'gtk-xft-hinting': 1,
                 'gtk-xft-hintstyle': 'hintslight', 'gtk-xft-rgba': 'rgb'}, fixed
assert before != fixed, (before, fixed)
assert (run / 'transport/fixed.png').read_bytes() != (run / 'transport/before.png').read_bytes()
print('PASS: isolated original GTK applies Unity subpixel/hinting settings and changes rendered text', flush=True)

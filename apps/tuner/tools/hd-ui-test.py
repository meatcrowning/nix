#!/usr/bin/env python3
"""Run only inside the private Xvfb harness with a scratch HOME/config."""
import os
import sys
import time
from pathlib import Path

assert os.environ.get('TUNER_ISOLATED_UI') == '1', 'Use hd-ui-test.sh'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main as m

m.rtl.devices = lambda: []
m.audio.output_devices = lambda: []
app = m.Gtk.Application(application_id='org.test.tunerhd'); app.register(None)
path = Path(os.environ['XDG_CONFIG_HOME']) / 'hd-test.json'
w = m.TunerWindow(app, str(path), False)

def settle():
    for _ in range(5):
        while m.Gtk.events_pending(): m.Gtk.main_iteration_do(False)
        time.sleep(.01)

settle()
assert not w.hd_combo.get_visible()
w.hd_button.set_active(True); settle()
assert w.s['hd'] and w.hd_combo.get_visible()
assert not w.rate_combo.get_sensitive() and not w.receiver_page.get_sensitive()
assert w.rds_display.get_visible() and w.dial.get_mapped()
w.rds_button.set_active(False); settle()
assert not w.rds_display.get_visible() and w.dial.get_mapped()
w.rds_button.set_active(True); settle()
assert w.rds_display.get_mapped() and w.dial.get_mapped()
assert len(w.dial.boxes) == w.dial.DIGITS
assert w.dial.boxes[0][0] >= 0
assert w.dial.boxes[-1][1] < w.dial.get_allocated_width()
assert w.rds_button.get_label() == 'Text'
w.radio.running = True; w.radio.hd_enabled = True
w._refresh_rds(); assert w.rds_display.text == 'Searching for HD Radio'
gen = w.radio.metadata_generation
state = dict(program=0, station='TEST-FM', channels=[0, 1], locked=True, audio=True,
             artist='ARTIST', title='SONG')
w._hd_update(gen, state)
assert w.rds_display.text == 'ARTIST - SONG'
assert w.hd_combo.get_sensitive()
w._sync_hd_channels([1]); assert w.hd_combo.get_sensitive()
w.hd_combo.set_active_id('1')
assert w.radio.hd_program == 1 and 'SONG' not in w.rds_display.text
w._hd_update(gen, state); assert 'SONG' not in w.rds_display.text
state.update(program=1, title='HD2 SONG')
w._hd_update(gen, state); assert 'HD2 SONG' in w.rds_display.text
w.tune(102700000)
assert w.dial.value == 102700000 and w.dial.get_mapped()
assert w.radio.hd_program == 0 and w.hd_data == {}
w._hd_update(gen, state); assert 'HD2 SONG' not in w.rds_display.text
state.update(program=0, locked=False)
w._hd_update(w.radio.metadata_generation, state)
assert w.rds_display.text == 'HD signal lost'
w.radio.running = False
w._stopped()
w._write_settings()
w.destroy(); settle()
w = m.TunerWindow(app, str(path), False)
assert w.s['hd'] and w.hd_button.get_active() and w.hd_combo.get_visible()
w.hd_button.set_active(False)
assert w.receiver_page.get_sensitive() and w.rate_combo.get_sensitive()
assert not w.hd_combo.get_visible()
# The toggle requests one orderly stop; callback restarts only after release.
w.radio.running = True
calls = []
w.radio.stop = lambda: (calls.append('stop'), setattr(w.radio, 'running', False))
w.radio.start = lambda hw: calls.append(('start', hw['hd']))
w.start_button.set_active(True)
w.hd_button.set_active(True)
assert calls == ['stop'] and w.hd_restart
w._stopped()
assert calls == ['stop', ('start', True)] and not w.hd_restart
# Unlit segments use neutral charcoal and fixed cell positions.
from rdsview import RdsDisplay
class Canvas:
    def __init__(self): self.colors = []
    def set_source_rgb(self, *rgb): self.colors.append(rgb)
    def set_source_rgba(self, *rgba): self.colors.append(rgba)
    def __getattr__(self, name): return lambda *a: None
c = Canvas(); RdsDisplay._glyph(c, ' ', 0, 0, 20, 40)
assert c.colors and all(rgb == (.13, .13, .13) for rgb in c.colors)
w.destroy(); settle()
print('PASS HD controls, metadata isolation, subchannels, tune, loss, persistence, orderly restart, grey segments')

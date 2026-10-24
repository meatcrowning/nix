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
# Old hidden-text preferences must not suppress the permanent readout.
path.write_text('{"rds_display": false}')
w = m.TunerWindow(app, str(path), False)

def settle():
    for _ in range(5):
        while m.Gtk.events_pending(): m.Gtk.main_iteration_do(False)
        time.sleep(.01)

settle()
assert not w.hd_combo.get_visible()
assert w.rds_display.get_visible() and w.dial.get_visible()
w.hd_item.set_active(True); settle()
assert w.s['hd'] and w.hd_combo.get_visible()
assert not w.rate_combo.get_sensitive() and not w.receiver_page.get_sensitive()
assert w.rds_display.get_visible() and w.dial.get_mapped()
assert w.rds_display.get_mapped() and w.dial.get_mapped()
places = [box[2] for box in w.dial.boxes]
assert places == list(range(places[0], places[-1] - 1, -1)) and 6 in places and 5 in places
assert w.dial.boxes[0][0] >= 0
assert w.dial.boxes[-1][1] < w.dial.get_allocated_width()
assert not hasattr(w, 'rds_button') and not hasattr(w, 'hd_button')
# The face's popup menus resolve to the actual segment font.
from gi.repository import Gdk, Pango
font = w.get_pango_context().load_font(Pango.FontDescription('Tuner Segment 14'))
assert font.describe().get_family() == 'Tuner Segment', font.describe().to_string()
# One grid, three rows: every drawn control drives the state it shows.
f = w.face
f.born -= 5  # past the power-on sweep
now = time.monotonic(); f._compose(now)
zones = {z['name']: z for z in f.zones}
assert {'start', 'record', 'mute', 'gain', 'mode', 'step', 'signal', 'go', 'freq', 'station'} <= set(zones), zones
assert {z['row'] for z in f.zones} == {0, 1, 2}
muted = w.mute_button.get_active()
f._activate('mute', zones['mute']); assert w.mute_button.get_active() != muted
f._activate('mute', zones['mute']); assert w.mute_button.get_active() == muted
gain = w.volume.get_value(); f._adjust('gain', -1); assert w.volume.get_value() == gain - 1
f._adjust('gain', 1)
step = w.step_combo.get_active(); f._adjust('step', -1); assert w.step_combo.get_active() == step - 1
f._adjust('step', 1)
f._activate('step', zones['step']); settle()
items = f.menu.get_children()
assert len(items) == len(w.step_combo.get_model()) and items[step].get_active()
items[step - 1].activate(); assert w.step_combo.get_active() == step - 1
f.menu.popdown(); f._adjust('step', 1)
# Meters are built from the cells' own uprights, never from other shapes.
f.level.set_value(50); f._ballistics(time.monotonic()); f._compose(time.monotonic())
meter = [f.cells.get((1, zones['signal']['col'] + i), ('',))[0] for i in range(zones['signal']['width'])]
assert any(meter) and all(set(cell) <= set('efjmbc') for cell in meter), meter
f.level.set_value(0)
# Station text keeps scrolling even when it fits.
f.set_message('RDS', 'SHORT'); f.since -= 5
assert not f._marquee(30, time.monotonic(), True).startswith('SHORT')
assert f._marquee(30, time.monotonic(), False).startswith('SHORT')
w.radio.running = True; w.radio.hd_enabled = True
w._refresh_rds(); assert w.rds_display.text == 'Searching for HD Radio'
gen = w.radio.metadata_generation
state = dict(program=0, station='TEST-FM', channels=[0, 1], locked=True, audio=True,
             artist='ARTIST', title='SONG')
w._hd_update(gen, state)
assert w.rds_display.text == 'ARTIST - SONG'
assert w.hd_combo.get_sensitive()
if os.environ.get('TUNER_UI_SHOT'):
    import cairo
    settle()
    f.level.set_value(62); f.peak = 75; f.peak_at = time.monotonic()
    f.band_targets = [.2, .7, .9, .5, .3, .8, .6, .2, .1, .4, .7, .3]; f.band_at = time.monotonic()
    f._ballistics(time.monotonic())
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w.get_allocated_width(), w.get_allocated_height())
    w.draw(cairo.Context(surface))
    surface.write_to_png(os.environ['TUNER_UI_SHOT'])
w._sync_hd_channels([1]); assert w.hd_combo.get_sensitive()
w.hd_combo.set_active_id('1')
assert w.radio.hd_program == 1 and 'SONG' not in w.rds_display.text
w._hd_update(gen, state); assert 'SONG' not in w.rds_display.text
state.update(program=1, title='HD2 SONG')
w._hd_update(gen, state); assert 'HD2 SONG' in w.rds_display.text
w.tune(102700000)
assert w.dial.value == 102700000 and w.dial.get_mapped()
settle(); f._compose(time.monotonic()); assert [box[2] for box in w.dial.boxes] == [8, 7, 6, 5, 4]
# Typing on the face tunes directly.
class Key:
    def __init__(self, keyval): self.keyval = keyval
f._activate('go', zones['go'])
for ch in '101.1':
    f._edit_key(Key(Gdk.unicode_to_keyval(ord(ch))))
f._edit_key(Key(Gdk.KEY_Return))
assert w.s['frequency'] == 101100000 and f.editing is None
w.tune(102700000)
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
assert w.s['hd'] and w.hd_item.get_active() and w.hd_combo.get_visible()
w.hd_item.set_active(False)
assert w.receiver_page.get_sensitive() and w.rate_combo.get_sensitive()
assert not w.hd_combo.get_visible()
# The toggle requests one orderly stop; callback restarts only after release.
w.radio.running = True
calls = []
w.radio.stop = lambda: (calls.append('stop'), setattr(w.radio, 'running', False))
w.radio.start = lambda hw: calls.append(('start', hw['hd']))
w.start_button.set_active(True)
w.hd_item.set_active(True)
assert calls == ['stop'] and w.hd_restart
w._stopped()
assert calls == ['stop', ('start', True)] and not w.hd_restart
# Unlit segments use neutral charcoal and fixed cell positions.
import rdsview
class Canvas:
    def __init__(self): self.colors = []
    def set_source_rgb(self, *rgb): self.colors.append(rgb)
    def set_source_rgba(self, *rgba): self.colors.append(rgba)
    def __getattr__(self, name): return lambda *a: None
c = Canvas(); rdsview.glyph(c, ' ', 0, 0, 20, 40)
assert c.colors and all(rgb == (.13, .13, .13) for rgb in c.colors)
# Lit segments take the theme's selection colour; the readout drops dead zeros.
import faceplate, views
found, accent = w.get_style_context().lookup_color('theme_selected_bg_color')
assert not found or faceplate.LIT == (accent.red, accent.green, accent.blue), faceplate.LIT
c = Canvas(); rdsview.glyph(c, '8', 0, 0, 20, 40)
assert any(rgba[:3] == faceplate.LIT for rgba in c.colors)
assert [views.mhz_text(f) for f in (96900000, 96000000, 1234567, 102710000)] == \
    ['96.9', '96.0', '1.234567', '102.71']
w.destroy(); settle()
print('PASS HD controls, metadata isolation, subchannels, tune, loss, persistence, orderly restart, grey segments')

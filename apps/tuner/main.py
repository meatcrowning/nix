#!/usr/bin/env python3
"""tuner — a GTK 3 receiver for the RTL-SDR dongle, made for the Unity session.

It shares gqrx's bookmarks file and seeds its first settings from gqrx's
default.conf, then keeps its own in ~/.config/tuner/settings.json.

    tuner [--no-start] [--settings PATH]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GLib, GObject, Gtk  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import audio  # noqa: E402
import dsp  # noqa: E402
import gqrxfiles  # noqa: E402
import radio  # noqa: E402
import online  # noqa: E402
import rtl  # noqa: E402
from views import COLOUR_MAPS, DISPLAY_DEFAULTS, FrequencyDial, SpectrumView, mhz_text  # noqa: E402
from faceplate import SegmentMeter, SegmentScale, style_faceplate  # noqa: E402
from rdsview import RdsDisplay  # noqa: E402

APP_ID = "tuner"
SETTINGS = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tuner/settings.json"

STEPS = [10, 100, 500, 1000, 2500, 5000, 6250, 9000, 10000, 12500, 25000, 50000, 100000, 200000]
MODE_STEP = {"AM": 5000, "AM-Sync": 5000, "Narrow FM": 12500, "WFM (mono)": 100000,
             "WFM (stereo)": 100000, "LSB": 100, "USB": 100, "CW-L": 10, "CW-U": 10}
ZOOMS = [1, 2, 4, 8, 16]
SHORT_MODES = {"WFM (stereo)": "WFM", "WFM (mono)": "WFM mono", "Narrow FM": "NFM"}

HW_DEFAULTS = {"frequency": 96900000, "sample_rate": 1920000, "gain_db": None, "rtl_agc": False,
               "ppm": 0, "bias_tee": False, "device": 0, "hd": False}
OTHER_DEFAULTS = {"output": None, "udp_enabled": False, "udp_host": "localhost", "udp_port": 7355,
                  "udp_stereo": False, "rec_dir": str(Path.home()), "step": 100000, "zoom": 1,
                  "peak_hold": True, "auto_range": True, "floor_db": -80.0, "range_db": 60.0,
                  "start_on_launch": True, "tag_filter": "", "window": [1180, 760], "pane": 0,
                  "tab": 0, "bookmark_columns": []}


def step_label(step):
    if step >= 1000:
        return ("%g kHz" % (step / 1000))
    return "%d Hz" % step


def load_settings(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        data = None
    settings = dict(HW_DEFAULTS)
    settings.update(OTHER_DEFAULTS)
    settings.update(DISPLAY_DEFAULTS)
    rx = dict(dsp.Receiver.DEFAULTS)
    if data is None:
        seed = gqrxfiles.read_gqrx_settings()
        for key in ("frequency", "gain_db", "ppm", "udp_host", "udp_port", "rec_dir"):
            if key in seed:
                settings[key] = seed[key]
        if "sample_rate" in seed:
            settings["sample_rate"] = radio.nearest_rate(seed["sample_rate"])
        for key in ("mode", "filter_low", "filter_high", "agc_decay_ms", "squelch_db", "volume_db"):
            if key in seed:
                rx[key] = seed[key]
        rx["mode"] = dsp.canonical_mode(rx["mode"])
        rx["filter_width"] = "User"
        for name in ("Wide", "Normal", "Narrow"):
            if dsp.filter_for(rx["mode"], name) == (rx["filter_low"], rx["filter_high"]):
                rx["filter_width"] = name
        settings["step"] = MODE_STEP[rx["mode"]]
    else:
        settings.update({k: v for k, v in data.items() if k in settings})
        rx.update({k: v for k, v in data.get("receiver", {}).items() if k in rx})
    rx["offset"] = 0.0
    settings["receiver"] = rx
    return settings


class TunerWindow(Gtk.ApplicationWindow):
    def __init__(self, app, settings_path, autostart):
        super().__init__(application=app, title="Tuner")
        self.settings_path = settings_path
        self.s = load_settings(settings_path)
        self.rx = self.s["receiver"]
        self.bookmarks = gqrxfiles.Bookmarks()
        self.online = online.Client(online.load_sources(Path(settings_path).with_name("online.json")))
        self.updating = False
        self.save_pending = None
        self.radio = radio.Radio(self.rx, self._spectrum_cb, self._status_cb, self._error_cb, self._stopped_cb)
        self.hd_data = {}
        self.hd_restart = False
        self.hd_channels = []
        self.rds_data = {}
        self.rds_seen = 0.0
        self.radio.on_rds = lambda gen, data: GLib.idle_add(self._rds_update, gen, data)
        self.radio.on_hd = lambda gen, data: GLib.idle_add(self._hd_update, gen, data)
        self.radio.on_recorded = lambda path, secs: GLib.idle_add(self._recorded, path, secs)
        self.set_default_size(*self.s["window"])
        self.set_icon_name("gqrx")
        self.connect("delete-event", self._quit)
        self.connect("configure-event", self._configure)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)
        box.pack_start(self._menubar(), False, False, 0)
        face = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        face.set_name("tuner-face")
        face.set_border_width(6)
        face.pack_start(self._toolbar(), False, False, 0)
        face.pack_start(self._dial_row(), False, False, 0)
        style_faceplate(face)
        box.pack_start(face, False, False, 0)
        self.infobar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING, show_close_button=True)
        self.info_label = Gtk.Label(xalign=0)
        self.info_label.set_line_wrap(True)
        self.infobar.get_content_area().add(self.info_label)
        self.infobar.connect("response", lambda bar, r: bar.hide())
        self.infobar.set_no_show_all(True)
        box.pack_start(self.infobar, False, False, 0)

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.spectrum = SpectrumView()
        for key in DISPLAY_DEFAULTS:
            setattr(self.spectrum, key, self.s[key])
        self.spectrum.zoom = self.s["zoom"]
        self.spectrum.peak_hold = self.s["peak_hold"]
        self.spectrum.auto_range = self.s["auto_range"]
        self.spectrum.floor = self.s["floor_db"]
        self.spectrum.range_db = self.s["range_db"]
        self.spectrum.connect("tune", lambda v, f: self.tune(self._snap(f)))
        self.spectrum.connect("step", lambda v, n: self.tune(self.s["frequency"] + n * self.s["step"]))
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
        frame.add(self.spectrum)
        self.paned.pack1(frame, True, False)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.receiver_page = self._receiver_page()
        self.notebook.append_page(self._scrolled(self.receiver_page), Gtk.Label(label="Receiver"))
        self.notebook.append_page(self._scrolled(self._audio_page()), Gtk.Label(label="Audio"))
        self.notebook.append_page(self._scrolled(self._input_page()), Gtk.Label(label="Input"))
        self.notebook.append_page(self._scrolled(self._bookmarks_page()), Gtk.Label(label="Bookmarks"))
        self.notebook.append_page(self._scrolled(self._waterfall_page()), Gtk.Label(label="Waterfall"))
        self.notebook.set_size_request(220, -1)
        self.paned.pack2(self.notebook, False, False)
        self.paned.set_border_width(6)
        box.pack_start(self.paned, True, True, 0)
        self.statusbar = Gtk.Statusbar()
        box.pack_start(self.statusbar, False, False, 0)

        self.show_all()
        if self.s["pane"]:
            self.paned.set_position(self.s["pane"])
        self.notebook.set_current_page(self.s["tab"])
        self.notebook.connect("switch-page", lambda nb, page, n: self._save("tab", n))
        self.paned.connect("notify::position", lambda p, _: self._save("pane", p.get_position()))
        self._sync_mode_controls()
        self.tune(self.s["frequency"], quiet=True)
        self._sync_hd_controls()
        self._status("Stopped")
        if autostart and self.s["start_on_launch"]:
            GLib.idle_add(self._autostart)
        if os.environ.get("TUNER_SHOT_FEED"):
            self._shot_feed(os.environ["TUNER_SHOT_FEED"])

    def _shot_feed(self, source):
        """tools/shot.sh only: draw the waterfall from a recording, silently."""
        import threading
        import numpy as np

        if os.environ.get("TUNER_SHOT_TAB"):
            self.notebook.set_current_page(int(os.environ["TUNER_SHOT_TAB"]))
        rate = self.s["sample_rate"]
        centre = self.s["frequency"] - rate // 4
        raw = Path(source).read_bytes() if source != "synthetic" else None

        def run():
            spec = dsp.Spectrum(4096)
            rx = dsp.Receiver(rate, dict(self.rx, offset=float(self.s["frequency"] - centre)))
            rng = np.random.default_rng(3)
            n = radio.READ_BYTES // 2
            t0 = 0
            for i in range(200):
                if raw:
                    iq = dsp.u8_to_iq(raw[(i * 2 * n) % len(raw):][:2 * n])
                else:
                    t = (t0 + np.arange(n)) / rate
                    t0 += n
                    iq = (rng.normal(size=2 * n).astype(np.float32).view(np.complex64) * 0.01)
                    for off, dev in ((rate / 4, 60000), (rate / 4 - 400000, 50000), (rate / 4 + 200000, 40000)):
                        msg = np.sin(2 * np.pi * (300 + 200 * np.sin(i / 7)) * t)
                        iq += 0.2 * np.exp(1j * (2 * np.pi * (off - rate / 2 + rate / 2) * t
                                                 + dev / 300 * msg)).astype(np.complex64)
                    iq = iq.astype(np.complex64)
                self._spectrum_cb(spec(iq, 2), centre, rate)
                rx.process(iq)
                self._status_cb(rx.level_db, rx.stereo, rx.squelched, False, None)
                threading.Event().wait(0.03)

        threading.Thread(target=run, daemon=True).start()

    # Construction --------------------------------------------------------

    def _menubar(self):
        bar = Gtk.MenuBar()
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)

        def menu(title, items):
            item = Gtk.MenuItem.new_with_mnemonic(title)
            sub = Gtk.Menu()
            item.set_submenu(sub)
            for entry in items:
                if entry is None:
                    sub.append(Gtk.SeparatorMenuItem())
                    continue
                label, key, callback = entry
                mi = Gtk.MenuItem.new_with_mnemonic(label)
                if key:
                    keyval, mods = Gtk.accelerator_parse(key)
                    mi.add_accelerator("activate", accel, keyval, mods, Gtk.AccelFlags.VISIBLE)
                mi.connect("activate", lambda _w, cb=callback: cb())
                sub.append(mi)
            bar.append(item)
            return sub

        radio_menu = menu("_Radio", [("_Start or Stop", "<Control>space", lambda: self.start_button.set_active(
                            not self.start_button.get_active())),
                        ("_Record", "<Control>r", lambda: self.record_button.set_active(
                            not self.record_button.get_active())),
                        ("_Mute", "<Control>m", lambda: self.mute_button.set_active(
                            not self.mute_button.get_active())),
                        None,
                        ("_Quit", "<Control>q", lambda: self._quit())])
        self.hd_item = Gtk.CheckMenuItem(label="HD Radio")
        self.hd_item.set_active(self.s["hd"])
        self.hd_item.connect("toggled", self._toggle_hd)
        radio_menu.insert(self.hd_item, 3)
        menu("_Bookmarks", [("_Add Bookmark…", "<Control>d", self._add_bookmark),
                            ("_Remove Bookmark", None, self._remove_bookmark),
                            ("Re_load from gqrx", None, self._reload_bookmarks)])
        menu("_View", [("Zoom _In", "<Control>plus", lambda: self._zoom(1)),
                       ("Zoom _Out", "<Control>minus", lambda: self._zoom(-1))])
        return bar

    def _toolbar(self):
        bar = Gtk.Toolbar()
        bar.set_style(Gtk.ToolbarStyle.TEXT)
        self.start_button = Gtk.ToggleToolButton(icon_name="media-playback-start", label="Start")
        self.start_button.set_tooltip_text("Start or stop receiving (Ctrl+Space)")
        self.start_button.set_is_important(True)
        self.start_button.connect("toggled", self._toggle_start)
        bar.insert(self.start_button, -1)
        self.record_button = Gtk.ToggleToolButton(icon_name="media-record", label="Record")
        self.record_button.set_tooltip_text("Record the audio to a WAV file (Ctrl+R)")
        self.record_button.set_is_important(True)
        self.record_button.connect("toggled", self._toggle_record)
        bar.insert(self.record_button, -1)
        bar.insert(Gtk.SeparatorToolItem(), -1)
        self.mute_button = Gtk.ToggleToolButton(icon_name="audio-volume-muted", label="Mute")
        self.mute_button.set_tooltip_text("Mute (Ctrl+M)")
        self.mute_button.set_active(self.rx["mute"])
        self.mute_button.connect("toggled", lambda b: self._rx("mute", b.get_active()))
        bar.insert(self.mute_button, -1)
        self.volume = Gtk.Adjustment(value=self.rx["volume_db"], lower=-40, upper=30,
                                     step_increment=0.5, page_increment=3)
        self.volume.connect("value-changed", lambda a: self._rx("volume_db", round(a.get_value(), 1)))
        item = Gtk.ToolItem()
        scale = SegmentScale(adjustment=self.volume)
        scale.set_draw_value(False)
        scale.set_tooltip_text("Audio gain")
        hbox = Gtk.Box(spacing=4)
        hbox.pack_start(Gtk.Label(label="Gain"), False, False, 0)
        hbox.pack_start(scale, False, False, 0)
        item.add(hbox)
        bar.insert(item, -1)
        return bar

    def _dial_row(self):
        row = Gtk.Box(spacing=10)
        row.set_border_width(6)
        self.dial = FrequencyDial()
        self.dial.connect("changed", lambda d, v: self.tune(v))
        self.rds_display = RdsDisplay()
        readout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        readout.pack_start(self.dial, False, False, 0)
        readout.pack_start(self.rds_display, False, False, 0)
        readout.set_valign(Gtk.Align.CENTER)
        row.pack_start(readout, True, True, 0)
        self.hd_combo = Gtk.ComboBoxText()
        self.hd_combo.set_tooltip_text("HD channels detected on this frequency")
        self.hd_combo.connect("changed", self._select_hd)
        self.hd_combo.set_valign(Gtk.Align.CENTER)
        row.pack_start(self.hd_combo, False, False, 0)

        controls = Gtk.Grid(column_spacing=6, row_spacing=4)
        self.mode_combo = self._combo(dsp.MODES, self.rx["mode"])
        self.mode_combo.connect("changed", lambda c: self._set_mode(c.get_active_text()))
        controls.attach(Gtk.Label(label="Mode", xalign=1), 0, 0, 1, 1)
        controls.attach(self.mode_combo, 1, 0, 1, 1)
        self.step_combo = self._combo([step_label(s) for s in STEPS], step_label(self.s["step"]))
        self.step_combo.connect("changed", lambda c: self._save("step", STEPS[c.get_active()]))
        controls.attach(Gtk.Label(label="Step", xalign=1), 0, 1, 1, 1)
        controls.attach(self.step_combo, 1, 1, 1, 1)
        row.pack_start(controls, False, False, 0)

        meter = Gtk.Grid(column_spacing=6, row_spacing=4)
        self.level_bar = SegmentMeter()
        self.level_bar.set_size_request(150, 24)
        self.level_bar.set_valign(Gtk.Align.CENTER)
        self.level_label = Gtk.Label(label="– dBFS", xalign=1, width_chars=11)
        self.stereo_label = Gtk.Label(xalign=0, width_chars=7)
        meter.attach(Gtk.Label(label="Signal", xalign=1), 0, 0, 1, 1)
        meter.attach(self.level_bar, 1, 0, 1, 1)
        meter.attach(self.level_label, 2, 0, 1, 1)
        go = Gtk.Entry(placeholder_text="MHz", width_chars=11)
        go.set_tooltip_text("Type a frequency in MHz and press Enter")
        go.connect("activate", self._go)
        meter.attach(Gtk.Label(label="Go to", xalign=1), 0, 1, 1, 1)
        meter.attach(go, 1, 1, 1, 1)
        meter.attach(self.stereo_label, 2, 1, 1, 1)
        row.pack_start(meter, False, False, 0)
        return row

    @staticmethod
    def _scrolled(child):
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        sw.add(child)
        return sw

    @staticmethod
    def _combo(items, active):
        combo = Gtk.ComboBoxText()
        for item in items:
            combo.append_text(item)
        if active in items:
            combo.set_active(items.index(active))
        return combo

    @staticmethod
    def _page():
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        grid.set_border_width(10)
        grid.next_row = 0
        return grid

    def _heading(self, grid, text):
        label = Gtk.Label(xalign=0)
        label.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
        if grid.next_row:
            label.set_margin_top(8)
        grid.attach(label, 0, grid.next_row, 3, 1)
        grid.next_row += 1

    def _row(self, grid, text, widget, extra=None, tip=None):
        label = Gtk.Label(label=text, xalign=0)
        label.set_margin_start(12)
        widget.set_hexpand(True)
        grid.attach(label, 0, grid.next_row, 1, 1)
        grid.attach(widget, 1, grid.next_row, 1 if extra else 2, 1)
        if extra:
            grid.attach(extra, 2, grid.next_row, 1, 1)
        if tip:
            label.set_tooltip_text(tip)
            widget.set_tooltip_text(tip)
        grid.next_row += 1
        return label

    def _spin(self, value, lower, upper, step, digits=0, callback=None):
        spin = Gtk.SpinButton.new_with_range(lower, upper, step)
        spin.set_digits(digits)
        spin.set_value(value)
        if callback:
            spin.connect("value-changed", lambda s: None if self.updating else callback(
                s.get_value() if digits else s.get_value_as_int()))
        return spin

    def _scale(self, value, lower, upper, step, digits, callback, fmt="%.1f dB"):
        adj = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=step,
                             page_increment=step * 10)
        adj.connect("value-changed", lambda a: None if self.updating else callback(round(a.get_value(), digits)))
        return LabelledScale(adj, digits, fmt)

    def _check(self, label, active, callback):
        check = Gtk.CheckButton(label=label)
        check.set_active(active)
        check.connect("toggled", lambda c: None if self.updating else callback(c.get_active()))
        return check

    def _receiver_page(self):
        g = self._page()
        rx = self.rx
        self._heading(g, "Filter")
        self.width_combo = self._combo(dsp.FILTER_WIDTHS, rx["filter_width"])
        self.width_combo.connect("changed", lambda c: None if self.updating else self._set_width(c.get_active_text()))
        self._row(g, "Width", self.width_combo)
        self.low_spin = self._spin(rx["filter_low"], -120000, 120000, 50,
                                   callback=lambda v: self._set_cuts(low=v))
        self._row(g, "Low cut (Hz)", self.low_spin)
        self.high_spin = self._spin(rx["filter_high"], -120000, 120000, 50,
                                    callback=lambda v: self._set_cuts(high=v))
        self._row(g, "High cut (Hz)", self.high_spin)
        shape = self._combo(list(dsp.FILTER_SHAPES), rx["filter_shape"])
        shape.connect("changed", lambda c: self._rx("filter_shape", c.get_active_text()))
        self._row(g, "Shape", shape, tip="Sharper filters reject neighbours better but ring more")

        self._heading(g, "Squelch")
        self.squelch = self._scale(rx["squelch_db"], -150, 0, 0.5, 1, lambda v: self._rx("squelch_db", v))
        auto = Gtk.Button(label="Auto")
        auto.set_tooltip_text("Set the squelch just above the current signal level")
        auto.connect("clicked", lambda b: self.squelch.set_value(round(self.radio.rx.level_db + 3, 1)
                                                                 if self.radio.rx else -150))
        self._row(g, "Level", self.squelch)
        reset = Gtk.Button(label="Open")
        reset.set_tooltip_text("Open the squelch fully")
        reset.connect("clicked", lambda b: self.squelch.set_value(-150))
        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        buttons.pack_start(auto, False, False, 0)
        buttons.pack_start(reset, False, False, 0)
        g.attach(buttons, 1, g.next_row, 2, 1)
        g.next_row += 1

        self._heading(g, "Automatic gain control")
        self.agc_combo = self._combo(list(dsp.AGC_PRESETS), rx["agc"])
        self.agc_combo.connect("changed", lambda c: self._set_agc(c.get_active_text()))
        self.agc_row = self._row(g, "Mode", self.agc_combo, tip="Applies to AM, SSB and CW")
        self.agc_threshold = self._scale(rx["agc_threshold_db"], -160, 0, 1, 0,
                                         lambda v: self._rx("agc_threshold_db", v))
        self._row(g, "Threshold", self.agc_threshold, tip="Weakest level that is brought up to full volume")
        self.agc_decay = self._spin(rx["agc_decay_ms"], 20, 5000, 10, callback=lambda v: self._rx("agc_decay_ms", v))
        self._row(g, "Decay (ms)", self.agc_decay)
        self.agc_slope = self._scale(rx["agc_slope_db"], 0, 10, 1, 0, lambda v: self._rx("agc_slope_db", v))
        self._row(g, "Slope", self.agc_slope, tip="How much louder strong signals stay, dB per 10 dB")
        self.agc_hang = self._check("Hang", rx["agc_hang"], lambda v: self._rx("agc_hang", v))
        g.attach(self.agc_hang, 1, g.next_row, 2, 1)
        g.next_row += 1
        self.manual_gain = self._scale(rx["agc_manual_gain_db"], -20, 60, 0.5, 1,
                                       lambda v: self._rx("agc_manual_gain_db", v))
        self._row(g, "Manual gain", self.manual_gain, tip="Used when AGC is off")

        self._heading(g, "Noise blankers")
        self.nb1 = self._check("NB1", rx["nb1"], lambda v: self._rx("nb1", v))
        self.nb1_thr = self._spin(rx["nb1_threshold"], 1, 20, 0.1, 1, lambda v: self._rx("nb1_threshold", v))
        g.attach(self.nb1, 0, g.next_row, 1, 1)
        g.attach(self.nb1_thr, 1, g.next_row, 2, 1)
        g.next_row += 1
        self.nb2 = self._check("NB2", rx["nb2"], lambda v: self._rx("nb2", v))
        self.nb2_thr = self._spin(rx["nb2_threshold"], 1, 20, 0.1, 1, lambda v: self._rx("nb2_threshold", v))
        g.attach(self.nb2, 0, g.next_row, 1, 1)
        g.attach(self.nb2_thr, 1, g.next_row, 2, 1)
        for w in (self.nb1, self.nb2):
            w.set_margin_start(12)
            w.set_tooltip_text("Blanks impulse noise (ignition, power lines) above threshold × average")
        g.next_row += 1

        self._heading(g, "Mode options")
        self.max_dev = self._combo(["2500", "5000", "8000"], str(rx["fm_max_dev"]))
        self.max_dev.connect("changed", lambda c: self._rx("fm_max_dev", int(c.get_active_text())))
        self.max_dev_row = self._row(g, "FM deviation (Hz)", self.max_dev, tip="Narrow FM's peak deviation")
        self.nfm_tau = self._combo(["Off", "25", "50", "75", "100", "250", "530", "1000"],
                                   str(rx["nfm_tau_us"]) if rx["nfm_tau_us"] else "Off")
        self.nfm_tau.connect("changed", lambda c: self._rx("nfm_tau_us", _tau(c.get_active_text())))
        self.nfm_tau_row = self._row(g, "De-emphasis (µs)", self.nfm_tau, tip="Narrow FM de-emphasis time constant")
        self.wfm_tau = self._combo(["Off", "50", "75"], str(rx["wfm_tau_us"]) if rx["wfm_tau_us"] else "Off")
        self.wfm_tau.connect("changed", lambda c: self._rx("wfm_tau_us", _tau(c.get_active_text())))
        self.wfm_tau_row = self._row(g, "De-emphasis (µs)", self.wfm_tau,
                                     tip="Broadcast FM: 75 µs in the Americas, 50 µs elsewhere")
        self.am_dcr = self._check("Remove DC", rx["am_dcr"], lambda v: self._rx("am_dcr", v))
        g.attach(self.am_dcr, 1, g.next_row, 2, 1)
        g.next_row += 1
        self.cw_offset = self._spin(rx["cw_offset"], 100, 2000, 10, callback=lambda v: self._rx("cw_offset", v))
        self.cw_row = self._row(g, "CW tone (Hz)", self.cw_offset)
        return g

    def _audio_page(self):
        g = self._page()
        self._heading(g, "Output")
        self._row(g, "Gain", LabelledScale(self.volume, 1, "%.1f dB"))
        mute = Gtk.CheckButton(label="Mute")
        mute.set_active(self.rx["mute"])
        mute.bind_property("active", self.mute_button, "active",
                           GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        g.attach(mute, 1, g.next_row, 2, 1)
        g.next_row += 1
        self.devices = [(None, "Default output")] + audio.output_devices()
        names = [d[1] for d in self.devices]
        current = next((d[1] for d in self.devices if d[0] == self.s["output"]), names[0])
        device = self._combo(names, current)
        device.connect("changed", lambda c: self._set_output(self.devices[c.get_active()][0]))
        self._row(g, "Device", device)
        self._row(g, "Sample rate", Gtk.Label(label="48 kHz, stereo", xalign=0))

        self._heading(g, "Network stream")
        udp = self._check("Stream audio over UDP", self.s["udp_enabled"], lambda v: self._udp("udp_enabled", v))
        udp.set_margin_start(12)
        udp.set_tooltip_text("gqrx-compatible: 48 kHz signed 16-bit PCM datagrams")
        g.attach(udp, 0, g.next_row, 3, 1)
        g.next_row += 1
        host = Gtk.Entry(text=self.s["udp_host"])
        host.connect("changed", lambda e: self._udp("udp_host", e.get_text().strip() or "localhost"))
        self._row(g, "Host", host)
        port = self._spin(self.s["udp_port"], 1, 65535, 1, callback=lambda v: self._udp("udp_port", v))
        self._row(g, "Port", port)
        stereo = self._check("Stereo", self.s["udp_stereo"], lambda v: self._udp("udp_stereo", v))
        g.attach(stereo, 1, g.next_row, 2, 1)
        g.next_row += 1

        self._heading(g, "Recording")
        folder = Gtk.FileChooserButton(title="Recordings folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        folder.set_filename(str(Path(self.s["rec_dir"]).expanduser()))
        folder.connect("file-set", lambda b: self._save("rec_dir", b.get_filename()))
        self._row(g, "Folder", folder)
        self.last_recording = Gtk.Label(label="", xalign=0)
        self.last_recording.set_ellipsize(3)
        self._row(g, "Last", self.last_recording)
        self._udp(None, None)
        return g

    def _input_page(self):
        g = self._page()
        self._heading(g, "Device")
        names = rtl.devices()
        self.device_label = Gtk.Label(label=names[0] if names else "No dongle found", xalign=0)
        self.device_label.set_ellipsize(3)
        self._row(g, "Dongle", self.device_label)
        rates = ["%.2f MS/s" % (r / 1e6) for r in radio.SAMPLE_RATES]
        rate = self._combo(rates, "%.2f MS/s" % (self.s["sample_rate"] / 1e6))
        self.rate_combo = rate
        rate.connect("changed", lambda c: self._hw("sample_rate", radio.SAMPLE_RATES[c.get_active()]))
        self._row(g, "Sample rate", rate, tip="Width of the spectrum view; higher rates use more CPU")

        self._heading(g, "Gain")
        self.auto_gain = self._check("Automatic tuner gain", self.s["gain_db"] is None, self._set_auto_gain)
        self.auto_gain.set_margin_start(12)
        g.attach(self.auto_gain, 0, g.next_row, 3, 1)
        g.next_row += 1
        self.gain_scale = self._scale(self.s["gain_db"] if self.s["gain_db"] is not None else 30.0,
                                      0, 49.6, 0.1, 1, self._set_gain)
        self.gain_scale.set_sensitive(self.s["gain_db"] is not None)
        self._row(g, "RF gain", self.gain_scale, tip="Lower it if the status bar reports overload")
        agc = self._check("RTL2832 digital AGC", self.s["rtl_agc"], lambda v: self._hw("rtl_agc", v))
        agc.set_margin_start(12)
        g.attach(agc, 0, g.next_row, 3, 1)
        g.next_row += 1

        self._heading(g, "Corrections")
        ppm = self._spin(self.s["ppm"], -200, 200, 0.5, 1, lambda v: self._hw("ppm", v))
        self._row(g, "Frequency (ppm)", ppm, tip="Crystal error; tune a known station and adjust until centred")
        bias = self._check("Bias tee (powers an active antenna)", self.s["bias_tee"],
                           lambda v: self._hw("bias_tee", v))
        bias.set_margin_start(12)
        g.attach(bias, 0, g.next_row, 3, 1)
        g.next_row += 1

        start = self._check("Start receiving when opened", self.s["start_on_launch"],
                            lambda v: self._save("start_on_launch", v))
        start.set_margin_top(8)
        g.attach(start, 0, g.next_row, 3, 1)
        g.next_row += 1
        return g

    def _waterfall_page(self):
        g = self._page()
        self._heading(g, "Spectrum and waterfall")
        zoom = self._combo(["%d×" % z for z in ZOOMS], "%d×" % self.s["zoom"])
        zoom.connect("changed", lambda c: self._set_zoom(ZOOMS[c.get_active()]))
        self.zoom_combo = zoom
        self._row(g, "Zoom", zoom)
        auto = self._check("Automatic range", self.s["auto_range"], self._set_auto_range)
        g.attach(auto, 1, g.next_row, 2, 1)
        g.next_row += 1
        rng = self._scale(self.s["range_db"], 20, 120, 1, 0, self._set_range)
        self._row(g, "Range", rng)
        self.floor_scale = self._scale(self.s["floor_db"], -140, 0, 1, 0, self._set_floor)
        self.floor_scale.set_sensitive(not self.s["auto_range"])
        self._row(g, "Floor", self.floor_scale)
        peak = self._check("Peak hold", self.s["peak_hold"], self._set_peak_hold)
        g.attach(peak, 1, g.next_row, 2, 1)
        g.next_row += 1
        self._heading(g, "Waterfall")
        palette = self._combo(list(COLOUR_MAPS), self.s["colour_map"])
        palette.connect("changed", lambda c: self._set_display("colour_map", c.get_active_text()))
        self._row(g, "Colours", palette)
        for label, key, low, high, step, digits, tip in (
            ("Intensity (dB)", "intensity_db", -40, 40, 1, 0,
             "Brighten or darken the waterfall without changing the spectrum scale"),
            ("Contrast", "contrast", 0.2, 3, 0.1, 1,
             "Below 1 reveals weak signals; above 1 emphasizes strong signals"),
            ("Line interval (s)", "line_interval", 0, 2, 0.05, 2,
             "0 draws every update; longer intervals scroll more slowly and retain the strongest signal per bin"),
        ):
            control = self._spin(self.s[key], low, high, step, digits,
                                 lambda value, key=key: self._set_display(key, value))
            self._row(g, label, control, tip=tip)
        actions = Gtk.Box(spacing=6)
        pause = Gtk.ToggleButton(label="Pause waterfall")
        pause.connect("toggled", lambda b: self.spectrum.pause_waterfall(b.get_active()))
        clear = Gtk.Button(label="Clear waterfall")
        clear.connect("clicked", lambda b: self.spectrum.clear_waterfall())
        actions.pack_start(pause, False, False, 0)
        actions.pack_start(clear, False, False, 0)
        g.attach(actions, 0, g.next_row, 3, 1)
        g.next_row += 1

        self._heading(g, "Spectrum trace")
        for label, key, low, high, step, digits, tip in (
            ("Height (%)", "spectrum_percent", 10, 80, 1, 0,
             "Share of the display used by the spectrum; the remainder is waterfall"),
            ("Smoothing (%)", "smoothing", 0, 95, 5, 0,
             "0 follows every update; higher values smooth the spectrum trace"),
            ("Peak decay (dB/update)", "peak_decay", 0, 3, 0.05, 2,
             "How quickly held peaks fall; 0 holds maxima until reset or retuned"),
        ):
            control = self._spin(self.s[key], low, high, step, digits,
                                 lambda value, key=key: self._set_display(key, value))
            self._row(g, label, control, tip=tip)
        reset = Gtk.Button(label="Reset peaks")
        reset.connect("clicked", lambda b: self._reset_peaks())
        g.attach(reset, 1, g.next_row, 2, 1)
        g.next_row += 1
        self._heading(g, "Overlays")
        for label, key in (("Grid", "show_grid"), ("Fill under trace", "fill_trace"),
                           ("Bookmark labels", "show_bookmarks"), ("Filter shading", "show_filter"),
                           ("Tuned frequency line", "show_tuning_line"), ("Pointer crosshair", "show_crosshair")):
            control = self._check(label, self.s[key], lambda value, key=key: self._set_display(key, value))
            g.attach(control, 1, g.next_row, 2, 1)
            g.next_row += 1
        return g

    def _bookmarks_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(6)
        top = Gtk.Box(spacing=6)
        top.pack_start(Gtk.Label(label="Show"), False, False, 0)
        self.tag_combo = Gtk.ComboBoxText()
        top.pack_start(self.tag_combo, True, True, 0)
        box.pack_start(top, False, False, 0)
        # colour, frequency (sort key), frequency text, name, mode, index
        self.store = Gtk.ListStore(str, GObject.TYPE_INT64, str, str, str, int)
        self.filtered = self.store.filter_new()
        self.filtered.set_visible_func(self._tag_visible)
        sorted_model = Gtk.TreeModelSort(model=self.filtered)
        self.tree = Gtk.TreeView(model=sorted_model)
        self.tree.set_headers_clickable(True)
        self.tree.set_search_column(3)
        swatch = Gtk.CellRendererText(text="  ")
        col = Gtk.TreeViewColumn("", swatch, background=0)
        col.bookmark_key = "colour"
        col.set_reorderable(True)
        self.tree.append_column(col)
        for title, index, sort, expand in (("MHz", 2, 1, False), ("Name", 3, 3, True), ("Mode", 4, 4, False)):
            cell = Gtk.CellRendererText()
            if index == 2:
                cell.set_property("xalign", 1.0)
                cell.set_property("family", "Ubuntu Mono")
            if expand:
                cell.set_property("ellipsize", 3)
            col = Gtk.TreeViewColumn(title, cell, text=index)
            col.set_sort_column_id(sort)
            col.set_expand(expand)
            col.set_resizable(True)
            col.set_reorderable(True)
            col.bookmark_key = title
            self.tree.append_column(col)
        columns = {col.bookmark_key: col for col in self.tree.get_columns()}
        previous = None
        saved_order = self.s["bookmark_columns"]
        if isinstance(saved_order, list):
            for key in saved_order:
                col = columns.pop(key, None) if isinstance(key, str) else None
                if col is not None:
                    self.tree.move_column_after(col, previous)
                    previous = col
        self.tree.connect("columns-changed", lambda tree: self._save(
            "bookmark_columns", [col.bookmark_key for col in tree.get_columns()]))
        self.tree.connect("row-activated", self._bookmark_activated)
        self.tree.set_tooltip_text("Double-click a bookmark to tune to it; drag column headers to reorder")
        sw = Gtk.ScrolledWindow()
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(self.tree)
        box.pack_start(sw, True, True, 0)
        buttons = Gtk.Box(spacing=6)
        add = Gtk.Button.new_from_icon_name("list-add", Gtk.IconSize.BUTTON)
        add.set_label("Add")
        add.set_always_show_image(True)
        add.connect("clicked", lambda b: self._add_bookmark())
        remove = Gtk.Button.new_from_icon_name("list-remove", Gtk.IconSize.BUTTON)
        remove.set_label("Remove")
        remove.set_always_show_image(True)
        remove.connect("clicked", lambda b: self._remove_bookmark())
        buttons.pack_start(add, False, False, 0)
        buttons.pack_start(remove, False, False, 0)
        note = Gtk.Label(xalign=1)
        note.set_markup("<small>Shared with gqrx</small>")
        note.get_style_context().add_class("dim-label")
        buttons.pack_end(note, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        self.tag_combo.connect("changed", self._tag_changed)
        self._fill_bookmarks()
        return box

    # Bookmarks -----------------------------------------------------------

    def _fill_bookmarks(self):
        self.store.clear()
        for i, b in enumerate(self.bookmarks.items):
            self.store.append([self.bookmarks.tag_colour(b), b.freq, "%.4f" % (b.freq / 1e6), b.name,
                               SHORT_MODES.get(dsp.canonical_mode(b.mode), b.mode), i])
        self.updating = True
        self.tag_combo.remove_all()
        self.tag_combo.append("", "All bookmarks")
        for tag in self.bookmarks.tags:
            self.tag_combo.append(tag, tag)
        if not self.tag_combo.set_active_id(self.s["tag_filter"]):
            self.tag_combo.set_active_id("")
        self.updating = False
        self.filtered.refilter()
        self.spectrum.bookmarks = [(b.freq, b.name, self.bookmarks.tag_colour(b)) for b in self.bookmarks.items]
        self.spectrum.queue_draw()

    def _tag_visible(self, model, it, data):
        tag = self.s["tag_filter"]
        if not tag:
            return True
        return tag in self.bookmarks.items[model[it][5]].tags

    def _tag_changed(self, combo):
        if self.updating:
            return
        self._save("tag_filter", combo.get_active_id() or "")
        self.filtered.refilter()

    def _bookmark_activated(self, tree, path, column):
        b = self.bookmarks.items[tree.get_model()[path][5]]
        mode = dsp.canonical_mode(b.mode)
        low, high = dsp.bookmark_filter(mode, b.bandwidth)
        self._set_mode(mode, cuts=(low, high))
        self.tune(b.freq)

    def _selected_bookmark(self):
        model, it = self.tree.get_selection().get_selected()
        return self.bookmarks.items[model[it][5]] if it else None

    def _add_bookmark(self):
        dialog = Gtk.Dialog(title="Add Bookmark", transient_for=self, modal=True)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_ADD, Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        grid = self._page()
        freq = self.s["frequency"]
        self._row(grid, "Frequency", Gtk.Label(label="%.4f MHz, %s" % (freq / 1e6, self.rx["mode"]), xalign=0))
        name = Gtk.Entry(text="%.3f" % (freq / 1e6), activates_default=True, width_chars=28)
        self._row(grid, "Name", name)
        tag = Gtk.ComboBoxText.new_with_entry()
        for t in self.bookmarks.tags:
            tag.append_text(t)
        if self.s["tag_filter"]:
            tag.get_child().set_text(self.s["tag_filter"])
        self._row(grid, "Tag", tag)
        dialog.get_content_area().add(grid)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK and name.get_text().strip():
            tags = [tag.get_child().get_text().strip()] if tag.get_child().get_text().strip() else []
            width = int(self.rx["filter_high"] - self.rx["filter_low"])
            self.bookmarks.add(gqrxfiles.Bookmark(freq, name.get_text().strip(), self.rx["mode"], width, tags))
            self._fill_bookmarks()
        dialog.destroy()

    def _remove_bookmark(self):
        b = self._selected_bookmark()
        if b:
            self.bookmarks.remove(b)
            self._fill_bookmarks()

    def _reload_bookmarks(self):
        self.bookmarks.load()
        self._fill_bookmarks()

    # Tuning and receiver settings -----------------------------------------

    def tune(self, freq, quiet=False):
        freq = max(1000, int(freq))
        self.s["frequency"] = freq
        self.dial.set_value(freq)
        self.spectrum.freq = freq
        self.spectrum.queue_draw()
        if self.radio.running:
            self.radio.tune(freq)
        self.rds_data, self.rds_seen = {}, 0.0
        self.hd_data = {}
        self.radio.hd_program = 0
        if self.s["hd"]:
            self.radio.select_hd(0)
        self._sync_hd_channels([])
        self._refresh_rds()
        self._select_bookmark(freq)
        if not quiet:
            self._save()

    def _rds_update(self, generation, data):
        if generation != self.radio.metadata_generation or not self.radio.running:
            return False
        self.rds_data = data
        self.rds_seen = time.monotonic() if data.get("pi") else 0.0
        self._refresh_rds()
        return False

    def _toggle_hd(self, button):
        self._save("hd", button.get_active())
        self.rds_data, self.rds_seen = {}, 0.0
        self.hd_data = {}
        self._sync_hd_channels([])
        self._sync_hd_controls()
        if self.radio.running:
            # The old reader must release the dongle before the new mode starts.
            if self.record_button.get_active():
                self.record_button.set_active(False)
            self.hd_restart = True
            self.hd_item.set_sensitive(False)
            self.radio.stop()
        self._refresh_rds()

    def _sync_hd_controls(self):
        enabled = self.s["hd"]
        self.receiver_page.set_sensitive(not enabled)
        self.receiver_page.set_tooltip_text("Analog receiver settings; HD uses its own decoder" if enabled else None)
        self.spectrum.filter = (-200000, 200000) if enabled else (self.rx["filter_low"], self.rx["filter_high"])
        self.spectrum.queue_draw()
        self.mode_combo.set_sensitive(not enabled)
        self.rate_combo.set_sensitive(not enabled)
        self.rate_combo.set_tooltip_text("HD uses 1.488375 MS/s" if enabled else "Analog sample rate")
        for control in (self.width_combo, self.low_spin, self.high_spin, self.squelch):
            control.set_sensitive(not enabled)
        self.hd_combo.set_no_show_all(not enabled)
        self.hd_combo.set_visible(enabled)
        self._sync_hd_channels(self.hd_data.get("channels", []))

    def _sync_hd_channels(self, channels):
        channels = sorted(set(channels))
        selected = self.radio.hd_program
        ids = sorted(set(channels + [selected]))
        labels = [(p, "HD%d%s" % (p + 1, "" if p in channels else " · waiting")) for p in ids]
        if labels != self.hd_channels:
            self.hd_channels = labels
            self.hd_combo.remove_all()
            for program, label in labels:
                self.hd_combo.append(str(program), label)
        self.hd_combo.set_active_id(str(selected))
        self.hd_combo.set_sensitive(self.s["hd"] and bool(channels) and len(ids) > 1)

    def _select_hd(self, combo):
        value = combo.get_active_id()
        if value is not None and int(value) != self.radio.hd_program:
            self.radio.select_hd(int(value))
            self.hd_data = {k: v for k, v in self.hd_data.items()
                            if k in ("station", "channels", "locked", "mer")}
            self._refresh_rds()

    def _hd_update(self, generation, data):
        if (generation != self.radio.metadata_generation or not self.radio.running
                or not self.s["hd"] or data.get("program", 0) != self.radio.hd_program):
            return False
        self.hd_data = data
        self._sync_hd_channels(data.get("channels", []))
        self._refresh_rds()
        return False

    def _refresh_hd(self):
        data = self.hd_data
        heading = "%s MHz  ·  HD%d" % (mhz_text(self.s["frequency"]), self.radio.hd_program + 1)
        if data.get("station"):
            heading += "  ·  " + data["station"]
        if not self.radio.running:
            message = "Receiver stopped"
        elif not data.get("locked"):
            message = "HD signal lost" if data.get("station") else "Searching for HD Radio"
        elif not data.get("audio"):
            message = "HD locked - waiting for audio"
        else:
            message = " - ".join(filter(None, (data.get("artist"), data.get("title"))))
            message = message or data.get("station") or "Digital audio"
        detail = heading + "\n" + message
        if data.get("mer"):
            detail += "\nHD MER: %.1f / %.1f dB" % tuple(data["mer"])
        self.rds_display.set_message(heading, message, detail)

    def _refresh_rds(self):
        if self.s["hd"]:
            self.online.poll(None, "")
            self._refresh_hd()
            return
        heading = "%s MHz  ·  RDS" % mhz_text(self.s["frequency"])
        data = self.rds_data
        if not self.radio.running:
            message = "Receiver stopped"
        elif self.rx["mode"] not in dsp.WFM_MODES:
            message = "Select WFM for RDS"
        elif data.get("error"):
            message = "RDS unavailable"
        elif not self.rds_seen:
            message = "Waiting for RDS"
        elif time.monotonic() - self.rds_seen > 10:
            self.rds_data = {}
            data = {}
            message = "RDS signal lost"
        else:
            heading += "  ·  " + data.get("ps", "PI " + data["pi"][2:].upper())
            if data.get("prog_type"):
                heading += "  ·  " + data["prog_type"]
            message = data.get("radiotext") or data.get("ps") or "Reading station text"
        detail = heading + "\n" + message
        if data.get("pi"):
            detail += "\nPI: " + data["pi"]
        if data.get("error"):
            detail += "\n" + data["error"]
        fresh = self.rds_seen and time.monotonic() - self.rds_seen <= 10
        name = online.bookmark_name(self.bookmarks.items, self.s["frequency"])
        if (self.radio.running and self.rx["mode"] in dsp.WFM_MODES and name
                and not (fresh and data.get("radiotext"))):
            key = (self.radio.metadata_generation, self.s["frequency"], name)
            text, status = self.online.poll(key, name)
            origin = "Online" if text else "Bookmark"
            heading = "%s MHz  ·  %s  ·  %s" % (mhz_text(self.s["frequency"]), origin, name)
            if fresh and data.get("ps"):
                heading += "  ·  RDS: " + data["ps"]
            message = text or name
            detail += "\n" + heading + "\n" + status
            if text:
                detail += "\n" + text
        else:
            self.online.poll(None, "")
        self.rds_display.set_message(heading, message, detail)

    def _select_bookmark(self, freq):
        sel = self.tree.get_selection()
        for row in self.tree.get_model():
            if abs(row[1] - freq) < 500:
                sel.select_iter(row.iter)
                self.tree.scroll_to_cell(row.path, None, False, 0, 0)
                return
        sel.unselect_all()

    def _snap(self, freq):
        step = self.s["step"]
        return int(round(freq / step) * step)

    def _go(self, entry):
        try:
            mhz = float(entry.get_text().replace(",", "."))
        except ValueError:
            return
        self.tune(int(round(mhz * 1e6)))
        entry.set_text("")

    def _rx(self, key, value):
        self.rx[key] = value
        self.radio.receiver(**{key: value})
        self._save()

    def _set_mode(self, mode, cuts=None):
        if self.updating or not mode:
            return
        mode = dsp.canonical_mode(mode)
        changed = mode != self.rx["mode"]
        self.rx["mode"] = mode
        if cuts:
            low, high = cuts
            width = next((w for w in ("Wide", "Normal", "Narrow") if dsp.filter_for(mode, w) == cuts), "User")
        else:
            width = self.rx["filter_width"] if self.rx["filter_width"] != "User" else "Normal"
            low, high = dsp.filter_for(mode, width)
        self.rx.update(filter_width=width, filter_low=low, filter_high=high)
        self.radio.receiver(mode=mode, filter_width=width, filter_low=low, filter_high=high)
        if changed:
            step = MODE_STEP[mode]
            self.s["step"] = step
        self.rds_data, self.rds_seen = {}, 0.0
        self._refresh_rds()
        self._sync_mode_controls()
        self._save()

    def _set_width(self, width):
        if width == "User":
            self._rx("filter_width", "User")
            return
        low, high = dsp.filter_for(self.rx["mode"], width)
        self.rx.update(filter_width=width, filter_low=low, filter_high=high)
        self.radio.receiver(filter_width=width, filter_low=low, filter_high=high)
        self._sync_mode_controls()
        self._save()

    def _set_cuts(self, low=None, high=None):
        low = self.rx["filter_low"] if low is None else low
        high = self.rx["filter_high"] if high is None else high
        if high - low < 50:
            return
        self.rx.update(filter_width="User", filter_low=low, filter_high=high)
        self.radio.receiver(filter_width="User", filter_low=low, filter_high=high)
        self._sync_mode_controls()
        self._save()

    def _set_agc(self, name):
        if self.updating:
            return
        preset = dsp.AGC_PRESETS.get(name)
        changes = {"agc": name}
        if preset:
            changes["agc_decay_ms"], changes["agc_hang"] = preset
        self.rx.update(changes)
        self.radio.receiver(**changes)
        self._sync_mode_controls()
        self._save()

    def _sync_mode_controls(self):
        self.updating = True
        rx = self.rx
        mode = rx["mode"]
        self.mode_combo.set_active(dsp.MODES.index(mode))
        self.width_combo.set_active(dsp.FILTER_WIDTHS.index(rx["filter_width"]))
        self.low_spin.set_value(rx["filter_low"])
        self.high_spin.set_value(rx["filter_high"])
        self.step_combo.set_active(STEPS.index(self.s["step"]) if self.s["step"] in STEPS else 0)
        self.agc_decay.set_value(rx["agc_decay_ms"])
        self.agc_hang.set_active(rx["agc_hang"])
        fm = mode in ("Narrow FM",) + dsp.WFM_MODES
        agc_used = not fm
        user = rx["agc"] == "User"
        self.agc_combo.set_sensitive(agc_used)
        for w in (self.agc_threshold, self.agc_slope):
            w.set_sensitive(agc_used and rx["agc"] != "Off")
        for w in (self.agc_decay, self.agc_hang):
            w.set_sensitive(agc_used and user)
        self.manual_gain.set_sensitive(agc_used and rx["agc"] == "Off")
        self.max_dev.set_sensitive(mode == "Narrow FM")
        self.nfm_tau.set_sensitive(mode == "Narrow FM")
        self.wfm_tau.set_sensitive(mode in dsp.WFM_MODES)
        self.am_dcr.set_sensitive(mode in ("AM", "AM-Sync"))
        self.cw_offset.set_sensitive(mode in ("CW-L", "CW-U"))
        self.spectrum.filter = (rx["filter_low"], rx["filter_high"])
        self.spectrum.queue_draw()
        self.updating = False
        self._sync_hd_controls()

    # Hardware, audio and view settings -------------------------------------

    def _hw(self, key, value):
        self.s[key] = value
        if self.radio.running:
            self.radio.hardware(key, value)
        self._save()

    def _set_auto_gain(self, auto):
        self.gain_scale.set_sensitive(not auto)
        self._hw("gain_db", None if auto else round(self.gain_scale.get_value(), 1))

    def _set_gain(self, value):
        if not self.auto_gain.get_active():
            # Snap to the tuner's real gain steps, as the dongle would anyway.
            if self.radio.gains:
                value = min(self.radio.gains, key=lambda g: abs(g - value))
            self._hw("gain_db", value)

    def _set_output(self, target):
        self._save("output", target)
        self.radio.set_output(target)

    def _udp(self, key, value):
        if key:
            self.s[key] = value
            self._save()
        s = self.s
        self.radio.set_udp((s["udp_host"], int(s["udp_port"]), s["udp_stereo"]) if s["udp_enabled"] else None)

    def _set_display(self, key, value):
        setattr(self.spectrum, key, value)
        self.spectrum.queue_draw()
        self._save(key, value)

    def _reset_peaks(self):
        self.spectrum.peak = None
        self.spectrum.queue_draw()

    def _set_zoom(self, zoom):
        self.spectrum.zoom = zoom
        self.spectrum.queue_draw()
        self._save("zoom", zoom)

    def _zoom(self, direction):
        i = ZOOMS.index(self.s["zoom"]) if self.s["zoom"] in ZOOMS else 0
        i = max(0, min(len(ZOOMS) - 1, i + direction))
        self.zoom_combo.set_active(i)

    def _set_auto_range(self, auto):
        self.spectrum.auto_range = auto
        self.floor_scale.set_sensitive(not auto)
        if not auto:
            self.spectrum.floor = self.floor_scale.get_value()
        self._save("auto_range", auto)

    def _set_range(self, value):
        self.spectrum.range_db = value
        self.spectrum.queue_draw()
        self._save("range_db", value)

    def _set_floor(self, value):
        self.spectrum.floor = value
        self.spectrum.queue_draw()
        self._save("floor_db", value)

    def _set_peak_hold(self, on):
        self.spectrum.peak_hold = on
        self.spectrum.peak = None
        self._save("peak_hold", on)

    # Start, stop, record ---------------------------------------------------

    def _autostart(self):
        if rtl.devices():
            self.start_button.set_active(True)
        else:
            self._warn("No RTL-SDR dongle found. Plug it in and press Start.")
        return False

    def _toggle_start(self, button):
        if button.get_active():
            if not self.radio.running:
                hw = {k: self.s[k] for k in HW_DEFAULTS}
                self.radio.playback.target = self.s["output"]
                self.radio.start(hw)
                self._status("Receiving")
            button.set_icon_name("media-playback-stop")
            button.set_label("Stop")
        else:
            self.hd_restart = False
            self.radio.stop()
            button.set_icon_name("media-playback-start")
            button.set_label("Start")
            if self.record_button.get_active():
                self.record_button.set_active(False)

    def _toggle_record(self, button):
        if button.get_active():
            if not self.radio.running:
                button.set_active(False)
                self._warn("Start receiving before recording.")
                return
            self.radio.start_recording(self.s["rec_dir"], "HD%d" % (self.radio.hd_program + 1) if self.s["hd"] else self.rx["mode"])
        else:
            self.radio.stop_recording()

    def _recorded(self, path, seconds):
        self.last_recording.set_text("%s (%d s)" % (path.name, seconds))
        self.last_recording.set_tooltip_text(str(path))
        self._status("Saved %s" % path)
        return False

    # Radio callbacks (radio thread -> GTK) ------------------------------------

    def _spectrum_cb(self, row, center, rate):
        GLib.idle_add(self.spectrum.push, row, center, rate)

    def _status_cb(self, level, stereo, squelched, overload, recording):
        GLib.idle_add(self._show_status, level, stereo, squelched, overload, recording)

    def _error_cb(self, message):
        GLib.idle_add(self._warn, message)

    def _stopped_cb(self):
        GLib.idle_add(self._stopped)

    def _show_status(self, level, stereo, squelched, overload, recording):
        self._refresh_rds()
        self.level_bar.set_value(max(0.0, min(100.0, (level + 100) / 100 * 100)))
        self.level_label.set_text("%.1f dBFS" % level)
        mode = self.rx["mode"]
        self.stereo_label.set_text("Stereo" if stereo else ("Mono" if mode in dsp.WFM_MODES else ""))
        if self.s["hd"]:
            mode = "HD%d" % (self.radio.hd_program + 1)
            self.stereo_label.set_text("HD lock" if self.hd_data.get("locked") else "HD seek")
        parts = ["Receiving %.4f MHz %s" % (self.s["frequency"] / 1e6, mode)]
        if squelched:
            parts.append("squelched")
        if overload:
            parts.append("RF overload: lower the gain")
        if recording is not None:
            parts.append("recording %d:%02d" % (recording // 60, recording % 60))
        self._status(" · ".join(parts))
        return False

    def _stopped(self):
        if self.radio.thread and self.radio.thread.is_alive():
            GLib.timeout_add(30, self._stopped)
            return False
        self.hd_item.set_sensitive(True)
        if self.hd_restart:
            self.hd_restart = False
            self._toggle_start(self.start_button)
            return False
        self.hd_data = {}
        self._sync_hd_channels([])
        self.rds_data, self.rds_seen = {}, 0.0
        self._refresh_rds()
        if self.start_button.get_active():
            self.start_button.set_active(False)
        self.level_bar.set_value(0)
        self.level_label.set_text("– dBFS")
        self.stereo_label.set_text("")
        self.spectrum.clear()
        self._status("Stopped")
        if rtl.devices():
            self.device_label.set_text("%s (%s)" % (rtl.devices()[0], self.radio.tuner or "tuner"))
        return False

    def _warn(self, message):
        if message:
            self.info_label.set_text(message)
            self.infobar.show()
            self.info_label.show()
            self._status(message)
        return False

    def _status(self, text):
        self.statusbar.pop(0)
        self.statusbar.push(0, text)

    # Persistence ---------------------------------------------------------

    def _save(self, key=None, value=None):
        if key is not None:
            self.s[key] = value
        if self.save_pending is None:
            self.save_pending = GLib.timeout_add(500, self._write_settings)

    def _write_settings(self):
        self.save_pending = None
        data = {k: v for k, v in self.s.items() if k != "receiver"}
        data["receiver"] = {k: v for k, v in self.rx.items() if k != "offset"}
        path = Path(self.settings_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)
        return False

    def _configure(self, widget, event):
        if not self.is_maximized():
            size = list(self.get_size())
            if size != self.s["window"]:
                self._save("window", size)
        return False

    def _quit(self, *args):
        self.online.close()
        self.hd_restart = False
        self.radio.stop()
        if self.radio.thread:
            self.radio.thread.join(timeout=3)
        if self.save_pending is not None:
            GLib.source_remove(self.save_pending)
        self._write_settings()
        self.get_application().quit()
        return False


class LabelledScale(Gtk.Box):
    """A slider with its value in a fixed-width label, so long values never overlap it."""

    def __init__(self, adjustment, digits, fmt):
        super().__init__(spacing=6)
        self.adjustment, self.fmt = adjustment, fmt
        self.scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
        self.scale.set_digits(digits)
        self.scale.set_draw_value(False)
        self.label = Gtk.Label(xalign=1, width_chars=9)
        self.pack_start(self.scale, True, True, 0)
        self.pack_start(self.label, False, False, 0)
        adjustment.connect("value-changed", self._show)
        self._show(adjustment)

    def _show(self, adjustment):
        self.label.set_text(self.fmt % adjustment.get_value())

    def set_value(self, value):
        self.adjustment.set_value(value)

    def get_value(self):
        return self.adjustment.get_value()


def _tau(text):
    return 0 if text == "Off" else int(text)


class TunerApp(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id="org.lam.tuner")
        self.args = args
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = TunerWindow(self, self.args.settings, not self.args.no_start)
        self.window.present()


def main():
    parser = argparse.ArgumentParser(description="RTL-SDR receiver")
    parser.add_argument("--no-start", action="store_true", help="do not start receiving on launch")
    parser.add_argument("--settings", default=str(SETTINGS))
    args = parser.parse_args()
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Tuner")
    return TunerApp(args).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())

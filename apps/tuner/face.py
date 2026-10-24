"""The receiver display: one pane of fourteen-segment cells in three rows.

Every character, meter and control on the face is drawn in the same cell grid,
and every cell shows its unlit segments. The GTK objects main.py keeps for
state (toggle buttons, combo boxes, the gain adjustment, level labels) are
never packed: the face reads them each frame and drives them on input, so
their signals and the menu accelerators keep working unchanged.
"""

import math
import time

import cairo
from gi.repository import Gdk, GLib, GObject, Gtk

import faceplate
from faceplate import GHOST, GLASS
from rdsview import ALL, UPRIGHTS, add_dots, add_segments, display_text, segments, stroke_width

SIZE = 32  # character size; a glyph is .70 of it tall and .46 wide
ADVANCE, GLYPH_W, GLYPH_H = SIZE * .60, SIZE * .46, SIZE * .70
PITCH = GLYPH_H + 10  # row to row
PAD_X, PAD_Y = 12, 7
ROWS = 3
TICK_MS = 80

MODE_TEXT = {"AM-Sync": "AM SYNC", "Narrow FM": "NFM", "WFM (mono)": "WFM MONO",
             "WFM (stereo)": "WFM ST"}
GAIN_CELLS, METER_CELLS, ANALYZER_CELLS = 6, 8, 4
DIM, LABEL, UNLIT_SIGN = .3, .55, .13  # alphas: unavailable, caption, dark annunciator


class Level:
    """main.py's signal meter handle: a target the face's ballistics follow."""

    def __init__(self, face):
        self.face = face
        self.value = 0.0

    def set_value(self, value):
        self.value = value


class Face(Gtk.DrawingArea):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_INT64,)),
                    "go": (GObject.SignalFlags.RUN_FIRST, None, (str,))}
    DIGITS = 10  # up to 9.999 999 999 GHz

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.value = 100000000
        self.heading, self.text, self._detail = 'RDS', 'Receiver stopped', None
        self.since = time.monotonic()
        self.level = Level(self)
        self.shown, self.peak, self.peak_at = 0.0, 0.0, 0.0
        self.bands, self.band_targets, self.band_at = [0.0] * (3 * ANALYZER_CELLS), None, 0.0
        self.rds_lit = False
        self.cells, self.zones, self.boxes, self.points = {}, [], [], []
        self.ncols = 1
        self.reach = (7, 4)
        self.hover, self.hover_place = None, None
        self.focus_zone, self.focus_place = 'freq', None
        self.editing = None
        self.born = None
        self._ghost = None
        self._last = time.monotonic()
        self._scroll_carry = 0.0
        self._drag = False
        self.timer = None
        self.set_can_focus(True)
        self.set_has_tooltip(True)
        self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.FOCUS_CHANGE_MASK)
        self.set_size_request(400, round(ROWS * PITCH + 2 * PAD_Y))
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("button-release-event", lambda *a: setattr(self, "_drag", False))
        self.connect("motion-notify-event", self._motion)
        self.connect("leave-notify-event", lambda *a: self._set_hover(None, None))
        self.connect("scroll-event", self._scroll)
        self.connect("key-press-event", self._key)
        self.connect("focus-out-event", lambda *a: self._end_edit())
        self.connect("query-tooltip", self._tooltip)
        self.connect("map", self._mapped)
        self.connect("unmap", self._unmapped)
        self.connect("destroy", self._unmapped)
        self.get_accessible().set_name("Receiver display")

    # --- what main.py drives -------------------------------------------------

    def set_value(self, value):
        self.value = max(0, min(int(value), 10 ** self.DIGITS - 1))
        self.queue_draw()

    def set_message(self, heading, text, detail=None):
        if (heading, text, detail) == (self.heading, self.text, self._detail):
            return
        if text != self.text or heading != self.heading:
            self.since = time.monotonic()
        self.heading, self.text, self._detail = heading, text, detail
        self.get_accessible().set_description(detail or heading + "\n" + text)
        self.queue_draw()

    def analyze(self, row):
        """Feed one spectrum row; the analyzer shows the band around the tuning."""
        n = len(row)
        middle = row[n * 3 // 8:n * 5 // 8]
        count = len(self.bands)
        if len(middle) >= count:
            floor = float(sorted(row)[n // 2])
            step = len(middle) / count
            self.band_targets = [min(1.0, max(0.0, (float(max(middle[int(i * step):int((i + 1) * step)]))
                                                    - floor) / 40.0)) for i in range(count)]
            self.band_at = time.monotonic()
        return False

    # --- timing ----------------------------------------------------------------

    def _animated(self):
        return self.get_settings().get_property("gtk-enable-animations")

    def _mapped(self, *args):
        if self.born is None:
            self.born = time.monotonic()
        if self.timer is None:
            self.timer = GLib.timeout_add(TICK_MS, self._tick)

    def _unmapped(self, *args):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def _tick(self):
        self.queue_draw()
        return True

    def _ballistics(self, now):
        dt, self._last = min(now - self._last, .5), now
        target = self.level.value
        animate = self._animated()
        if not animate or target >= self.shown:
            self.shown = target
        else:
            self.shown = max(target, self.shown - 60 * dt)  # a meter falls, it doesn't drop
        if target >= self.peak or not animate:
            self.peak, self.peak_at = target, now
        elif now - self.peak_at > 1.5:
            self.peak = max(self.shown, self.peak - 40 * dt)
        live = self.band_targets if self.band_targets and now - self.band_at < .5 else None
        for i, value in enumerate(self.bands):
            want = live[i] if live else 0.0
            self.bands[i] = want if want >= value or not animate else max(want, value - 2.5 * dt)

    # --- composing the frame -----------------------------------------------------

    def _cols(self):
        return max(1, int((self.get_allocated_width() - 2 * PAD_X) / ADVANCE))

    @staticmethod
    def _cell_origin(row, col):
        return (PAD_X + col * ADVANCE + .07 * SIZE, PAD_Y + row * PITCH + (PITCH - GLYPH_H) / 2)

    def _put(self, row, col, text, alpha=1.0):
        for i, ch in enumerate(text):
            if col + i < self.ncols and ch != " ":
                self.cells[(row, col + i)] = (segments(ch), ch if ch in ".:," else "", alpha)

    def _put_segments(self, row, col, active, alpha=1.0):
        if col < self.ncols and active:
            self.cells[(row, col)] = (active, "", alpha)

    def _field(self, row, col, text, name=None, tip=None, alpha=1.0, enabled=True, width=None):
        width = width or len(text)
        self._put(row, col, text[:width], alpha if enabled else DIM)
        if name and col < self.ncols:
            self.zones.append(dict(name=name, row=row, col=col, width=min(width, self.ncols - col),
                                   tip=tip, enabled=enabled))
        return col + width + 1

    def _bars(self, row, col, cells, lit, peak=None, name=None, tip=None):
        """A horizontal bargraph of each cell's three uprights."""
        for cell in range(cells):
            active = ""
            for k, pair in enumerate(UPRIGHTS):
                index = cell * 3 + k
                if index < lit or index == peak:
                    active += "".join(pair)
            self._put_segments(row, col + cell, active)
        if name and col < self.ncols:
            self.zones.append(dict(name=name, row=row, col=col, width=min(cells, self.ncols - col),
                                   tip=tip, enabled=True))
        return col + cells + 1

    def _compose(self, now):
        win = self.win
        animate = self._animated()
        blink = not animate or int(now * 2) % 2 == 0
        self.ncols = self._cols()
        self.cells, self.zones, self.points = {}, [], []

        # Row 1: transport, gain, mode and step; the clock at the far end.
        running = win.start_button.get_active()
        col = self._field(0, 0, win.start_button.get_label().upper(), "start",
                          "Start or stop receiving (Ctrl+Space)", 1 if running else LABEL, width=5)
        recording = win.record_button.get_active()
        col = self._field(0, col, "REC", "record", "Record the audio to a WAV file (Ctrl+R)",
                          (1 if blink else LABEL) if recording else LABEL)
        col = self._field(0, col, "MUTE", "mute", "Mute (Ctrl+M)",
                          1 if win.mute_button.get_active() else LABEL)
        col = self._field(0, col + 1, "VOL", alpha=LABEL)
        adj = win.volume
        fraction = (adj.get_value() - adj.get_lower()) / (adj.get_upper() - adj.get_lower())
        col = self._bars(0, col, GAIN_CELLS, round(fraction * 3 * GAIN_CELLS), name="gain",
                         tip="Audio gain %+.1f dB: click, drag or scroll" % adj.get_value())
        mode = win.mode_combo.get_active_text() or ""
        enabled = win.mode_combo.get_sensitive()
        col = self._field(0, col + 1, display_text(MODE_TEXT.get(mode, mode)), "mode",
                          "Demodulator: %s" % mode if enabled else "HD uses its own decoder",
                          enabled=enabled, width=8)
        col = self._field(0, col + 1, "STEP", alpha=LABEL)
        step = display_text(win.step_combo.get_active_text() or "").replace(" ", "")
        col = self._field(0, col, step, "step", "Tuning step", width=7)
        clock = time.strftime("%H:%M")
        if self.ncols - 5 > col:
            self._put(0, self.ncols - 5, clock if blink else clock.replace(":", " "))

        # Row 2: signal, indicators, analyzer, direct entry, HD channel.
        col = self._field(1, 0, "SIG", alpha=LABEL)
        bars = 3 * METER_CELLS
        col = self._bars(1, col, METER_CELLS, round(self.shown / 100 * bars),
                         peak=min(bars - 1, round(self.peak / 100 * bars)) if self.peak > self.shown + 1 else None,
                         name="signal", tip=win.level_label.get_text())
        level = win.level_label.get_text()
        reading = "  --DB" if level.startswith("–") else "%.1fDB" % (self.level.value - 100)
        col = self._field(1, col, reading.rjust(8))
        stereo = win.stereo_label.get_text()
        col = self._field(1, col + 1, "ST", alpha=1 if stereo == "Stereo" else UNLIT_SIGN)
        col = self._field(1, col, "RDS", alpha=1 if self.rds_lit else UNLIT_SIGN)
        hd_alpha = 1 if stereo == "HD lock" else ((1 if blink else UNLIT_SIGN) if stereo == "HD seek"
                                                  else UNLIT_SIGN)
        col = self._field(1, col, "HD", alpha=hd_alpha)
        col += 1
        for cell in range(ANALYZER_CELLS):
            active = ""
            for k, (low, high) in enumerate(UPRIGHTS):
                level_k = self.bands[cell * 3 + k]
                active += (low if level_k > .12 else "") + (high if level_k > .55 else "")
            self._put_segments(1, col + cell, active)
        col += ANALYZER_CELLS + 2
        col = self._field(1, col, "GO", alpha=LABEL)
        if self.editing is not None:
            typed = (self.editing + ("_" if blink else " "))[-9:]
        else:
            typed = ""
        col = self._field(1, col, display_text(typed), "go",
                          "Type a frequency in MHz, then Enter", width=9)
        if win.hd_combo.get_visible():
            channel = display_text(win.hd_combo.get_active_text() or "HD1").split()[0]
            self._field(1, col, channel, "hd", "HD channel" if win.hd_combo.get_sensitive()
                        else "No other HD channel on this frequency",
                        enabled=win.hd_combo.get_sensitive(), width=3)

        # Row 3: frequency, station identity, then the scrolling text.
        col = self._frequency(2, 0)
        parts = [p.strip() for p in self.heading.split("·") if p.strip()] or [""]
        part = parts[int((now - self.since) / 2.5) % len(parts)] if animate else " ".join(parts)
        col = self._field(2, col + 1, display_text(part)[:8], alpha=.75, width=8)
        room = self.ncols - col
        if room > 0:
            self._field(2, col, self._marquee(room, now, animate), "station",
                        self._detail or self.heading + "\n" + self.text, width=room)

        if self.born is not None and animate and now - self.born < .7:
            # Power-on segment test: a sweep across the glass, once.
            reach = (now - self.born) / .5 * self.ncols
            for row in range(ROWS):
                for col in range(min(self.ncols, int(reach))):
                    self.cells[(row, col)] = (ALL, "", .45)

    def _marquee(self, room, now, animate):
        text = display_text(self.text)
        if not animate or not text:
            return text[:room]
        cycle = text.ljust(room) + "    " if len(text) < room else text + "    "
        start = int(max(0, now - self.since - 1.5) / .35) % len(cycle)
        return (cycle + cycle)[start:start + room]

    def _frequency(self, row, col):
        text = "%0*d" % (self.DIGITS, self.value)
        lit = [p for p, ch in zip(range(self.DIGITS - 1, -1, -1), text) if ch != "0"]
        # Read as MHz: only significant digits show, plus one blank cell after
        # them that lights while hovered or focused, so any finer digit stays
        # tunable. Coarser digits appear by carrying from the leading one.
        self.reach = (max(lit + [6]), max(min(lit + [5]) - 1, 0))
        focused = self.has_focus() and self.focus_zone == "freq"
        self.boxes = []
        start = col
        for place in range(self.reach[0], self.reach[1] - 1, -1):
            ch = text[self.DIGITS - 1 - place]
            shown = place != self.reach[1] or ch != "0" or place == 5 \
                or self.hover_place == place or (focused and self.focus_place == place)
            if shown:
                self._put(row, col, ch)
            x = PAD_X + col * ADVANCE
            self.boxes.append((x, x + ADVANCE, place))
            if place == 6 and col < self.ncols:
                self.points.append((row, col))  # the decimal point sits after this cell
            col += 1
        self.zones.append(dict(name="freq", row=row, col=start, width=col - start,
                               tip="Scroll over a digit, or click its top or bottom half, to tune",
                               enabled=True))
        self._put(row, col, "MHZ", LABEL)
        return col + 3

    # --- drawing ----------------------------------------------------------------

    def _ghost_layer(self, cr, width, height):
        key = (width, height)
        if self._ghost and self._ghost[0] == key:
            return self._ghost[1]
        surface = cr.get_target().create_similar(cairo.CONTENT_COLOR_ALPHA, width, height)
        g = cairo.Context(surface)
        g.new_sub_path()
        radius = 4
        for (cx, cy, a) in ((width - radius, radius, -math.pi / 2), (width - radius, height - radius, 0),
                            (radius, height - radius, math.pi / 2), (radius, radius, math.pi)):
            g.arc(cx, cy, radius, a, a + math.pi / 2)
        g.close_path()
        g.set_source_rgb(*GLASS)
        g.fill_preserve()
        g.set_source_rgb(.19, .18, .15)
        g.set_line_width(1.5)
        g.stroke()
        shine = cairo.LinearGradient(0, 0, 0, height)
        shine.add_color_stop_rgba(0, 1, 1, 1, .05)
        shine.add_color_stop_rgba(.5, 1, 1, 1, 0)
        g.rectangle(2, 2, width - 4, height / 2)
        g.set_source(shine)
        g.fill()
        g.set_line_width(stroke_width(GLYPH_H))
        g.set_source_rgb(*GHOST)
        for row in range(ROWS):
            for col in range(self._cols()):
                add_segments(g, ALL, *self._cell_origin(row, col), GLYPH_W, GLYPH_H)
        g.stroke()
        self._ghost = (key, surface)
        return surface

    def _draw(self, widget, cr):
        now = time.monotonic()
        self._ballistics(now)
        self._compose(now)
        width, height = self.get_allocated_width(), self.get_allocated_height()
        cr.set_source_surface(self._ghost_layer(cr, width, height), 0, 0)
        cr.paint()

        r, g, b = faceplate.LIT
        for zone in self.zones:
            hovered = zone["name"] == self.hover and zone["enabled"] and zone["name"] != "freq"
            if hovered:
                cr.set_source_rgba(r, g, b, .1)
                cr.rectangle(PAD_X + zone["col"] * ADVANCE, PAD_Y + zone["row"] * PITCH + 2,
                             zone["width"] * ADVANCE, PITCH - 4)
                cr.fill()
            if self.has_focus() and zone["name"] == self.focus_zone:
                cr.rectangle(PAD_X + zone["col"] * ADVANCE, PAD_Y + (zone["row"] + 1) * PITCH - 3,
                             zone["width"] * ADVANCE - (ADVANCE - GLYPH_W) / 2, 1)
                faceplate.glow(cr, 1, fill=True, alpha=.7)
        place = self.hover_place if self.hover_place is not None else (
            self.focus_place if self.has_focus() and self.focus_zone == "freq" else None)
        for left, right, p in self.boxes:
            if p == place:
                cr.set_source_rgba(r, g, b, .14)
                cr.rectangle(left, PAD_Y + 2 * PITCH + 2, right - left, PITCH - 4)
                cr.fill()

        width_line = stroke_width(GLYPH_H)
        groups = {}
        for (row, col), (active, dots, alpha) in self.cells.items():
            groups.setdefault(alpha, []).append((row, col, active, dots))
        for alpha, cells in sorted(groups.items()):
            cr.new_path()
            for row, col, active, _ in cells:
                add_segments(cr, active, *self._cell_origin(row, col), GLYPH_W, GLYPH_H)
            faceplate.glow(cr, width_line, alpha=alpha)
            cr.new_path()
            for row, col, _, dots in cells:
                if dots:
                    add_dots(cr, dots, *self._cell_origin(row, col), GLYPH_W, GLYPH_H)
            faceplate.glow(cr, 1, fill=True, alpha=alpha)
        cr.new_path()
        for row, col in self.points:
            x, y = self._cell_origin(row, col)
            cr.new_sub_path()
            cr.arc(x + GLYPH_W + (ADVANCE - GLYPH_W) / 2, y + GLYPH_H * .96,
                   max(1.5, GLYPH_H * .07), 0, 2 * math.pi)
        faceplate.glow(cr, 1, fill=True)
        return True

    # --- input -------------------------------------------------------------------

    def _zone_at(self, x, y):
        row = int((y - PAD_Y) // PITCH)
        col = int((x - PAD_X) // ADVANCE)
        for zone in self.zones:
            if zone["row"] == row and zone["col"] <= col < zone["col"] + zone["width"]:
                return zone
        return None

    def _place_at(self, x):
        for left, right, place in self.boxes:
            if left <= x < right:
                return place
        return None

    def _set_hover(self, name, place):
        if (name, place) != (self.hover, self.hover_place):
            self.hover, self.hover_place = name, place
            self.queue_draw()

    def _motion(self, widget, event):
        zone = self._zone_at(event.x, event.y)
        name = zone["name"] if zone and zone["enabled"] else None
        self._set_hover(name, self._place_at(event.x) if name == "freq" else None)
        if self._drag:
            self._gain_at(event.x)
        return False

    def _press(self, widget, event):
        zone = self._zone_at(event.x, event.y)
        if event.button != 1 or not zone or not zone["enabled"]:
            return False
        self.grab_focus()
        self.focus_zone = zone["name"]
        name = zone["name"]
        if name == "freq":
            place = self._place_at(event.x)
            if place is not None:
                self.focus_place = place
                middle = PAD_Y + zone["row"] * PITCH + PITCH / 2
                self._tune_by(10 ** place * (1 if event.y < middle else -1))
        elif name == "gain":
            self._drag = True
            self._gain_at(event.x)
        else:
            self._activate(name, zone)
        return True

    def _scroll(self, widget, event):
        zone = self._zone_at(event.x, event.y)
        if not zone or not zone["enabled"]:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            notches = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            notches = -1
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            self._scroll_carry -= event.delta_y
            notches = int(self._scroll_carry)
            self._scroll_carry -= notches
        else:
            return False
        if notches:
            place = self._place_at(event.x) if zone["name"] == "freq" else None
            self._adjust(zone["name"], notches, place)
        return True

    def _focusable(self):
        return [z for z in self.zones if z["enabled"]]

    def _key(self, widget, event):
        key = event.keyval
        if self.editing is not None:
            return self._edit_key(event)
        zones = self._focusable()
        names = [z["name"] for z in zones]
        if self.focus_zone not in names and names:
            self.focus_zone = names[0]
        if key in (Gdk.KEY_Left, Gdk.KEY_Right):
            forward = key == Gdk.KEY_Right
            if self.focus_zone == "freq":
                place = self.focus_place if self.focus_place in range(self.reach[1], self.reach[0] + 1) \
                    else self.reach[1] + 1
                place += -1 if forward else 1
                if self.reach[1] <= place <= self.reach[0]:
                    self.focus_place = place
                    self.queue_draw()
                    return True
            index = names.index(self.focus_zone) + (1 if forward else -1)
            if 0 <= index < len(names):
                self.focus_zone = names[index]
                if self.focus_zone == "freq":
                    self.focus_place = self.reach[0] if forward else self.reach[1] + 1
                self.queue_draw()
                return True
            return False
        if key in (Gdk.KEY_Up, Gdk.KEY_Down):
            place = None
            if self.focus_zone == "freq":
                if self.focus_place is None:
                    self.focus_place = self.reach[1] + 1
                place = self.focus_place
            self._adjust(self.focus_zone, 1 if key == Gdk.KEY_Up else -1, place)
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            zone = next((z for z in zones if z["name"] == self.focus_zone), None)
            if zone:
                self._activate(zone["name"], zone)
                return True
        return False

    def _tooltip(self, widget, x, y, keyboard, tooltip):
        zone = next((z for z in self.zones if z["name"] == self.focus_zone), None) if keyboard \
            else self._zone_at(x, y)
        if not zone or not zone["tip"]:
            return False
        tooltip.set_text(zone["tip"])
        tooltip.set_tip_area(self._zone_rect(zone))
        return True

    @staticmethod
    def _zone_rect(zone):
        rect = Gdk.Rectangle()
        rect.x = round(PAD_X + zone["col"] * ADVANCE)
        rect.y = round(PAD_Y + zone["row"] * PITCH)
        rect.width = round(zone["width"] * ADVANCE)
        rect.height = round(PITCH)
        return rect

    # --- actions -----------------------------------------------------------------

    def _toggle(self, button):
        button.set_active(not button.get_active())

    def _activate(self, name, zone):
        win = self.win
        if name == "start":
            self._toggle(win.start_button)
        elif name == "record":
            self._toggle(win.record_button)
        elif name == "mute":
            self._toggle(win.mute_button)
        elif name in ("mode", "step", "hd"):
            self.menu = self._popup(self._combo(name), zone)
        elif name == "go":
            self.editing = ""
        self.queue_draw()

    def _combo(self, name):
        return {"mode": self.win.mode_combo, "step": self.win.step_combo, "hd": self.win.hd_combo}[name]

    def _adjust(self, name, notches, place=None):
        if name == "freq" and place is not None:
            self._tune_by(notches * 10 ** place)
        elif name == "gain":
            self.win.volume.set_value(self.win.volume.get_value() + notches)
        elif name in ("mode", "step", "hd"):
            combo = self._combo(name)
            count = len(combo.get_model())
            index = combo.get_active() + notches
            if count and 0 <= index < count:
                combo.set_active(index)
        self.queue_draw()

    def _tune_by(self, delta):
        value = max(1000, min(self.value + delta, 10 ** self.DIGITS - 1))
        if value != self.value:
            self.set_value(value)
            self.emit("changed", value)

    def _gain_at(self, x):
        zone = next((z for z in self.zones if z["name"] == "gain"), None)
        if zone:
            fraction = (x - PAD_X - zone["col"] * ADVANCE) / (zone["width"] * ADVANCE)
            adj = self.win.volume
            adj.set_value(adj.get_lower() + max(0, min(1, fraction)) * (adj.get_upper() - adj.get_lower()))
            self.queue_draw()

    def _popup(self, combo, zone):
        menu = Gtk.Menu()
        menu.set_name("tuner-menu")
        active = combo.get_active()
        for index, row in enumerate(combo.get_model()):
            item = Gtk.CheckMenuItem(label=display_text(row[0]))
            item.set_draw_as_radio(True)
            item.set_active(index == active)
            # set_active above emits activate; connect only afterwards.
            item.connect("activate", lambda _i, n=index: combo.set_active(n))
            menu.append(item)
        menu.show_all()
        menu.attach_to_widget(self, None)
        menu.popup_at_rect(self.get_window(), self._zone_rect(zone),
                           Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        return menu

    def _edit_key(self, event):
        key = event.keyval
        char = chr(Gdk.keyval_to_unicode(key)) if Gdk.keyval_to_unicode(key) else ""
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            text, self.editing = self.editing, None
            if text:
                self.emit("go", text)
        elif key == Gdk.KEY_Escape:
            self.editing = None
        elif key == Gdk.KEY_BackSpace:
            self.editing = self.editing[:-1]
        elif char and (char.isdigit() or char in ".,") and len(self.editing) < 12:
            self.editing += "." if char == "," else char
        elif key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.editing = None
            return False
        self.queue_draw()
        return True

    def _end_edit(self):
        self.editing = None
        self._drag = False
        self.queue_draw()
        return False

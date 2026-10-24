"""Custom-drawn widgets: the frequency dial and the spectrum/waterfall."""

import math
import time

import cairo
import numpy as np
from gi.repository import Gdk, GObject, Gtk, Pango, PangoCairo

from rdsview import RdsDisplay

ORANGE = (0.941, 0.467, 0.275)  # Ubuntu's selection orange


def _plasma_lut():
    anchors = np.array([
        [0.00, 13, 8, 135], [0.25, 126, 3, 168], [0.50, 204, 71, 120],
        [0.75, 248, 149, 64], [1.00, 240, 249, 33]], dtype=np.float64)
    x = np.linspace(0, 1, 256)
    rgb = [np.interp(x, anchors[:, 0], anchors[:, i]) for i in (1, 2, 3)]
    # Fade the bottom of the scale into black so the noise floor stays quiet.
    fade = np.clip(x / 0.18, 0, 1)
    r, g, b = (np.round(c * fade).astype(np.uint32) for c in rgb)
    return (r << 16) | (g << 8) | b


def _colour_lut(anchors):
    anchors = np.asarray(anchors, dtype=float)
    x = np.linspace(0, 1, 256)
    r, g, b = (np.round(np.interp(x, anchors[:, 0], anchors[:, i])).astype(np.uint32)
               for i in (1, 2, 3))
    return (r << 16) | (g << 8) | b


COLOUR_MAPS = {
    "Plasma": _plasma_lut(),
    "Grey": _colour_lut([(0, 0, 0, 0), (1, 255, 255, 255)]),
    "Ice": _colour_lut([(0, 0, 0, 0), (.35, 0, 30, 150), (.7, 0, 200, 255), (1, 255, 255, 255)]),
    "Fire": _colour_lut([(0, 0, 0, 0), (.35, 150, 0, 0), (.7, 255, 150, 0), (1, 255, 255, 230)]),
}
DISPLAY_DEFAULTS = {
    "colour_map": "Plasma", "intensity_db": 0.0, "contrast": 1.0,
    "line_interval": 0.0, "spectrum_percent": 32.0, "smoothing": 60.0,
    "peak_decay": 0.15, "show_grid": True, "fill_trace": True,
    "show_bookmarks": True, "show_filter": True, "show_tuning_line": True,
    "show_crosshair": True,
}


class FrequencyDial(Gtk.DrawingArea):
    """gqrx-style dial: scroll a digit, or click its upper/lower half."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_INT64,))}
    DIGITS = 10  # up to 9.999 999 999 GHz

    def __init__(self):
        super().__init__()
        self.value = 100000000
        self.hover = None
        self.boxes = []
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.set_size_request(360, 48)
        self.set_tooltip_text("Scroll over a digit, or click its top or bottom half, to tune")
        self.connect("draw", self._draw)
        self.connect("scroll-event", self._scroll)
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("leave-notify-event", lambda *a: self._set_hover(None))
        self.connect("key-press-event", self._key)
        self._scroll_carry = 0.0

    def set_value(self, value):
        value = max(0, min(int(value), 10 ** self.DIGITS - 1))
        if value != self.value:
            self.value = value
            self.queue_draw()

    def _emit(self, value):
        value = max(1000, min(int(value), 10 ** self.DIGITS - 1))
        if value != self.value:
            self.set_value(value)
            self.emit("changed", value)

    def _draw(self, widget, cr):
        alloc = self.get_allocation()
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription("Ubuntu Mono Bold")
        font.set_absolute_size(alloc.height * 0.72 * Pango.SCALE)
        layout.set_font_description(font)
        layout.set_text("0", -1)
        digit_w, digit_h = layout.get_pixel_size()
        sep_w = digit_w * 0.45
        unit = "Hz"
        small = Pango.FontDescription("Tuner Segment")
        small.set_absolute_size(alloc.height * 0.28 * Pango.SCALE)
        total = self.DIGITS * digit_w + 3 * sep_w + digit_w * 1.6
        x = (alloc.width - total) / 2
        y = (alloc.height - digit_h) / 2
        text = "%0*d" % (self.DIGITS, self.value)
        leading = True
        self.boxes = []
        for i, ch in enumerate(text):
            place = self.DIGITS - 1 - i
            if ch != "0" or place < 7:
                leading = False
            if self.hover == place:
                cr.set_source_rgba(*ORANGE, 0.25)
                cr.rectangle(x, 3, digit_w, alloc.height - 6)
                cr.fill()
            RdsDisplay._glyph(cr, " " if leading else ch, x + 3, y + 6,
                              digit_w - 6, digit_h - 12)
            self.boxes.append((x, x + digit_w, place))
            x += digit_w
            if place in (9, 6, 3):
                cr.set_source_rgba(1, .60, .16, 0.08 if leading else 0.8)
                cr.arc(x + sep_w / 2, y + digit_h * 0.82, max(digit_w * 0.08, 1.5), 0, 2 * math.pi)
                cr.fill()
                x += sep_w
        layout.set_font_description(small)
        layout.set_text(unit, -1)
        cr.set_source_rgb(*ORANGE)
        cr.move_to(x + digit_w * 0.3, y + digit_h * 0.55)
        PangoCairo.show_layout(cr, layout)
        return True

    def _place_at(self, x):
        for left, right, place in self.boxes:
            if left <= x < right:
                return place
        return None

    def _set_hover(self, place):
        if place != self.hover:
            self.hover = place
            self.queue_draw()

    def _motion(self, widget, event):
        self._set_hover(self._place_at(event.x))

    def _press(self, widget, event):
        self.grab_focus()
        place = self._place_at(event.x)
        if place is None or event.button != 1:
            return False
        step = 10 ** place
        up = event.y < self.get_allocated_height() / 2
        self._emit(self.value + (step if up else -step))
        return True

    def _scroll(self, widget, event):
        place = self._place_at(event.x)
        if place is None:
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
            self._emit(self.value + notches * 10 ** place)
        return True

    def _key(self, widget, event):
        place = self.hover if self.hover is not None else 3
        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            self._emit(self.value + 10 ** place)
        elif event.keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self._emit(self.value - 10 ** place)
        elif event.keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            self._set_hover(min(self.DIGITS - 1, max(0, place + (1 if event.keyval == Gdk.KEY_Left else -1))))
        else:
            return False
        return True


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class SpectrumView(Gtk.DrawingArea):
    """Spectrum trace above a scrolling waterfall. Click or scroll to tune."""

    __gsignals__ = {"tune": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_INT64,)),
                    "step": (GObject.SignalFlags.RUN_FIRST, None, (int,))}
    HISTORY = 600

    def __init__(self):
        super().__init__()
        self.rows = None  # HISTORY x bins, dB
        self.head = 0
        self.count = 0
        self.center = 0
        self.rate = 1
        self.freq = 0
        self.filter = (-80000, 80000)
        self.zoom = 1
        for key, value in DISPLAY_DEFAULTS.items():
            setattr(self, key, value)
        self.waterfall_paused = False
        self._pending_row = None
        self._last_line = None
        self.floor = -80.0
        self.range_db = 60.0
        self.auto_range = True
        self.trace = None
        self.peak = None
        self.peak_hold = True
        self.bookmarks = []  # (freq, name, colour)
        self.hover_x = None
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK
                        | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.set_size_request(400, 260)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("scroll-event", self._scroll)
        self.connect("motion-notify-event", self._motion)
        self.connect("leave-notify-event", self._leave)
        self._scroll_carry = 0.0

    def clear(self):
        self.rows, self.count, self.trace, self.peak = None, 0, None, None
        self.head = 0
        self._pending_row = None
        self._last_line = None
        self.queue_draw()

    def clear_waterfall(self):
        self.count = 0
        self._pending_row = None
        self._last_line = None
        self.queue_draw()

    def pause_waterfall(self, paused):
        self.waterfall_paused = paused
        self._pending_row = None
        self._last_line = None

    def push(self, row, center, rate):
        if self.rows is None or self.rows.shape[1] != len(row):
            self.rows = np.full((self.HISTORY, len(row)), -150.0, dtype=np.float32)
            self.count = 0
            self.trace = None
            self.peak = None
            self._pending_row = None
            self._last_line = None
        if center != self.center or rate != self.rate:
            self.peak = None
            self._pending_row = None
        self.center, self.rate = center, rate
        if not self.waterfall_paused:
            now = time.monotonic()
            # Keep brief signals visible when several updates share one line.
            self._pending_row = row.copy() if self._pending_row is None else np.maximum(self._pending_row, row)
            if self._last_line is None or now - self._last_line >= self.line_interval:
                self.head = (self.head + 1) % self.HISTORY
                self.rows[self.head] = self._pending_row
                self.count = min(self.count + 1, self.HISTORY)
                self._pending_row = None
                self._last_line = now
        weight = self.smoothing / 100.0
        first_trace = self.trace is None
        self.trace = row.copy() if first_trace else weight * self.trace + (1 - weight) * row
        if self.peak_hold:
            self.peak = self.trace.copy() if self.peak is None else np.maximum(self.peak - self.peak_decay, self.trace)
        if self.auto_range:
            floor = float(np.percentile(row, 20)) - 6
            self.floor = 0.95 * self.floor + 0.05 * floor if not first_trace else floor
        self.queue_draw()

    # Geometry -----------------------------------------------------------

    def span(self):
        """(low, high) Hz shown across the widget."""
        width = self.rate / self.zoom
        centre = self.center if self.zoom == 1 else self.freq
        low = max(self.center - self.rate / 2, min(centre - width / 2, self.center + self.rate / 2 - width))
        return low, low + width

    def x_of(self, freq, width):
        low, high = self.span()
        return (freq - low) / (high - low) * width

    def freq_of(self, x, width):
        low, high = self.span()
        return low + x / max(width, 1) * (high - low)

    # Drawing ------------------------------------------------------------

    def _draw(self, widget, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        top = int(h * self.spectrum_percent / 100.0)
        cr.set_source_rgb(0.07, 0.07, 0.065)
        cr.paint()
        if self.rows is None or self.rate <= 1:
            self._message(cr, w, h, "Not receiving")
            return True
        low, high = self.span()
        bins = self.rows.shape[1]
        first = (low - (self.center - self.rate / 2)) / self.rate * bins
        last = (high - (self.center - self.rate / 2)) / self.rate * bins
        index = np.clip(np.linspace(first, last, w, endpoint=False).astype(int), 0, bins - 1)
        self._waterfall(cr, w, h, top, index)
        self._spectrum(cr, w, top, index)
        self._overlays(cr, w, h, top)
        return True

    def _waterfall(self, cr, w, h, top, index):
        rows = h - top
        if rows <= 0:
            return
        count = min(self.count, rows)
        order = (self.head - np.arange(count)) % self.HISTORY
        data = self.rows[order][:, index]
        normalized = np.clip((data - self.floor + self.intensity_db) / self.range_db, 0, 1)
        level = (normalized ** self.contrast * 255).astype(np.uint8)
        pixels = np.zeros((rows, w), dtype=np.uint32)
        pixels[:count] = COLOUR_MAPS[self.colour_map][level]
        surface = cairo.ImageSurface.create_for_data(memoryview(pixels), cairo.FORMAT_RGB24, w, rows, w * 4)
        cr.set_source_surface(surface, 0, top)
        cr.paint()

    def _spectrum(self, cr, w, top, index):
        cr.save()
        cr.rectangle(0, 0, w, top)
        cr.clip()
        cr.set_source_rgb(0.05, 0.05, 0.048)
        cr.paint()
        # Grid: dB lines every 10 dB, frequency lines at a round step.
        cr.set_line_width(1)
        cr.set_source_rgba(1, 1, 1, 0.08)
        if self.show_grid:
            for db in range(int(self.floor // 10 * 10), int(self.floor + self.range_db) + 1, 10):
                y = self._y(db, top)
                cr.move_to(0, int(y) + 0.5)
                cr.line_to(w, int(y) + 0.5)
            cr.stroke()
        low, high = self.span()
        step = _nice_step((high - low) / 8)
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription("Ubuntu 8")
        layout.set_font_description(font)
        f = math.ceil(low / step) * step
        while f < high:
            x = int(self.x_of(f, w)) + 0.5
            cr.set_source_rgba(1, 1, 1, 0.08)
            if self.show_grid:
                cr.move_to(x, 0)
                cr.line_to(x, top)
                cr.stroke()
            cr.set_source_rgba(1, 1, 1, 0.55)
            layout.set_text(_mhz(f, step), -1)
            tw, th = layout.get_pixel_size()
            cr.move_to(x - tw / 2, top - th - 2)
            PangoCairo.show_layout(cr, layout)
            f += step
        if self.peak is not None and self.peak_hold:
            self._trace(cr, self.peak[index], top, (1, 1, 1, 0.25))
        if self.trace is not None:
            values = self.trace[index]
            self._trace(cr, values, top, (0.85, 0.85, 0.82, 0.95), fill=self.fill_trace)
        cr.restore()

    def _trace(self, cr, values, top, colour, fill=False):
        ys = self._y(values, top)
        cr.move_to(0, ys[0])
        for x in range(1, len(ys)):
            cr.line_to(x, ys[x])
        if fill:
            path = cr.copy_path()
            cr.line_to(len(ys) - 1, top)
            cr.line_to(0, top)
            cr.close_path()
            cr.set_source_rgba(colour[0], colour[1], colour[2], 0.12)
            cr.fill()
            cr.append_path(path)
        cr.set_source_rgba(*colour)
        cr.set_line_width(1)
        cr.stroke()

    def _y(self, db, top):
        return top - (np.asarray(db) - self.floor) / self.range_db * (top - 14) - 14

    def _overlays(self, cr, w, h, top):
        if self.show_filter:
            x0 = self.x_of(self.freq + self.filter[0], w)
            x1 = self.x_of(self.freq + self.filter[1], w)
            cr.set_source_rgba(*ORANGE, 0.16)
            cr.rectangle(min(x0, x1), 0, max(abs(x1 - x0), 1), top)
            cr.fill()
        if self.show_tuning_line:
            cr.set_source_rgba(*ORANGE, 0.9)
            cr.set_line_width(1)
            x = int(self.x_of(self.freq, w)) + 0.5
            cr.move_to(x, 0)
            cr.line_to(x, h)
            cr.stroke()
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription("Ubuntu 8"))
        low, high = self.span()
        for freq, name, colour in (self.bookmarks if self.show_bookmarks else []):
            if not low <= freq <= high:
                continue
            bx = int(self.x_of(freq, w)) + 0.5
            rgba = Gdk.RGBA()
            rgba.parse(colour)
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.8)
            cr.move_to(bx, 0)
            cr.line_to(bx, 8)
            cr.stroke()
            layout.set_text(name, -1)
            cr.move_to(bx + 2, 0)
            PangoCairo.show_layout(cr, layout)
        if self.show_crosshair and self.hover_x is not None:
            f = self.freq_of(self.hover_x, w)
            layout.set_text("%.4f MHz" % (f / 1e6), -1)
            tw, th = layout.get_pixel_size()
            tx = min(self.hover_x + 6, w - tw - 4)
            cr.set_source_rgba(0, 0, 0, 0.7)
            cr.rectangle(tx - 3, top + 3, tw + 6, th + 2)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(tx, top + 4)
            PangoCairo.show_layout(cr, layout)
            cr.set_source_rgba(1, 1, 1, 0.3)
            cr.move_to(int(self.hover_x) + 0.5, 0)
            cr.line_to(int(self.hover_x) + 0.5, h)
            cr.stroke()

    def _message(self, cr, w, h, text):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription("Ubuntu 11"))
        layout.set_text(text, -1)
        tw, th = layout.get_pixel_size()
        cr.set_source_rgba(1, 1, 1, 0.45)
        cr.move_to((w - tw) / 2, (h - th) / 2)
        PangoCairo.show_layout(cr, layout)

    # Input --------------------------------------------------------------

    def _press(self, widget, event):
        if event.button == 1 and self.rows is not None:
            self.emit("tune", int(self.freq_of(event.x, self.get_allocated_width())))
            return True
        return False

    def _scroll(self, widget, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.emit("step", 1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.emit("step", -1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            self._scroll_carry -= event.delta_y
            n = int(self._scroll_carry)
            self._scroll_carry -= n
            if n:
                self.emit("step", n)
        return True

    def _motion(self, widget, event):
        self.hover_x = event.x
        self.queue_draw()

    def _leave(self, widget, event):
        self.hover_x = None
        self.queue_draw()


def _nice_step(raw):
    exp = 10 ** math.floor(math.log10(max(raw, 1)))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * exp:
            return m * exp
    return 10 * exp


def _mhz(freq, step):
    decimals = max(0, min(6, int(math.ceil(-math.log10(step / 1e6))) if step < 1e6 else 0))
    return "%.*f" % (decimals, freq / 1e6)

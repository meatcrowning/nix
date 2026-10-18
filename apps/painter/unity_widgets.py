# -*- coding: utf-8 -*-
"""GTK 3.6 / Python 2.7 widgets for Painter's Unity face."""
from __future__ import unicode_literals
import threading
try:
    import Queue as queue
except ImportError:
    import queue
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango, GObject


class CompactSpin(Gtk.SpinButton):
    """Size the entry for its visible value, retaining native stepper space."""
    def do_get_preferred_width(self):
        entry = Gtk.Entry.do_get_preferred_width(self)
        height = Gtk.SpinButton.do_get_preferred_height(self)[0]
        return tuple(width + 2 * height for width in entry)

    def do_get_preferred_width_for_height(self, height):
        return self.do_get_preferred_width()


class PreviewDivider(Gtk.Paned):
    def __init__(self):
        Gtk.Paned.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.set_name('painter-preview-divider')
        css = Gtk.CssProvider()
        css.load_from_data(b'#painter-preview-divider { -GtkPaned-handle-size: 10; }')
        self.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.connect_after('draw', self.draw_grip)

    def draw_grip(self, widget, cr):
        colour = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(colour.red, colour.green, colour.blue, .8)
        x, y = self.get_allocated_width() / 2, self.get_position() + 4
        for offset in (-6, 0, 6):
            cr.rectangle(x + offset - 1, y, 3, 2)
        cr.fill()
        return False


class HistoryGrid(Gtk.IconView):
    """Fit whole thumbnail columns to the viewport with small, uniform gaps."""
    def __init__(self, model):
        Gtk.IconView.__init__(self, model=model)
        self.cell_width = 150
        self.pending_fit = None
        self.fitted_width = 0
        self.set_pixbuf_column(0)
        # GTK 3.6's built-in text column forces labels to twice the icon width.
        # An explicit renderer keeps filenames within their thumbnail column.
        self.name_cell = Gtk.CellRendererText()
        self.name_cell.set_property('width', self.cell_width)
        self.name_cell.set_property('xalign', .5)
        self.pack_start(self.name_cell, False)
        self.add_attribute(self.name_cell, 'text', 1)
        self.set_item_width(self.cell_width)
        self.set_margin(4)
        self.set_item_padding(3)
        self.set_column_spacing(4)
        self.set_row_spacing(4)
        self.set_spacing(3)
        for cell in self.get_cells():
            cell.set_property('xpad', 0)
            cell.set_property('ypad', 0)
            if isinstance(cell, Gtk.CellRendererText):
                cell.set_property('ellipsize', Pango.EllipsizeMode.END)
                cell.set_property('wrap-width', -1)
                cell.set_property('single-paragraph-mode', True)
                cell.set_property('height', self.create_pango_layout('Ag').get_pixel_size()[1] + 4)
        self.connect('size-allocate', self.resized)
        self.connect('destroy', self.destroyed)

    def focus_width(self):
        value = GObject.Value()
        value.init(GObject.TYPE_INT)
        self.style_get_property('focus-line-width', value)
        return value.get_int()

    def thumbnail(self, original):
        if original is None:
            return None
        scale = float(self.cell_width) / max(original.get_width(), original.get_height())
        return original.scale_simple(max(1, int(round(original.get_width() * scale))),
                                     max(1, int(round(original.get_height() * scale))),
                                     GdkPixbuf.InterpType.BILINEAR)

    def resized(self, widget, allocation):
        if allocation.width != self.fitted_width and self.pending_fit is None:
            self.pending_fit = GLib.idle_add(self.fit)

    def fit(self):
        self.pending_fit = None
        width = self.get_allocated_width()
        self.fitted_width = width
        available = max(1, width - 2 * self.get_margin())
        # GtkCellArea adds focus-line-width on both sides of each renderer.
        padding = 2 * (self.get_item_padding() + self.focus_width())
        gap = self.get_column_spacing()
        columns = max(1, (available + gap) // (150 + padding + gap))
        cell_width = max(32, (available - (columns - 1) * gap) // columns - padding)
        if cell_width != self.cell_width:
            self.cell_width = cell_width
            self.set_item_width(cell_width)
            self.name_cell.set_property('width', cell_width)
            for row in self.get_model():
                if row[3] is not None:
                    row[0] = self.thumbnail(row[3])
        return False

    def destroyed(self, *_):
        if self.pending_fit is not None:
            GLib.source_remove(self.pending_fit)
            self.pending_fit = None


class ResizableText(Gtk.Box):
    def __init__(self, height, saved):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.saved = saved
        self.drag = None
        self.text = Gtk.TextView()
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_shadow_type(Gtk.ShadowType.IN)
        self.scroll.add(self.text)
        self.pack_start(self.scroll, False, False, 0)
        self.handle = Gtk.EventBox()
        self.handle.set_tooltip_text('Drag to resize the text box')
        grip = Gtk.Label(label='⋯')
        grip.set_size_request(-1, 10)
        self.handle.add(grip)
        self.pack_start(self.handle, False, False, 0)
        self.handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                               Gdk.EventMask.POINTER_MOTION_MASK)
        self.handle.connect('realize', lambda w: w.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.SB_V_DOUBLE_ARROW)))
        self.handle.connect('button-press-event', self.press)
        self.handle.connect('motion-notify-event', self.motion)
        self.handle.connect('button-release-event', self.release)
        self.set_height(height)

    def set_height(self, height):
        self.height = max(40, min(600, int(height)))
        self.scroll.set_size_request(-1, self.height)

    def press(self, widget, event):
        if event.button != 1:
            return False
        self.drag = (event.y_root, self.height)
        widget.grab_add()
        return True

    def motion(self, widget, event):
        if self.drag:
            self.set_height(self.drag[1] + event.y_root - self.drag[0])
            return True
        return False

    def release(self, widget, event):
        if event.button != 1 or not self.drag:
            return False
        self.motion(widget, event)
        self.drag = None
        widget.grab_remove()
        self.saved(self.height)
        return True


class ImageView(Gtk.Box):
    """One current image across Browse and View; literal zoom and scroll pan."""
    def __init__(self, error, playback):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.error, self.playback = error, playback
        self.original = self.before = None
        self.path = None
        self.serial = 0
        self.zoom = 0.0
        self.scale = 1.0
        self.video = False
        self.natural_size = None
        self.duration = 0
        self.zoom_buttons = []
        self.drag = None
        self.render_timer = None
        self.rendering = False
        self.viewport_size = None
        self.zoom_anchor = None
        self.zoom_idle = None
        self.image_origin = (0, 0)
        self.visible_origin = (0, 0)
        self.crop_key = None
        self.crop_bounds = (0, 0, 0, 0)
        self.picture = Gtk.Image()
        self.events = Gtk.EventBox()
        self.events.add(self.picture)
        self.events.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.BUTTON_PRESS_MASK |
                               Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.events.connect('scroll-event', self.wheel)
        self.events.connect('button-press-event', self.press)
        self.events.connect('motion-notify-event', self.motion)
        self.events.connect('button-release-event', self.release)
        self.events.connect('realize', lambda w: w.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.HAND1)))
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.canvas = Gtk.Layout()
        self.canvas.put(self.events, 0, 0)
        self.scroll.add(self.canvas)
        self.scroll.get_hadjustment().connect('value-changed', self.scrolled)
        self.scroll.get_vadjustment().connect('value-changed', self.scrolled)
        self.scroll.connect('size-allocate', self.resized)
        self.canvas.connect('size-allocate', self.resized)
        self.pack_start(self.scroll, True, True, 0)
        bar = Gtk.Box(spacing=6)
        self.info = Gtk.Label(label='Select an output')
        self.info.set_alignment(0, .5)
        bar.pack_start(self.info, True, True, 0)
        for title, callback in [('−', lambda: self.zoom_by(1 / 1.25)),
                                ('+', lambda: self.zoom_by(1.25)),
                                ('Fit', lambda: self.set_zoom(0)),
                                ('1:1', lambda: self.set_zoom(1))]:
            button = Gtk.Button(label=title)
            button.connect('clicked', lambda _w, fn=callback: fn())
            bar.pack_start(button, False, False, 0)
            self.zoom_buttons.append(button)
        self.pack_start(bar, False, False, 0)
        self.compare = Gtk.HScale.new_with_range(0, 100, 1)
        self.compare.set_value(50)
        self.compare.set_draw_value(False)
        self.compare.set_tooltip_text('Before / after')
        self.compare.set_no_show_all(True)
        self.compare.connect('value-changed', lambda *_: self.render())
        self.pack_start(self.compare, False, False, 0)
        # One decoder worker; rapidly walking outputs only retains the newest
        # pending request. GTK widgets are updated solely on the main thread.
        self.loads = queue.Queue()
        worker = threading.Thread(target=self.load_worker)
        worker.daemon = True
        worker.start()

    def load_worker(self):
        while True:
            item = self.loads.get()
            while not self.loads.empty():
                item = self.loads.get()
            serial, path, before = item
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                other = None
                if before:
                    try:
                        other = GdkPixbuf.Pixbuf.new_from_file(before)
                    except GLib.GError:
                        pass
                GLib.idle_add(self.loaded, serial, pixbuf, other, '')
            except GLib.GError as exc:
                GLib.idle_add(self.loaded, serial, None, None, str(exc))

    def load(self, path, before='', video=False):
        if (path, before, video) == self.path:
            return
        self.path = (path, before, video)
        self.serial += 1
        self.zoom = 0.0
        self.zoom_anchor = None
        self.video = video
        self.natural_size = None
        for button in self.zoom_buttons:
            button.set_sensitive(not video)
        self.original = self.before = None
        self.picture.clear()
        self.canvas.set_size(1, 1)
        self.scroll.get_hadjustment().set_value(0)
        self.scroll.get_vadjustment().set_value(0)
        self.compare.hide()
        self.info.set_text('Loading…' if path else 'Waiting for a preview frame…')
        if path:
            self.loads.put((self.serial, path, before))

    def loaded(self, serial, pixbuf, before, error):
        if serial == self.serial:
            if error:
                self.info.set_text('Image unavailable')
                self.error(error, True)
            else:
                self.original, self.before = pixbuf, before
                self.compare.set_visible(before is not None)
                self.render()
        return False

    def frame(self, pixbuf, size=None, duration=0):
        self.natural_size = size
        self.duration = duration
        self.original = pixbuf
        self.render()

    def resized(self, *args):
        size = (self.canvas.get_allocated_width(), self.canvas.get_allocated_height())
        if args and size == self.viewport_size:
            return
        self.viewport_size = size
        if self.render_timer:
            GLib.source_remove(self.render_timer)
        self.render_timer = GLib.timeout_add(60, self.render)

    def scrolled(self, *args):
        # Both axes change during a drag. Drain input first, then scale only
        # the latest viewport once before GTK paints, not once per adjustment.
        if not self.rendering and self.render_timer is None:
            self.render_timer = GLib.idle_add(self.render, priority=GLib.PRIORITY_HIGH_IDLE)

    def render(self):
        if self.render_timer:
            GLib.source_remove(self.render_timer)
            self.render_timer = None
        if self.original is None or self.rendering:
            return False
        self.rendering = True
        w, h = self.original.get_width(), self.original.get_height()
        vw, vh = max(1, self.canvas.get_allocated_width()), max(1, self.canvas.get_allocated_height())
        self.scale = self.zoom or min(float(vw) / w, float(vh) / h)
        width, height = max(1, int(w * self.scale)), max(1, int(h * self.scale))
        # Keep a bounded overscan crop: native scrolling can expose its margin
        # immediately, without rescaling or waiting for a new child allocation.
        self.canvas.set_size(max(vw, width), max(vh, height))
        x, y = max(0, (vw - width) // 2), max(0, (vh - height) // 2)
        self.image_origin = (x, y)
        if self.zoom_anchor is not None:
            # Keep the anchor through GTK allocation: new scrollbars can change
            # the viewport after the first render. User panning clears it.
            ix, iy, cx, cy = self.zoom_anchor
            for adjustment, target in (
                    (self.scroll.get_hadjustment(), x + ix * self.scale - cx),
                    (self.scroll.get_vadjustment(), y + iy * self.scale - cy)):
                adjustment.set_value(max(0, min(adjustment.get_upper() -
                                               adjustment.get_page_size(), target)))
        sx = int(self.scroll.get_hadjustment().get_value())
        sy = int(self.scroll.get_vadjustment().get_value())
        left, top = max(x, sx), max(y, sy)
        right, bottom = min(x + width, sx + vw), min(y + height, sy + vh)
        key = (self.original, self.before, self.scale, x, y, width, height,
               vw, vh, self.compare.get_value())
        cl, ct, cr, cb = self.crop_bounds
        # Refresh before reaching the cached edge, while the old crop still
        # covers the viewport during GTK's asynchronous child allocation.
        covered = (max(x, left - vw // 4) >= cl and max(y, top - vh // 4) >= ct
                   and min(x + width, right + vw // 4) <= cr
                   and min(y + height, bottom + vh // 4) <= cb)
        if key != self.crop_key or not covered:
            left, top = max(x, left - vw), max(y, top - vh)
            right, bottom = min(x + width, right + vw), min(y + height, bottom + vh)
            rw, rh = max(1, right - left), max(1, bottom - top)
            pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, rw, rh)
            pixbuf.fill(0)
            self.original.scale(pixbuf, 0, 0, rw, rh, x - left, y - top,
                                self.scale, self.scale, GdkPixbuf.InterpType.BILINEAR)
            if self.before is not None:
                cut = min(rw, max(0, x + int(width * self.compare.get_value() / 100) - left))
                if cut:
                    self.before.scale(pixbuf, 0, 0, cut, rh, x - left, y - top,
                                      float(width) / self.before.get_width(),
                                      float(height) / self.before.get_height(), GdkPixbuf.InterpType.BILINEAR)
            self.crop_key = key
            self.crop_bounds = (left, top, right, bottom)
            self.visible_origin = (left, top)
            self.canvas.move(self.events, left, top)
            self.picture.set_from_pixbuf(pixbuf)
        nw, nh = self.natural_size or (w, h)
        self.info.set_text('%d × %d  ·  %d%%%s' % (nw, nh, round(self.scale * w / nw * 100),
                           '  ·  %.1fs  ·  Click to play / pause' % (self.duration / 1000.0) if self.video else ''))
        self.rendering = False
        return False

    def set_zoom(self, value, cursor=None):
        if self.video:
            return
        self.zoom_anchor = None
        if value and self.original is not None:
            cx, cy = cursor or (self.canvas.get_allocated_width() / 2.0,
                                self.canvas.get_allocated_height() / 2.0)
            self.zoom_anchor = (
                (cx + self.scroll.get_hadjustment().get_value() - self.image_origin[0]) / self.scale,
                (cy + self.scroll.get_vadjustment().get_value() - self.image_origin[1]) / self.scale,
                cx, cy)
        self.zoom = max(.05, min(16, value)) if value else 0.0
        self.render()
        if self.zoom_idle is not None:
            GLib.source_remove(self.zoom_idle)
        self.zoom_idle = GLib.idle_add(self.finish_zoom, priority=GLib.PRIORITY_LOW)

    def finish_zoom(self):
        # GTK updates adjustment bounds and scrollbar allocations asynchronously.
        self.zoom_idle = None
        self.render()
        self.zoom_anchor = None
        return False

    def zoom_by(self, factor, cursor=None):
        self.set_zoom(self.scale * factor, cursor)

    def wheel(self, widget, event):
        # Events are local to the cropped bitmap, not the full image or viewport.
        cursor = (event.x + self.visible_origin[0] - self.scroll.get_hadjustment().get_value(),
                  event.y + self.visible_origin[1] - self.scroll.get_vadjustment().get_value())
        if event.direction == Gdk.ScrollDirection.UP:
            self.zoom_by(1.25, cursor)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.zoom_by(1 / 1.25, cursor)
        return True

    def press(self, widget, event):
        if event.button != 1:
            return False
        self.drag = (event.x_root, event.y_root, self.scroll.get_hadjustment().get_value(),
                     self.scroll.get_vadjustment().get_value())
        widget.grab_add()
        return True

    def motion(self, widget, event):
        if not self.drag or self.video:
            return False
        self.zoom_anchor = None
        for adjustment, start, now, value in [
                (self.scroll.get_hadjustment(), self.drag[0], event.x_root, self.drag[2]),
                (self.scroll.get_vadjustment(), self.drag[1], event.y_root, self.drag[3])]:
            adjustment.set_value(max(adjustment.get_lower(), min(adjustment.get_upper() -
                                 adjustment.get_page_size(), value + start - now)))
        return True

    def release(self, widget, event):
        if event.button == 1 and self.drag:
            self.motion(widget, event)
            self.drag = None
            widget.grab_remove()
            if self.video:
                self.playback()
            return True
        return False

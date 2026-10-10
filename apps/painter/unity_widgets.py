# -*- coding: utf-8 -*-
"""GTK 3.6 / Python 2.7 widgets for Painter's Unity face."""
from __future__ import unicode_literals
import threading
try:
    import Queue as queue
except ImportError:
    import queue
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib


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
        self.scroll.get_hadjustment().connect('value-changed', lambda *_: self.render())
        self.scroll.get_vadjustment().connect('value-changed', lambda *_: self.render())
        self.scroll.connect('size-allocate', self.resized)
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
        size = (self.scroll.get_allocated_width(), self.scroll.get_allocated_height())
        if args and size == self.viewport_size:
            return
        self.viewport_size = size
        if self.render_timer:
            GLib.source_remove(self.render_timer)
        self.render_timer = GLib.timeout_add(60, self.render)

    def render(self):
        if self.render_timer:
            GLib.source_remove(self.render_timer)
            self.render_timer = None
        if self.original is None or self.rendering:
            return False
        self.rendering = True
        w, h = self.original.get_width(), self.original.get_height()
        vw, vh = max(1, self.scroll.get_allocated_width() - 4), max(1, self.scroll.get_allocated_height() - 4)
        self.scale = self.zoom or min(float(vw) / w, float(vh) / h, 1.0)
        width, height = max(1, int(w * self.scale)), max(1, int(h * self.scale))
        # The layout has the full virtual image size. Only the visible region
        # gets a bitmap, so zooming a large output never allocates zoom^2 pixels.
        self.canvas.set_size(max(vw, width), max(vh, height))
        x, y = max(0, (vw - width) // 2), max(0, (vh - height) // 2)
        sx = int(self.scroll.get_hadjustment().get_value())
        sy = int(self.scroll.get_vadjustment().get_value())
        left, top = max(x, sx), max(y, sy)
        right, bottom = min(x + width, sx + vw), min(y + height, sy + vh)
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
        self.canvas.move(self.events, left, top)
        self.picture.set_from_pixbuf(pixbuf)
        nw, nh = self.natural_size or (w, h)
        self.info.set_text('%d × %d  ·  %d%%%s' % (nw, nh, round(self.scale * w / nw * 100),
                           '  ·  %.1fs  ·  Click to play / pause' % (self.duration / 1000.0) if self.video else ''))
        self.rendering = False
        return False

    def set_zoom(self, value):
        if self.video:
            return
        self.zoom = max(.05, min(16, value)) if value else 0.0
        self.render()

    def zoom_by(self, factor):
        self.set_zoom(self.scale * factor)

    def wheel(self, widget, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.zoom_by(1.25)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.zoom_by(1 / 1.25)
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
        for adjustment, start, now, value in [
                (self.scroll.get_hadjustment(), self.drag[0], event.x_root, self.drag[2]),
                (self.scroll.get_vadjustment(), self.drag[1], event.y_root, self.drag[3])]:
            adjustment.set_value(max(adjustment.get_lower(), min(adjustment.get_upper() -
                                 adjustment.get_page_size(), value + start - now)))
        return True

    def release(self, widget, event):
        if event.button == 1 and self.drag:
            self.drag = None
            widget.grab_remove()
            if self.video:
                self.playback()
            return True
        return False

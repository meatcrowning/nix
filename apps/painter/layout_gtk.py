# -*- coding: utf-8 -*-
"""Native Quantal GTK adapter for the shared MOSS composition editor."""
from __future__ import unicode_literals
import base64
from gi.repository import Gtk, Gdk, GdkPixbuf
from layout_ui import LayoutUI


class CompactFields(Gtk.Bin):
    """Optional toolbar fields contribute natural width, but no minimum."""
    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_get_preferred_width(self):
        return 0, self.get_child().get_preferred_width()[1]

    def do_get_preferred_height(self):
        return self.get_child().get_preferred_height()

    def do_get_preferred_width_for_height(self, height):
        return self.do_get_preferred_width()

    def do_size_allocate(self, allocation):
        self.set_allocation(allocation)
        child = self.get_child()
        fits = allocation.width >= child.get_preferred_width()[0]
        child.set_child_visible(fits)
        if fits:
            child.size_allocate(allocation)


class Toolkit(object):
    def __init__(self, parent):
        self.window = parent.get_toplevel()
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.root.set_border_width(0)
        parent.pack_start(self.root, True, True, 0)

    def show_widget(self, widget, visible):
        widget.set_visible(visible)

    def drawing_cursor(self, widget, drawing):
        if widget.get_window():
            widget.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.CROSSHAIR if drawing else Gdk.CursorType.LEFT_PTR))

    def menu(self, parent, title):
        button = Gtk.Button(label=title)
        menu = Gtk.Menu()
        button.connect('clicked', lambda *_: menu.popup(None, None, None, None, 0, Gtk.get_current_event_time()))
        parent.pack_start(button, False, False, 0)
        return menu

    def menu_item(self, menu, title, callback):
        item = Gtk.MenuItem(label=title)
        item.connect('activate', lambda *_: callback())
        menu.append(item)
        item.show()
        return item

    def enable_widget(self, widget, enabled):
        widget.set_sensitive(enabled)

    def close(self):
        self.root.destroy()

    def row(self, parent, expand=False):
        box = Gtk.Box(spacing=6)
        parent.pack_start(box, expand, expand, 0)
        return box

    def toolbar(self, parent):
        box = self.row(parent)
        box.set_spacing(2)
        box.sizes = Gtk.SizeGroup.new(Gtk.SizeGroupMode.VERTICAL)
        return box

    def spacer(self, parent):
        parent.pack_start(Gtk.Box(), True, True, 0)

    def compact_fields(self, parent):
        holder = CompactFields()
        box = Gtk.Box(spacing=2)
        box.sizes = parent.sizes
        holder.add(box)
        parent.pack_start(holder, False, True, 0)
        return box

    def button_checked(self, button, checked):
        button.syncing = True
        button.set_active(checked)
        button.syncing = False

    def column(self, parent):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(280, -1)
        parent.pack_start(box, False, True, 0)
        return box

    def label(self, parent, text):
        label = Gtk.Label(label=text)
        label.set_alignment(0, .5)
        label.set_line_wrap(True)
        label.set_max_width_chars(32)
        parent.pack_start(label, False, False, 0)
        return label

    def set_label(self, label, text):
        label.set_text(text)

    def button(self, parent, title, callback):
        icons = {'Add': Gtk.STOCK_ADD, 'Undo': Gtk.STOCK_UNDO, 'Redo': Gtk.STOCK_REDO,
                 'Delete': Gtk.STOCK_REMOVE, 'Duplicate': Gtk.STOCK_COPY, 'Lock': Gtk.STOCK_DIALOG_AUTHENTICATION, 'Hide': Gtk.STOCK_CLOSE}
        icon = icons.get(title) if hasattr(parent, 'sizes') else None
        button = (Gtk.ToggleButton if title in ('Lock', 'Hide') else Gtk.Button)(label=None if icon else title)
        if icon:
            image = Gtk.Image.new_from_stock(icon, Gtk.IconSize.MENU)
            if title == 'Hide':
                colour = button.get_style_context().get_color(Gtk.StateFlags.NORMAL)
                stroke = '#%02x%02x%02x' % tuple(int(v * 255) for v in (colour.red, colour.green, colour.blue))
                loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
                loader.write(('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><g fill="none" stroke="%s" stroke-width="1.5"><path d="M1 8 Q8 0 15 8 Q8 16 1 8Z"/><circle cx="8" cy="8" r="2"/><path d="M2 2L14 14"/></g></svg>' % stroke).encode('utf-8'))
                loader.close()
                image = Gtk.Image.new_from_pixbuf(loader.get_pixbuf())
            button.set_image(image)
            tooltip = 'Add region' if title == 'Add' else 'Lock / unlock selected regions' if title == 'Lock' else 'Hide / show selected regions in generation' if title == 'Hide' else title + ' selected regions' if title in ('Delete', 'Duplicate') else title
            button.set_tooltip_text(tooltip)
            button.get_accessible().set_name(tooltip)
        if hasattr(parent, 'sizes'):
            parent.sizes.add_widget(button)
        button.connect('clicked', lambda *_: callback() if not getattr(button, 'syncing', False) else None)
        parent.pack_start(button, False, False, 0)
        return button

    def tabs(self, parent):
        tabs = Gtk.Notebook()
        tabs.set_size_request(-1, 420)
        parent.pack_start(tabs, True, True, 0)
        return tabs

    def tab(self, tabs, title):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        scroll.add_with_viewport(box)
        tabs.append_page(scroll, Gtk.Label(label=title))
        return box

    def field(self, parent, title, kind, options, callback):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        parent.pack_start(box, False, False, 0)
        if kind != 'check' and title and not hasattr(parent, 'sizes'):
            self.label(box, title)
        swatches = None
        if kind == 'combo':
            control = Gtk.ComboBoxText()
            for value in options:
                control.append(value or '_empty', value or 'Unspecified')
            control.connect('changed', lambda *_: callback())
            box.pack_start(control, False, False, 0)
            if hasattr(parent, 'sizes'):
                parent.sizes.add_widget(control)
        elif kind == 'check':
            control = Gtk.CheckButton(label=title)
            control.connect('toggled', lambda *_: callback())
            box.pack_start(control, False, False, 0)
        elif kind == 'number':
            control = Gtk.SpinButton.new_with_range(*options)
            control.set_digits(2 if options[2] < 1 else 0)
            control.connect('value-changed', lambda *_: callback())
            box.pack_start(control, False, False, 0)
        elif kind == 'text':
            control = Gtk.TextView()
            control.set_wrap_mode(Gtk.WrapMode.NONE if title == 'Exact wording' else Gtk.WrapMode.WORD_CHAR)
            control.get_buffer().connect('changed', lambda *_: callback())
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.set_shadow_type(Gtk.ShadowType.IN)
            scroll.set_size_request(-1, self.window.region_prompt_height if title == 'Region prompt' else 95)
            scroll.add(control)
            box.pack_start(scroll, False, False, 0)
            if title == 'Region prompt':
                control.resize_handle = self.resize_handle(box, scroll, 40, 600, self.window.region_prompt_resized, 'Drag to resize the region prompt')
        else:
            control = Gtk.Entry()
            if kind == 'pair':
                control.set_width_chars(6)
                control.set_tooltip_text(title + '; comma-separated')
                control.connect('activate', lambda *_: callback())
                control.connect('focus-out-event', lambda *_: callback() or False)
                parent.sizes.add_widget(control)
            else:
                control.connect('changed', lambda *_: callback())
            box.pack_start(control, False, False, 0)
            if kind == 'palette':
                swatches = self.row(box)
                picker = Gtk.ColorButton()
                picker.set_title(title)
                def picked(*_):
                    c = picker.get_rgba()
                    value = '#%02x%02x%02x' % (int(round(c.red * 255)), int(round(c.green * 255)), int(round(c.blue * 255)))
                    old = control.get_text().strip()
                    control.set_text(value if title == 'Text colour' or not old else old + ', ' + value)
                picker.connect('color-set', picked)
                chooser = self.row(box)
                self.label(chooser, 'Choose colour' if title == 'Text colour' else 'Add colour')
                chooser.pack_start(picker, False, False, 0)
                picker.set_tooltip_text('Choose a colour to add; edit the list above to remove colours.')
        if kind in ('text', 'entry', 'palette') and title not in ('Vertical guides (%; comma-separated)', 'Horizontal guides (%; comma-separated)'):
            spelling = getattr(self.window, 'spelling', None)
            if spelling: spelling.attach(control)
        field = (kind, control, box, swatches)
        if kind == 'palette':
            control.connect('changed', lambda *_: self.swatches(field))
        return field

    def swatches(self, field):
        for child in field[3].get_children():
            field[3].remove(child)
        for value in field[1].get_text().split(',')[:12]:
            c = Gdk.RGBA()
            if c.parse(value.strip()):
                button = Gtk.ColorButton()
                button.set_rgba(c)
                button.set_size_request(22, 22)
                button.set_tooltip_text(value.strip())
                button.connect('color-set', self.replace_colour, field, value.strip())
                field[3].pack_start(button, False, False, 0)
        field[3].show_all()

    def replace_colour(self, button, field, original):
        c = button.get_rgba()
        value = '#%02x%02x%02x' % (int(round(c.red * 255)), int(round(c.green * 255)), int(round(c.blue * 255)))
        field[1].set_text(', '.join(value if v.strip() == original else v.strip() for v in field[1].get_text().split(',')))

    def get(self, field):
        kind, control = field[:2]
        if kind == 'check': return control.get_active()
        if kind == 'number': return control.get_value()
        if kind == 'combo': return (control.get_active_id() or '').replace('_empty', '')
        if kind == 'text':
            b = control.get_buffer()
            value = b.get_text(b.get_start_iter(), b.get_end_iter(), True)
            return value.decode('utf-8') if isinstance(value, bytes) else value
        value = control.get_text()
        return value.decode('utf-8') if isinstance(value, bytes) else value

    def set(self, field, value):
        kind, control = field[:2]
        if kind == 'check': control.set_active(bool(value))
        elif kind == 'number': control.set_value(float(value or 0))
        elif kind == 'combo':
            if not control.set_active_id(value or '_empty'): control.set_active(-1)
        elif kind == 'text': control.get_buffer().set_text(value or '')
        else: control.set_text(value or '')

    def sensitive(self, field, enabled):
        field[2].set_sensitive(enabled)

    def visible(self, field, visible):
        field[2].set_visible(visible)

    def region_list(self, parent, changed):
        model = Gtk.ListStore(str, str)
        view = Gtk.TreeView(model=model)
        view.set_headers_visible(False)
        view.append_column(Gtk.TreeViewColumn('Regions', Gtk.CellRendererText(), text=1))
        selection = view.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.connect('changed', lambda s: changed([model[path][0] for path in s.get_selected_rows()[1]]))
        scroll = Gtk.ScrolledWindow()
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_box.set_no_show_all(True)
        view.show()
        scroll.add(view)
        view.region_scroll = scroll
        list_box.pack_start(scroll, False, False, 0)
        view.region_box = list_box
        view.resize_handle = self.resize_handle(list_box, scroll, 28, 600, self.window.region_list_resized, 'Drag to resize the region list')
        parent.pack_start(list_box, False, False, 0)
        scroll.show()
        view.resize_handle.show_all()
        return view

    def set_list(self, view, rows, selected):
        model = view.get_model()
        model.clear()
        for identity, title in rows:
            it = model.append([identity, title])
            if identity in selected:
                view.get_selection().select_iter(it)

        scroll = view.region_scroll
        scroll.set_size_request(-1, self.window.region_list_height or min(140, max(28, view.get_preferred_height()[1] + 4)))
        view.region_box.set_visible(bool(rows))

    def canvas(self, parent, editor):
        image = Gtk.Image()
        image.set_alignment(0, 0)
        events = Gtk.EventBox()
        events.set_size_request(180, self.window.layout_height)
        surface = Gtk.Layout()
        surface.get_style_context().add_class(Gtk.STYLE_CLASS_BACKGROUND)
        surface.connect('draw', lambda widget, cr: Gtk.render_background(widget.get_style_context(), cr, 0, 0, widget.get_allocated_width(), widget.get_allocated_height()) or False)
        surface.put(image, 0, 0)
        events.add(surface)
        events.set_above_child(True)
        events.set_can_focus(True)
        events.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK)
        def pointer(widget, event, action):
            if editor.panning or (action != 'move' and event.button == 2):
                if action == 'press': widget.grab_add()
                editor.pan_pointer(action, event.x, event.y)
                if action == 'release': widget.grab_remove()
                return True
            if action != 'move' and event.button != 1:
                return False
            if action == 'press':
                widget.grab_focus()
                widget.grab_add()
            editor.pointer(action, event.x, event.y, bool(event.state & Gdk.ModifierType.SHIFT_MASK))
            if action == 'release': widget.grab_remove()
            return True
        events.connect('key-press-event', lambda widget, event: editor.key(Gdk.keyval_name(event.keyval), bool(event.state & Gdk.ModifierType.CONTROL_MASK), bool(event.state & Gdk.ModifierType.SHIFT_MASK)))
        events.connect('button-press-event', pointer, 'press')
        events.connect('button-release-event', pointer, 'release')
        events.connect('motion-notify-event', pointer, 'move')
        def wheel(widget, event):
            steps = 1 if event.direction == Gdk.ScrollDirection.UP else -1 if event.direction == Gdk.ScrollDirection.DOWN else -event.get_scroll_deltas()[2]
            editor.zoom_at(event.x, event.y, steps)
            return True
        events.connect('scroll-event', wheel)
        def draw(*_):
            w, h = events.get_allocated_width(), events.get_allocated_height()
            if w > 10 and h > 10:
                loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
                loader.write(editor.render(w, h))
                loader.close()
                image.set_from_pixbuf(loader.get_pixbuf())
        events.connect('size-allocate', draw)
        parent.pack_start(events, False, False, 0)
        events.resize_handle = self.resize_handle(parent, events, 140, 1200, self.window.layout_resized, 'Drag to resize the layout')
        events.repaint = draw
        return events

    def resize_handle(self, parent, target, minimum, maximum, saved, tooltip):
        handle = Gtk.EventBox()
        handle.set_tooltip_text(tooltip)
        grip = Gtk.Label(label='⋯')
        grip.set_size_request(-1, 10)
        handle.add(grip)
        parent.pack_start(handle, False, False, 0)
        handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                          Gdk.EventMask.POINTER_MOTION_MASK)
        handle.connect('realize', lambda widget: widget.get_window().set_cursor(Gdk.Cursor.new(Gdk.CursorType.SB_V_DOUBLE_ARROW)))
        drag = []
        def resize(widget, event, action):
            if action != 'move' and event.button != 1:
                return False
            if action == 'press':
                drag[:] = [event.y_root, target.get_allocated_height()]
                widget.grab_add()
            if not drag:
                return False
            height = max(minimum, min(maximum, int(drag[1] + event.y_root - drag[0])))
            target.set_size_request(target.get_size_request()[0], height)
            if action == 'release':
                drag[:] = []
                widget.grab_remove()
                saved(height)
            return True
        handle.connect('button-press-event', resize, 'press')
        handle.connect('motion-notify-event', resize, 'move')
        handle.connect('button-release-event', resize, 'release')
        return handle

    def redraw(self, canvas):
        canvas.repaint()

    def reference(self, path):
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 1600, 1600, True)
        ok, data = pixbuf.save_to_bufferv('png', [], [])
        return base64.b64encode(data).decode('ascii') if ok else ''

    def choose_file(self):
        dialog = Gtk.FileChooserDialog('Reference underlay', self.window, Gtk.FileChooserAction.OPEN,
                                      (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else ''
        dialog.destroy()
        return path

    def copy(self, text):
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(text, -1)
        clip.store()

    def paste(self):
        return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ''


def open_editor(parent, doc, accepted):
    toolkit = Toolkit(parent)
    editor = LayoutUI(toolkit, doc, accepted)
    toolkit.root.show_all()
    editor.region_visibility()
    toolkit.root.editor = editor
    return editor

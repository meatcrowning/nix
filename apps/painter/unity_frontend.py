#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Native GTK 3.6 face. Deliberately compatible with Quantal's Python 2.7.

Only this file runs in the historical runtime. All generation, model discovery,
metadata and persistence belong to the modern controller across the socket.
"""
from __future__ import unicode_literals
import json
import os
import socket
import sys
import threading
try:
    import Queue as queue
    from urllib import unquote
except ImportError:
    import queue
    from urllib.parse import unquote

# The runtime does not run Ubuntu's Xsession snippets. Select the original
# menu exporter explicitly, and use GTK's compose input method when IBus is
# absent from this extracted desktop.
os.environ['UBUNTU_MENUPROXY'] = 'libappmenu.so'
if not os.path.exists('/usr/lib/x86_64-linux-gnu/gtk-3.0/3.0.0/immodules/im-ibus.so'):
    os.environ.setdefault('GTK_IM_MODULE', 'gtk-im-context-simple')
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GObject


def local_path(uri):
    return unquote(uri[7:]) if uri.startswith('file://') else uri


class Connection:
    def __init__(self, path, deliver):
        self.path, self.deliver = path, deliver
        self.requests = queue.Queue()
        self.pending_poll = False
        self.closed = False
        self.finished = False
        worker = threading.Thread(target=self.work)
        worker.daemon = True
        worker.start()

    def send(self, request):
        if self.closed or (request['op'] == 'poll' and self.pending_poll):
            return
        if request['op'] == 'poll':
            self.pending_poll = True
        self.requests.put(request)

    def work(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        try:
            sock.connect(self.path)
            stream = sock.makefile('rb')
            while not self.closed:
                request = self.requests.get()
                if request is None:
                    break
                sock.sendall((json.dumps(request) + '\n').encode('utf-8'))
                line = stream.readline(8 * 1024 * 1024)
                if not line or not line.endswith(b'\n'):
                    raise IOError('Painter engine disconnected')
                reply = json.loads(line.decode('utf-8'))
                GLib.idle_add(self.deliver, request['op'], reply)
                if request['op'] == 'poll':
                    self.pending_poll = False
        except Exception as exc:
            if not self.closed:
                GLib.idle_add(self.deliver, 'disconnected', dict(ok=False, error=str(exc)))
        finally:
            sock.close()
            self.finished = True

    def close(self):
        self.closed = True
        self.requests.put(None)


def scroll(child, height=None):
    w = Gtk.ScrolledWindow()
    w.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    w.set_shadow_type(Gtk.ShadowType.IN)
    w.add(child)
    if height:
        w.set_size_request(-1, height)
    return w


def label(text):
    w = Gtk.Label(label=text)
    w.set_alignment(0, 0.5)
    return w


class Window(Gtk.Window):
    def __init__(self, path):
        Gtk.Window.__init__(self, title='Painter')
        self.set_wmclass('painter', 'Painter')
        self.set_icon_name('painter')
        self.set_default_size(1180, 820)
        self.set_size_request(760, 560)
        self.loading = True
        self.state = {}
        self.revision = None
        self.offset = 0
        self.controls = {}
        self.rows = {}
        self.gallery_key = None
        self.selection = ''
        self.preview_serial = 0
        self.zoom = 1.0
        self.save_timer = None
        self.connected = True
        self.closing = False
        self.connection = Connection(path, self.receive)
        self.connect('delete-event', self.close_window)
        self.accels = Gtk.AccelGroup()
        self.add_accel_group(self.accels)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.actions = {}
        menubar = Gtk.MenuBar()
        for title, entries in [
            ('_File', [('generate', '_Generate', '<Control>Return', self.generate),
                       ('open', '_Open Output', '<Control>o', self.open_output),
                       ('folder', 'Open Output _Folder', None, lambda: self.send('folder')),
                       ('quit', '_Quit', '<Control>q', self.close_window)]),
            ('_Edit', [('restore', '_Use Output Settings', '<Control>r', self.restore),
                       ('loras', '_LoRAs…', None, self.loras_dialog)]),
            ('_View', [('browse', '_Browse', 'Escape', self.browse),
                       ('preview', '_View Image', 'Return', self.view),
                       ('zoom_in', 'Zoom _In', '<Control>plus', lambda: self.zoom_by(1.5)),
                       ('zoom_out', 'Zoom _Out', '<Control>minus', lambda: self.zoom_by(1 / 1.5)),
                       ('fit', '_Fit Image', '<Control>0', self.fit_image),
                       ('refresh', '_Refresh', 'F5', lambda: self.send('rescan'))]),
            ('_Generation', [('cancel', '_Cancel Jobs', None, lambda: self.send('cancel'))])]:
            top = Gtk.MenuItem.new_with_mnemonic(title)
            menu = Gtk.Menu()
            top.set_submenu(menu)
            menubar.append(top)
            for key, text, accelerator, callback in entries:
                item = Gtk.MenuItem.new_with_mnemonic(text)
                item.connect('activate', lambda _w, fn=callback: fn())
                if accelerator:
                    code, mods = Gtk.accelerator_parse(accelerator)
                    item.add_accelerator('activate', self.accels, code, mods, Gtk.AccelFlags.VISIBLE)
                menu.append(item)
                self.actions.setdefault(key, []).append(item)
        outer.pack_start(menubar, False, False, 0)
        toolbar = Gtk.Toolbar()
        toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)
        for key, stock, text, callback in [
            ('generate', Gtk.STOCK_EXECUTE, 'Generate', self.generate),
            ('cancel', Gtk.STOCK_STOP, 'Cancel', lambda: self.send('cancel')),
            ('browse', Gtk.STOCK_INDEX, 'Browse', self.browse),
            ('preview', Gtk.STOCK_ZOOM_FIT, 'View', self.view),
            ('restore', Gtk.STOCK_REVERT_TO_SAVED, 'Use Settings', self.restore),
            ('open', Gtk.STOCK_OPEN, 'Open', self.open_output)]:
            button = Gtk.ToolButton.new_from_stock(stock)
            button.set_label(text)
            button.set_is_important(True)
            button.connect('clicked', lambda _w, fn=callback: fn())
            toolbar.insert(button, -1)
            self.actions.setdefault(key, []).append(button)
        outer.pack_start(toolbar, False, False, 0)
        self.info = Gtk.InfoBar()
        self.info.set_no_show_all(True)
        self.info.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        self.info.connect('response', lambda *_: self.info.hide())
        self.info_label = label('')
        self.info_label.set_line_wrap(True)
        self.info.get_content_area().add(self.info_label)
        outer.pack_start(self.info, False, False, 0)

        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_position(380)
        outer.pack_start(split, True, True, 0)
        params = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        params.set_border_width(12)
        params_scroll = Gtk.ScrolledWindow()
        params_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        params_scroll.add_with_viewport(params)
        split.pack1(params_scroll, False, False)
        self.mode_store = Gtk.ListStore(str, str, bool)
        self.mode = Gtk.ComboBox.new_with_model(self.mode_store)
        cell = Gtk.CellRendererText()
        self.mode.pack_start(cell, True)
        self.mode.add_attribute(cell, 'text', 1)
        self.mode.add_attribute(cell, 'sensitive', 2)
        self.mode.connect('changed', self.mode_changed)
        params.pack_start(label('Mode'), False, False, 0)
        params.pack_start(self.mode, False, False, 0)
        self.models = Gtk.ComboBoxText()
        self.models.connect('changed', self.model_changed)
        params.pack_start(label('Model'), False, False, 0)
        params.pack_start(self.models, False, False, 0)
        self.model_info = label('Looking for models…')
        self.model_info.set_line_wrap(True)
        params.pack_start(self.model_info, False, False, 0)
        for key, title, height in [('positive', 'Prompt', 120), ('negative', 'Negative prompt', 65)]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.pack_start(label(title), False, False, 0)
            text = Gtk.TextView()
            text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            text.get_buffer().connect('changed', self.changed)
            box.pack_start(scroll(text, height), True, True, 0)
            params.pack_start(box, False, False, 0)
            self.controls[key] = text
            self.rows[key] = box

        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(6)
        self.grid.set_column_spacing(10)
        params.pack_start(self.grid, False, False, 0)
        self.grid_row = 0
        self.combo('seedPolicy', 'Seed', ['Random', 'Fixed', 'Reuse last'])
        self.entry('seed', 'Seed number')
        self.number('count', 'Jobs', 1, 100, 1)
        self.number('width', 'Width', 64, 16384, 64)
        self.number('height', 'Height', 64, 16384, 64)
        self.number('steps', 'Steps', 1, 1000, 1)
        self.number('cfg', 'Guidance', 0, 100, .5, 2)
        self.combo('sampler_name', 'Sampler', [])
        self.combo('scheduler', 'Schedule', [])
        self.number('denoise', 'Denoise', 0, 1, .05, 2)
        self.number('batch_size', 'Batch size', 1, 64, 1)
        self.check('still', 'Generate a still frame')
        self.number('duration', 'Seconds', .1, 120, .5, 1)
        self.number('fps', 'Frames per second', 1, 120, 1)
        self.number('megapixels', 'Pixel budget (MP)', .1, 16, .1, 2)
        self.check('editNoScale', 'Keep source image size')
        self.number('editMegapixels', 'Edit pixel budget (MP)', .1, 16, .1, 2)
        self.check('useInputImage', 'Use first frame')
        self.check('useLastFrame', 'Use last frame')
        self.check('useReferences', 'Use reference images')
        self.input_button = Gtk.Button(label='Choose source image…')
        self.input_button.connect('clicked', lambda *_: self.choose_image('input'))
        params.pack_start(self.input_button, False, False, 0)
        self.last_button = Gtk.Button(label='Choose last frame…')
        self.last_button.connect('clicked', lambda *_: self.choose_image('last'))
        params.pack_start(self.last_button, False, False, 0)
        self.reference_button = Gtk.Button(label='Additional references…')
        self.reference_button.connect('clicked', lambda *_: self.choose_image('reference'))
        params.pack_start(self.reference_button, False, False, 0)
        clear = Gtk.Button(label='Clear source images')
        clear.connect('clicked', lambda *_: self.send('clear_references'))
        params.pack_start(clear, False, False, 0)
        self.clear_button = clear
        self.source_info = label('')
        self.source_info.set_line_wrap(True)
        params.pack_start(self.source_info, False, False, 0)

        advanced = Gtk.Expander(label='Advanced')
        params.pack_start(advanced, False, False, 0)
        advanced_grid = Gtk.Grid()
        advanced_grid.set_row_spacing(6)
        advanced_grid.set_column_spacing(10)
        advanced.add(advanced_grid)
        self.grid = advanced_grid
        self.grid_row = 0
        self.check('negpip', 'Negative prompt weighting')
        self.check('modelSampling', 'Model sampling patch')
        for key, title, low, high, step in [
                ('shift_start', 'Starting shift', 0, 100, .1),
                ('shift_end', 'Ending shift', 0, 100, .1),
                ('start_percent', 'Start fraction', 0, 1, .05),
                ('end_percent', 'End fraction', 0, 1, .05),
                ('multiplier', 'Multiplier', 0, 100, .1)]:
            self.number('ms.' + key, title, low, high, step, 2)
        self.combo('ms.curve', 'Curve', [])
        self.combo('ms.outside_window', 'Outside interval', [])
        self.entry('system_prompt', 'System prompt')
        self.combo('krea_sampling', 'Krea sampling', ['native', 'manual', 'turbo_fixed'])
        self.number('krea_shift', 'Krea shift', .01, 100, .1, 2)
        self.number('reference_megapixels', 'Reference budget (MP)', .1, 16, .1, 2)
        loras = Gtk.Button(label='LoRAs…')
        loras.connect('clicked', lambda *_: self.loras_dialog())
        self.grid.attach(loras, 0, self.grid_row, 2, 1)
        self.loras_button = loras

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right.set_border_width(8)
        split.pack2(right, True, False)
        self.search = Gtk.Entry()
        self.search.set_placeholder_text('Search outputs')
        self.search.connect('changed', self.search_changed)
        right.pack_start(self.search, False, False, 0)
        self.pages = Gtk.Notebook()
        self.pages.set_show_tabs(False)
        self.pages.set_show_border(False)
        right.pack_start(self.pages, True, True, 0)
        self.tiles = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str)
        self.gallery = Gtk.IconView.new_with_model(self.tiles)
        self.gallery.set_pixbuf_column(0)
        self.gallery.set_text_column(1)
        self.gallery.set_item_width(150)
        self.gallery.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.gallery.connect('selection-changed', self.selected)
        self.gallery.connect('item-activated', lambda *_: self.view())
        self.pages.append_page(scroll(self.gallery), None)
        self.picture = Gtk.Image()
        picture_scroll = Gtk.ScrolledWindow()
        picture_scroll.add_with_viewport(self.picture)
        self.pages.append_page(picture_scroll, None)
        nav = Gtk.Box(spacing=6)
        self.previous = Gtk.Button.new_from_stock(Gtk.STOCK_GO_BACK)
        self.previous.connect('clicked', lambda *_: self.change_page(-60))
        self.next = Gtk.Button.new_from_stock(Gtk.STOCK_GO_FORWARD)
        self.next.connect('clicked', lambda *_: self.change_page(60))
        self.tally = label('Loading outputs…')
        nav.pack_start(self.previous, False, False, 0)
        nav.pack_start(self.tally, True, True, 0)
        nav.pack_end(self.next, False, False, 0)
        right.pack_start(nav, False, False, 0)
        bottom = Gtk.Box(spacing=12)
        bottom.set_border_width(6)
        self.status = label('Connecting to Painter…')
        self.progress = Gtk.ProgressBar()
        self.progress.set_size_request(180, -1)
        bottom.pack_start(self.status, True, True, 0)
        bottom.pack_end(self.progress, False, False, 0)
        outer.pack_end(bottom, False, False, 0)
        self.show_all()
        self.info.hide()
        self.loading = False
        self.update_actions()
        self.send('hello')
        GLib.timeout_add(750, self.poll)

    def add_row(self, key, title, control):
        text = label(title)
        self.grid.attach(text, 0, self.grid_row, 1, 1)
        control.set_hexpand(True)
        self.grid.attach(control, 1, self.grid_row, 1, 1)
        self.grid_row += 1
        self.controls[key] = control
        self.rows[key] = (text, control)

    def number(self, key, title, low, high, step, digits=0):
        control = Gtk.SpinButton.new_with_range(low, high, step)
        control.set_digits(digits)
        control.connect('value-changed', self.changed)
        self.add_row(key, title, control)

    def entry(self, key, title):
        control = Gtk.Entry()
        control.connect('changed', self.changed)
        self.add_row(key, title, control)

    def combo(self, key, title, values):
        control = Gtk.ComboBoxText()
        for value in values:
            control.append(value, value)
        control.connect('changed', self.changed)
        self.add_row(key, title, control)

    def check(self, key, title):
        control = Gtk.CheckButton(label=title)
        control.connect('toggled', self.changed)
        self.grid.attach(control, 0, self.grid_row, 2, 1)
        self.grid_row += 1
        self.controls[key] = control
        self.rows[key] = (control,)

    def values(self):
        values = {}
        for key, control in self.controls.items():
            if key == 'seedPolicy':
                continue
            if isinstance(control, Gtk.TextView):
                buf = control.get_buffer()
                values[key] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
            elif isinstance(control, Gtk.SpinButton):
                values[key] = control.get_value() if control.get_digits() else control.get_value_as_int()
            elif isinstance(control, Gtk.CheckButton):
                values[key] = control.get_active()
            elif isinstance(control, Gtk.ComboBoxText):
                values[key] = control.get_active_id() or ''
            else:
                values[key] = control.get_text()
        values['seed'] = int(values['seed'] or '-1')
        values['ms'] = dict((key[3:], values.pop(key)) for key in list(values) if key.startswith('ms.'))
        policy = self.controls['seedPolicy'].get_active_id()
        values.update(randomSeed=policy == 'Random', reuseSeed=policy == 'Reuse last')
        return values

    def send(self, op, save=False, **extra):
        if not self.connected:
            return
        request = dict(op=op, offset=self.offset, filter=self.search.get_text())
        if save and self.state.get('model'):
            try:
                request.update(settings=self.values(), model=self.state['model'])
            except (ValueError, TypeError) as exc:
                self.message('Check the generation settings: ' + str(exc), True)
                return False
        request.update(extra)
        self.connection.send(request)
        return True

    def changed(self, *_):
        if self.loading:
            return
        self.visibility()
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_timer = GLib.timeout_add(700, self.save)

    def save(self):
        self.save_timer = None
        self.send('settings', save=True)
        return False

    def poll(self):
        if not self.connected or self.closing:
            return False
        self.send('poll')
        return True

    def receive(self, op, reply):
        if not reply.get('ok'):
            self.message(reply.get('error', 'Painter failed'), True)
            if op == 'disconnected':
                self.connected = False
                self.status.set_text('Painter engine disconnected')
                self.update_actions()
            return False
        state = reply['state']
        old = self.state
        self.state = state
        self.loading = True
        if old.get('models') != state['models']:
            self.models.remove_all()
            for model in state['models']:
                self.models.append(model['name'], model['name'])
        self.models.set_active_id(state['model'])
        self.models.set_sensitive(not state['mode'])
        if old.get('modes') != state['modes']:
            self.mode_store.clear()
            self.mode_store.append(['', 'Choose a model', True])
            for mode in state['modes']:
                self.mode_store.append([mode['id'], mode['label'].capitalize(), mode['available']])
        for index, row in enumerate(self.mode_store):
            if row[0] == state['mode']:
                self.mode.set_active(index)
                break
        selected = next((m for m in state['models'] if m['name'] == state['model']), {})
        self.model_info.set_text(selected.get('problem') or selected.get('label') or '')
        settings_changed = self.revision != state['revision']
        for key, source in [('sampler_name', 'samplers'), ('scheduler', 'schedulers'),
                            ('ms.curve', 'curves'), ('ms.outside_window', 'outsideWindows')]:
            if settings_changed or old.get(source) != state[source]:
                values = state['settings']['ms'] if key.startswith('ms.') else state['settings']
                field = key[3:] if key.startswith('ms.') else key
                current = values.get(field, '') if settings_changed else self.controls[key].get_active_id()
                self.controls[key].remove_all()
                for value in sorted(set(state[source] + ([current] if current else []))):
                    self.controls[key].append(value, value)
                self.controls[key].set_active_id(current)
        if settings_changed:
            self.revision = state['revision']
            self.apply_settings(state['settings'])
        self.loading = False
        self.visibility()
        self.update_actions()
        self.status.set_text('%s   |   %s queued' % (state['status'], state['queue']))
        self.progress.set_fraction(max(0, min(1, state['progress'])))
        self.progress.set_text('%d%%' % (state['progress'] * 100) if state['busy'] else '')
        self.progress.set_show_text(True)
        self.source_info.set_text('\n'.join([p for p in [state['input'], state['last']] + state['references'] if p]))
        self.update_gallery(state)
        for message in state['messages']:
            self.message(message['text'], message['error'])
        return False

    def apply_settings(self, values):
        for key, control in self.controls.items():
            if key == 'seedPolicy':
                control.set_active_id('Reuse last' if values.get('reuseSeed') else
                                      'Random' if values.get('randomSeed') else 'Fixed')
                continue
            value = values.get('ms', {}).get(key[3:]) if key.startswith('ms.') else values.get(key)
            if value is None:
                continue
            if isinstance(control, Gtk.TextView):
                control.get_buffer().set_text(value)
            elif isinstance(control, Gtk.SpinButton):
                control.set_value(float(value))
            elif isinstance(control, Gtk.CheckButton):
                control.set_active(bool(value))
            elif isinstance(control, Gtk.ComboBoxText):
                if not control.set_active_id(str(value)):
                    control.append(str(value), str(value))
                    control.set_active_id(str(value))
            else:
                control.set_text(str(value))

    def visible(self, key, show):
        rows = self.rows[key]
        if not isinstance(rows, tuple):
            rows = (rows,)
        for widget in rows:
            widget.set_visible(bool(show))

    def visibility(self):
        flags = self.state.get('flags', {})
        edit, video = flags.get('isEdit', False), flags.get('isVideo', False)
        still = self.controls['still'].get_active()
        sampling = not edit or flags.get('editSampling', False)
        for key in ['steps', 'sampler_name', 'scheduler', 'denoise']:
            self.visible(key, sampling and not flags.get('fixedSampling'))
        for key in ['cfg', 'negative']:
            self.visible(key, sampling and not video)
        for key in ['width', 'height']:
            self.visible(key, not edit)
        self.visible('batch_size', not edit and not video)
        self.visible('still', video)
        for key in ['duration', 'fps', 'useInputImage', 'useLastFrame']:
            self.visible(key, video and not still)
        self.visible('megapixels', video)
        self.visible('editNoScale', edit)
        self.visible('editMegapixels', edit and not self.controls['editNoScale'].get_active())
        patches = flags.get('editPatches') if edit else not video and flags.get('supportsPatches')
        self.visible('negpip', patches or flags.get('encoderControls'))
        self.visible('modelSampling', patches)
        for key in self.controls:
            if key.startswith('ms.'):
                self.visible(key, patches and self.controls['modelSampling'].get_active())
        for key in ['system_prompt', 'krea_sampling', 'krea_shift', 'reference_megapixels', 'useReferences']:
            self.visible(key, flags.get('encoderControls') and not edit)
        self.controls['seed'].set_sensitive(self.controls['seedPolicy'].get_active_id() == 'Fixed')
        images = edit or video or flags.get('referenceImages') or flags.get('optionalEditImage')
        self.input_button.set_visible(bool(images))
        self.last_button.set_visible(video and not still)
        self.reference_button.set_visible(bool(edit or flags.get('referenceImages')))
        self.clear_button.set_visible(bool(images))
        self.loras_button.set_sensitive(bool(flags.get('supportsLoras', False)))

    def update_actions(self):
        for key, widgets in self.actions.items():
            enabled = self.connected
            if key == 'generate':
                enabled = enabled and bool(self.state.get('ready')) and bool(self.state.get('model'))
            elif key == 'cancel':
                enabled = enabled and bool(self.state.get('busy') or self.state.get('queue'))
            elif key in ('restore', 'open', 'preview', 'zoom_in', 'zoom_out', 'fit'):
                enabled = enabled and bool(self.selection)
            elif key == 'loras':
                enabled = enabled and self.state.get('flags', {}).get('supportsLoras', False)
            elif key == 'quit':
                enabled = True
            for widget in widgets:
                widget.set_sensitive(bool(enabled))

    def model_changed(self, *_):
        if not self.loading and self.models.get_active_id():
            self.send('select', save=True, name=self.models.get_active_id())

    def mode_changed(self, *_):
        active = self.mode.get_active_iter()
        if not self.loading and active is not None:
            row = self.mode_store[active]
            if row[2]:
                self.send('mode', save=True, name=row[0])

    def generate(self):
        self.info.hide()
        self.send('generate', save=True)

    def message(self, text, error=False):
        self.info_label.set_text(text)
        self.info.set_message_type(Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO)
        self.info.get_content_area().show_all()
        self.info.show()

    def search_changed(self, *_):
        self.offset = 0
        self.send('poll')

    def change_page(self, delta):
        self.offset = max(0, self.offset + delta)
        self.send('poll')

    def update_gallery(self, state):
        rows = state['gallery']
        key = [(r['path'], r['thumb'], r['poster']) for r in rows]
        if key != self.gallery_key:
            selected = self.selection
            self.tiles.clear()
            for row in rows:
                pixbuf = None
                path = local_path(row['poster'] if row['is_video'] else row['thumb'])
                if path:
                    try:
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 140, 140, True)
                    except GLib.GError:
                        pass
                tree_iter = self.tiles.append([pixbuf, row['name'], row['path']])
                if row['path'] == selected:
                    self.gallery.select_path(self.tiles.get_path(tree_iter))
            self.gallery_key = key
        self.tally.set_text('%d–%d of %d' % (state['offset'] + 1 if rows else 0,
                                            state['offset'] + len(rows), state['total']))
        self.previous.set_sensitive(state['offset'] > 0)
        self.next.set_sensitive(state['offset'] + 60 < state['total'])

    def selected(self, *_):
        items = self.gallery.get_selected_items()
        self.selection = self.tiles[items[0]][2] if items else ''
        self.update_actions()

    def browse(self):
        self.pages.set_current_page(0)

    def view(self):
        if not self.selection:
            return
        row = next((r for r in self.state['gallery'] if r['path'] == self.selection), None)
        if not row:
            return
        path = local_path(row['poster']) if row['is_video'] else row['path']
        if not path:
            self.message('The video poster is still being prepared. Open plays the original clip.')
            return
        self.preview_serial += 1
        serial = self.preview_serial
        width = int(max(400, self.pages.get_allocated_width() - 24) * self.zoom)
        height = int(max(300, self.pages.get_allocated_height() - 24) * self.zoom)
        self.picture.clear()
        self.pages.set_current_page(1)
        def load():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, True)
                GLib.idle_add(self.show_preview, serial, pixbuf)
            except GLib.GError as exc:
                GLib.idle_add(self.message, str(exc), True)
        worker = threading.Thread(target=load)
        worker.daemon = True
        worker.start()

    def zoom_by(self, multiplier):
        self.zoom = max(.25, min(8, self.zoom * multiplier))
        self.view()

    def fit_image(self):
        self.zoom = 1.0
        self.view()

    def show_preview(self, serial, pixbuf):
        if serial == self.preview_serial:
            self.picture.set_from_pixbuf(pixbuf)
        return False

    def restore(self):
        if self.selection:
            self.send('restore', save=True, path=self.selection)

    def open_output(self):
        if self.selection:
            self.send('open', path=self.selection)

    def choose_image(self, op):
        dialog = Gtk.FileChooserDialog('Choose an image', self, Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        filt = Gtk.FileFilter()
        filt.set_name('Images')
        for ext in ['png', 'jpg', 'jpeg', 'webp', 'bmp']:
            filt.add_pattern('*.' + ext)
        dialog.add_filter(filt)
        if dialog.run() == Gtk.ResponseType.OK:
            self.send(op, save=True, path=dialog.get_filename())
        dialog.destroy()

    def loras_dialog(self):
        dialog = Gtk.Dialog('LoRAs', self, Gtk.DialogFlags.MODAL,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_APPLY, Gtk.ResponseType.OK))
        dialog.set_default_size(620, 420)
        store = Gtk.ListStore(bool, str, str, bool, str)
        active = dict((r['name'], r) for r in self.state.get('loras', []))
        for row in self.state.get('choices', []):
            saved = active.get(row['name'], {})
            store.append([bool(saved.get('enabled', False)), row['name'],
                          str(saved.get('strength', 1.0)), row['ok'], row.get('reason', '')])
        tree = Gtk.TreeView(model=store)
        toggle = Gtk.CellRendererToggle()
        toggle.connect('toggled', lambda _w, path: store[path].__setitem__(0, not store[path][0]) if store[path][3] else None)
        tree.append_column(Gtk.TreeViewColumn('Use', toggle, active=0, sensitive=3))
        tree.append_column(Gtk.TreeViewColumn('LoRA', Gtk.CellRendererText(), text=1))
        strength = Gtk.CellRendererText()
        strength.set_property('editable', True)
        strength.connect('edited', lambda _w, path, text: store[path].__setitem__(2, text))
        tree.append_column(Gtk.TreeViewColumn('Strength', strength, text=2))
        tree.append_column(Gtk.TreeViewColumn('Compatibility', Gtk.CellRendererText(), text=4))
        dialog.get_content_area().pack_start(scroll(tree), True, True, 8)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                rows = [dict(name=r[1], strength=float(r[2]), enabled=r[0]) for r in store if r[0] and r[3]]
                self.send('loras', save=True, rows=rows)
            except ValueError:
                self.message('LoRA strengths must be numbers.', True)
        dialog.destroy()

    def close_window(self, *_):
        if self.closing:
            return True
        self.closing = True
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = None
        if self.connected and not self.send('settings', save=True):
            self.closing = False
            return True
        # Queue shutdown after the final settings acknowledgement, so quitting
        # immediately after typing still persists the edit.
        self.connection.requests.put(None)
        self.hide()
        GLib.timeout_add(250, self.finish_close)
        return True

    def finish_close(self):
        if not self.connection.finished:
            return True
        self.connection.close()
        Gtk.main_quit()
        return False


def main():
    GObject.threads_init()
    window = Window(sys.argv[1])
    Gtk.main()
    window.connection.close()


if __name__ == '__main__':
    main()

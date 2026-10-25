#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Native GTK 3.6 face. Deliberately compatible with Quantal's Python 2.7.

This frontend and its GTK helpers run in the historical runtime. All generation, model discovery,
metadata and persistence belong to the modern controller across the socket.
"""
from __future__ import unicode_literals
import base64
import json
import os
import sys
import threading
try:
    from urllib import unquote
except ImportError:
    from urllib.parse import unquote

# The runtime does not run Ubuntu's Xsession snippets. Select the original
# menu exporter explicitly, and use GTK's compose input method when IBus is
# absent from this extracted desktop.
os.environ['UBUNTU_MENUPROXY'] = 'libappmenu.so'
if not os.path.exists('/usr/lib/x86_64-linux-gnu/gtk-3.0/3.0.0/immodules/im-ibus.so'):
    os.environ.setdefault('GTK_IM_MODULE', 'gtk-im-context-simple')
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GObject, Gio
from unity_widgets import ImageView, PreviewDivider, HistoryGrid


def local_path(uri):
    return unquote(uri[7:]) if uri.startswith('file://') else uri


sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pylib'))
from unitygtk import Connection
from spelling_gtk import Spelling
from text_history_gtk import TextHistory


from unity_params import ParameterForm, SnapshotForm, scroll, label


class Window(Gtk.Window, ParameterForm):
    def do_key_press_event(self, event):
        if event.keyval == Gdk.KEY_Escape:
            forms = [self, getattr(self, 'compare_form', None)]
            cards = [card for form in forms if form for card in getattr(form, 'wildcard_cards', {}).values()]
            if any(card.window.get_visible() for card in cards):
                for card in cards: card.hide()
                return True
        # GtkWindow activates menu accelerators before forwarding to the editor.
        # Let multiline text consume Enter and navigation before gallery shortcuts.
        if (isinstance(self.get_focus(), (Gtk.TextView, Gtk.Entry)) and
                not event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK) and
                event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_Page_Up, Gdk.KEY_Page_Down)):
            self.propagate_key_event(event)
            return True
        return Gtk.Window.do_key_press_event(self, event)

    def __init__(self, path):
        Gtk.Window.__init__(self, title='Painter')
        self.set_wmclass('painter', 'Painter')
        self.set_icon_name('applications-graphics')
        self.set_default_size(1180, 820)
        self.set_size_request(760, 560)
        self.loading = True
        self.state = {}
        self.revision = None
        self.offset = 0
        self.history_limit = 60
        self.history_pending = False
        self.history_anchor = None
        self.controls = {}
        self.rows = {}
        self.gallery_key = None
        self.selection = ''
        self.selection_row = {}
        self.history_demand = None
        self.history_fetch_timer = None
        self.text_boxes = {}
        self.heights_loaded = False
        self.restore_history_width = 0
        self.history_save_timer = None
        self.layout_height = 300
        self.region_list_height = 0
        self.region_prompt_height = 95
        self.wording_height = 95
        self.frame_tick = ''
        self.rebuilding_gallery = False
        self.walk_pending = None
        self.grabbed_live = False
        self.save_timer = None
        self.connected = True
        self.closing = False
        self.compare_open = False
        self.copy_serial = 0
        self.image_menu = None
        self.layout_doc = {}
        self.layout_editor = None
        self.layout_model = ''
        self.connection = Connection(path, self.receive)
        self.spelling = Spelling(self.connection.send)
        self.connect('delete-event', self.close_window)
        self.accels = Gtk.AccelGroup()
        self.add_accel_group(self.accels)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.actions = {}
        self.text_history = TextHistory(self.update_text_actions)
        self.text_history.watch(self)
        menubar = Gtk.MenuBar()
        for title, entries in [
            ('_File', [('generate', '_Generate', '<Control>Return', self.generate),
                       ('open', '_Open Output', '<Control>o', self.open_output),
                       ('folder', 'Open Output _Folder', None, lambda: self.send('folder')),
                       ('quit', '_Quit', '<Control>q', self.close_window)]),
            ('_Edit', [('undo', '_Undo', '<Control>z', lambda: self.text_history.apply()),
                       ('redo', '_Redo', '<Control><Shift>z', lambda: self.text_history.apply(True)),
                       ('restore', '_Use Output Settings', '<Control>r', self.restore),
                       ('loras', '_LoRAs…', None, self.loras_dialog)]),
            ('_View', [('browse', '_Browse', 'Escape', self.browse),
                       ('preview', '_View Image', 'Return', self.view),
                       ('zoom_in', 'Zoom _In', '<Control>plus', lambda: self.zoom_by(1.25)),
                       ('zoom_out', 'Zoom _Out', '<Control>minus', lambda: self.zoom_by(1 / 1.25)),
                       ('fit', '_Fit Image', '<Control>0', self.fit_image),
                       ('actual', '_Actual Size', '<Control>1', lambda: self.viewer.set_zoom(1)),
                       ('older', '_Previous Output', 'Page_Up', lambda: self.walk(-1)),
                       ('newer', '_Next Output', 'Page_Down', lambda: self.walk(1)),
                       ('refresh', '_Refresh', 'F5', lambda: self.send('rescan'))]),
            ('_Generation', [('cancel', '_Cancel and Save', None, lambda: self.send('cancel')),
                              ('hard_stop', '_Hard Stop', None, lambda: self.send('hard_stop'))])]:
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
                if key == 'redo':
                    code, mods = Gtk.accelerator_parse('<Control>y')
                    item.add_accelerator('activate', self.accels, code, mods, Gtk.AccelFlags.VISIBLE)
                if key in ('browse', 'preview'):
                    code, mods = Gtk.accelerator_parse('<Alt>Left' if key == 'browse' else '<Alt>Right')
                    item.add_accelerator('activate', self.accels, code, mods, Gtk.AccelFlags.VISIBLE)
                menu.append(item)
                self.actions.setdefault(key, []).append(item)
        outer.pack_start(menubar, False, False, 0)
        toolbar = Gtk.Toolbar()
        toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)
        for key, stock, text, callback in [
            ('generate', Gtk.STOCK_EXECUTE, 'Generate', self.generate),
            ('cancel', Gtk.STOCK_STOP, 'Cancel', lambda: self.send('cancel')),
            ('restore', Gtk.STOCK_REVERT_TO_SAVED, 'Use Settings', self.restore),
            ('compare_params', Gtk.STOCK_PROPERTIES, 'Compare Settings', self.toggle_parameter_compare),
            ('heatmap', Gtk.STOCK_SELECT_COLOR, 'Heatmap', self.toggle_heatmap)]:
            button = (Gtk.ToggleToolButton.new_from_stock(stock) if key in ('compare_params', 'heatmap')
                      else Gtk.ToolButton.new_from_stock(stock))
            button.set_label(text)
            button.set_is_important(True)
            button.connect('clicked', lambda _w, fn=callback: fn())
            if key == 'cancel':
                button.get_child().connect('button-press-event', self.cancel_menu)
                button.set_tooltip_text('Stop after this step and decode; right-click for Hard stop')
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
        self.sidebar_split = split
        split.set_position(380)
        split.connect_after('button-release-event', self.sidebar_resized)
        split.connect_after('accept-position', self.sidebar_resized)
        self.parameter_overlay = Gtk.Overlay()
        self.parameter_overlay.add(split)
        outer.pack_start(self.parameter_overlay, True, True, 0)
        self.compare_panel = Gtk.EventBox()
        self.compare_panel.set_no_show_all(True)
        self.compare_form = None
        self.compare_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.compare_panel.add(self.compare_content)
        self.parameter_overlay.add_overlay(self.compare_panel)
        self.parameter_overlay.connect('get-child-position', self.compare_position)
        split.pack1(self.build_parameters(), False, False)

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
        self.tiles = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, GdkPixbuf.Pixbuf)
        self.gallery = HistoryGrid(self.tiles)
        self.gallery.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.gallery.connect('selection-changed', self.selected)
        self.gallery.connect('item-activated', lambda *_: self.view())
        self.gallery.connect('button-press-event', self.gallery_menu)
        self.browse_pane = PreviewDivider()
        self.browse_pane.set_position(400)
        self.browse_pane.connect_after('button-release-event', self.preview_resized)
        self.browse_pane.connect_after('accept-position', self.preview_resized)
        self.browse_pane.connect_after('size-allocate', self.restore_history_size)
        self.browse_pane.connect('notify::position', self.history_position_changed)
        self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.browse_pane.pack1(self.preview_box, True, False)
        self.history_scroll = scroll(self.gallery)
        self.browse_pane.pack2(self.history_scroll, False, False)
        self.history_scroll.get_vadjustment().connect('value-changed', self.history_scrolled)
        self.pages.append_page(self.browse_pane, Gtk.Label(label='Browse'))
        self.full_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pages.append_page(self.full_box, Gtk.Label(label='View'))
        self.pages.connect_after('switch-page', self.page_switched)
        self.viewer = ImageView(self.message, lambda: self.send('playback'))
        self.viewer.events.connect('button-press-event', self.preview_menu)
        self.heatmap_open = False
        self.heatmap_key = None
        self.heatmap_row = Gtk.Box(spacing=6)
        self.heatmap_row.set_no_show_all(True)
        self.heatmap_row.pack_start(label('Token associations · experimental'), False, False, 0)
        self.heatmap_tokens = Gtk.ComboBoxText()
        self.heatmap_tokens.connect('changed', self.select_heatmap)
        self.heatmap_row.pack_start(self.heatmap_tokens, True, True, 0)
        self.viewer.pack_start(self.heatmap_row, False, False, 0)
        self.viewer.reorder_child(self.heatmap_row, 0)
        self.picture = self.viewer.picture
        self.preview_box.pack_start(self.viewer, True, True, 0)
        self.history_tally = 'Loading outputs…'
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
        GLib.timeout_add(40, self.poll)
        self.poll_count = 0

    def cancel_menu(self, widget, event):
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label='Hard stop')
        item.connect('activate', lambda *_: self.send('hard_stop'))
        menu.append(item)
        menu.show_all()
        self.stop_menu = menu
        menu.popup(None, None, None, None, event.button, event.time)
        return True

    def compare_position(self, overlay, widget, allocation):
        if widget != self.compare_panel:
            return False
        # Paned children have window-local origins; the right child's x is 0.
        allocation.x = self.params_scroll.get_allocated_width()
        allocation.y = 0
        allocation.width = self.params_scroll.get_allocated_width()
        allocation.height = overlay.get_allocated_height()
        return True

    def toggle_parameter_compare(self):
        self.compare_open = not self.compare_open
        self.compare_panel.set_visible(self.compare_open)
        if self.compare_open:
            self.compare_content.show_all()
            self.request_parameter_compare()

    def request_parameter_compare(self):
        if not self.compare_open:
            return
        if self.compare_form:
            self.compare_form.close()
            self.compare_form = None
        for child in self.compare_content.get_children():
            child.destroy()
        note = label('Loading saved settings…' if self.selection and not self.selection.startswith('live://')
                     else 'Select a saved output to compare.')
        note.set_line_wrap(True)
        self.compare_content.pack_start(note, False, False, 0)
        self.compare_content.show_all()
        if self.selection and not self.selection.startswith('live://'):
            self.send('compare_params', path=self.selection)

    def receive_parameter_compare(self, result):
        if not self.compare_open or result.get('path') != self.selection:
            return
        if self.compare_form:
            self.compare_form.close()
            self.compare_form = None
        for child in self.compare_content.get_children():
            child.destroy()
        self.compare_form = None
        state = result.get('snapshot')
        if state:
            self.compare_form = SnapshotForm(self, state)
            self.compare_scroll = self.compare_form.params_scroll
            self.compare_content.pack_start(self.compare_scroll, True, True, 0)
        else:
            note = label('No generation settings are saved in this output.')
            self.compare_content.pack_start(note, False, False, 12)
            note.show()
        self.compare_content.show()
        self.compare_panel.queue_resize()

    def send(self, op, save=False, **extra):
        if not self.connected:
            return
        request = dict(op=op, offset=self.offset, limit=self.history_limit,
                       filter=self.search.get_text(), frameTick=self.frame_tick)
        visible = self.gallery.get_visible_range()
        if visible and visible[0] is not None:
            request.update(thumbFirst=max(0, visible[0].get_indices()[0] - 6),
                           thumbLast=visible[1].get_indices()[0] + 7)
        if save and self.state.get('model'):
            try:
                request.update(settings=self.values(), model=self.state['model'])
            except (ValueError, TypeError) as exc:
                self.message('Check the generation settings: ' + str(exc), True)
                return False
        request.update(extra)
        self.connection.send(request)
        return True


    def sidebar_resized(self, *_):
        if self.heights_loaded:
            self.send('settings', sidebarWidth=max(200, self.sidebar_split.get_position()))
        return False


    def update_status(self):
        self.status.set_text('%s   |   %s' % (self.status_text, self.history_tally))


    def history_size(self):
        return max(0, self.browse_pane.get_allocated_width() -
                   self.browse_pane.get_position() - self.browse_pane.handle_size)

    def restore_history_size(self, widget, allocation):
        if self.restore_history_width and allocation.width > 1:
            width = self.restore_history_width
            self.restore_history_width = 0
            widget.set_position(max(0, allocation.width - widget.handle_size - width))

    def history_position_changed(self, *_):
        if self.heights_loaded and not self.restore_history_width and not self.closing:
            if self.history_save_timer:
                GLib.source_remove(self.history_save_timer)
            self.history_save_timer = GLib.timeout_add(150, self.save_history_size)

    def save_history_size(self):
        self.history_save_timer = None
        if not self.closing:
            self.preview_resized()
        return False

    def preview_resized(self, *_):
        if self.heights_loaded and self.pages.get_current_page() == 0:
            self.send('settings', previewWidth=self.browse_pane.get_position(), historyWidth=self.history_size())
        return False

    def poll(self):
        if not self.connected or self.closing:
            return False
        self.poll_count += 1
        if self.poll_count % 20 == 0:
            self.send('poll')
        elif self.viewer.video or (self.selection == 'live://generating' and self.poll_count % 4 == 0):
            self.send('frame')
        return True


    def generate_tags(self, request, callback):
        if getattr(self, 'tag_callback', None):
            callback(dict(error='The local writer is already running.'))
            return
        self.tag_callback = callback
        self.connection.send(dict(op='tag_start', request=request))

    def poll_tags(self):
        if not self.closing and getattr(self, 'tag_callback', None):
            self.connection.send(dict(op='tag_poll'))
        return False

    def toggle_heatmap(self):
        self.heatmap_open = not self.heatmap_open
        self.heatmap_row.set_visible(self.heatmap_open)
        for widget in self.actions.get('heatmap', []):
            widget.set_active(self.heatmap_open)
        if self.heatmap_open:
            self.heatmap_row.show_all()
            self.heatmap_tokens.remove_all()
            for token in self.state.get('heatmap', {}).get('tokens', []):
                self.heatmap_tokens.append_text(token['label'])
            self.heatmap_tokens.set_active(0)
        else:
            self.heatmap_key = None
            self.viewer.load(self.selection, self.state.get('media', {}).get('before', ''))

    def select_heatmap(self, *_):
        index = self.heatmap_tokens.get_active()
        if self.heatmap_open and index >= 0:
            self.send('heatmap_select', path=self.selection, index=index)

    def receive(self, op, reply):
        if self.closing:
            return False
        if op in ('moss_tokenize', 'heatmap_select'):
            return False
        if op == 'compare_params':
            if reply.get('ok'):
                self.receive_parameter_compare(reply['state'])
            elif self.compare_open:
                for child in self.compare_content.get_children():
                    child.destroy()
                note = label(reply.get('error', 'Could not read output settings'))
                note.set_line_wrap(True)
                self.compare_content.pack_start(note, False, False, 0)
                self.compare_content.show_all()
            return False
        if op in ('tag_start', 'tag_poll') or (op == 'disconnected' and getattr(self, 'tag_callback', None)):
            result = reply.get('state', {}) if reply.get('ok') else dict(error=reply.get('error', 'Tag worker disconnected'))
            if result.get('busy') and not result.get('error'):
                GLib.timeout_add(150, self.poll_tags)
            else:
                callback = getattr(self, 'tag_callback', None)
                self.tag_callback = None
                if callback:
                    callback(result)
            if op != 'disconnected':
                return False
        if not reply.get('ok'):
            self.message(reply.get('error', 'Painter failed'), True)
            if op == 'disconnected':
                self.connected = False
                self.status.set_text('Painter engine disconnected')
                self.update_actions()
            return False
        state = reply['state']
        if op in ('spell', 'spell_learn'):
            if op == 'spell': self.spelling.receive(state)
            return False
        if op == 'frame':
            self.receive_media(state['media'])
            return False
        old = self.state
        if (state.get('offset', 0) != self.offset or
                state.get('galleryQuery', '') != self.search.get_text()):
            for key in ('gallery', 'offset', 'total', 'limit', 'galleryQuery'):
                if key in old: state[key] = old[key]
        self.state = state
        self.apply_parameter_state(state, old)
        for marks in self.token_marks:
            marks.update(state)
        heatmap = state.get('heatmap', {})
        overlay = heatmap.get('overlay', '')
        if (self.heatmap_open and heatmap.get('path') == self.selection
                and overlay and overlay != self.heatmap_key):
            self.heatmap_key = overlay
            self.viewer.load(local_path(overlay))
        if not self.heights_loaded:
            self.sampling.set_expanded(state.get('samplingExpanded', True))
            self.browse_pane.set_position(state['previewWidth'])
            self.restore_history_width = state.get('historyWidth', 0)
            self.browse_pane.queue_resize()
            self.sidebar_split.set_position(state['sidebarWidth'])
            self.layout_height = state['layoutHeight']
            self.region_list_height = state['regionListHeight']
            self.region_prompt_height = state['regionPromptHeight']
            self.wording_height = state.get('wordingHeight', 95)
            for key, height in state['heights'].items():
                self.text_boxes[key].set_height(height)
            self.heights_loaded = True
        g = state['settings']
        self.dimensions.set_text('%d × %d' % (g['width'], g['height']))
        self.dimensions.set_tooltip_text(self.dimensions.get_text())
        self.loading = False
        self.visibility()
        self.update_actions()
        if state.get('flags', {}).get('layoutSupport'):
            self.sync_layout()
        status = '%s   |   %s queued' % (state['status'], state['queue'])
        if state['busy']:
            seconds = max(0, int(state.get('elapsed', 0)))
            status = '%d:%02d   |   %s' % (seconds // 60, seconds % 60, status)
        self.status_text = status
        self.update_status()
        self.progress.set_fraction(max(0, min(1, state['progress'])))
        progress = '%d%%' % (state['progress'] * 100)
        rate = state.get('rate', 0)
        if rate > 0:
            progress += '   |   ' + ('%.2f it/s' % rate if rate >= 1 else '%.2f s/it' % (1 / rate))
        self.progress.set_text(progress if state['busy'] else '')
        self.progress.set_show_text(True)
        self.source_info.set_text('\n'.join([p for p in [state['input'], state['last']] + state['references'] if p]))
        if op == 'generate':
            self.grabbed_live = False
        if (state['offset'] == self.offset and state.get('limit', 60) == self.history_limit
                and state.get('galleryQuery', '') == self.search.get_text()):
            self.update_gallery(state)
        self.receive_media(state['media'])
        for message in state['messages']:
            self.message(message['text'], message['error'], message.get('completion', False))
        self.update_wildcards(state)
        return False


    def receive_media(self, media):
        if self.heatmap_open:
            return
        if media['path'] == self.selection:
            if media['before'] and self.viewer.path and self.viewer.path[1] != media['before']:
                self.viewer.load(self.selection, media['before'])
            if media['path'] == 'live://generating' and media['tick'] == 'live:0':
                self.viewer.original = None
                self.viewer.picture.clear()
                self.viewer.info.set_text('Waiting for a preview frame…')
            if media['data']:
                try:
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(base64.b64decode(media['data']))
                    loader.close()
                    self.viewer.frame(loader.get_pixbuf(), media.get('size'), media.get('duration', 0))
                except GLib.GError as exc:
                    self.message(str(exc), True)
            self.frame_tick = media['tick']


    def update_text_actions(self):
        for key in ('undo', 'redo'):
            for widget in self.actions.get(key, []):
                widget.set_sensitive(self.text_history.available(key == 'redo'))

    def update_actions(self):
        self.refresh_prompt_undo()
        for key, widgets in self.actions.items():
            enabled = self.connected
            if key in ('undo', 'redo'):
                enabled = self.text_history.available(key == 'redo')
            elif key == 'generate':
                enabled = enabled and bool(self.state.get('ready')) and bool(self.state.get('model'))
            elif key in ('cancel', 'hard_stop'):
                enabled = enabled and bool(self.state.get('busy') or self.state.get('queue'))
            elif key == 'heatmap':
                heatmap = self.state.get('heatmap', {})
                enabled = enabled and heatmap.get('available', False) and heatmap.get('path') == self.selection
            elif key == 'compare_params':
                enabled = self.compare_open or (enabled and bool(self.selection and not self.selection.startswith('live://')))
            elif key in ('restore', 'open', 'preview', 'zoom_in', 'zoom_out', 'fit', 'actual', 'older', 'newer'):
                enabled = enabled and bool(self.selection)
            if key in ('zoom_in', 'zoom_out', 'fit', 'actual') and self.viewer.video:
                enabled = False
            if key in ('open', 'restore') and self.selection == 'live://generating':
                enabled = False
            elif key == 'loras':
                enabled = enabled and self.state.get('flags', {}).get('supportsLoras', False)
            elif key == 'quit':
                enabled = True
            for widget in widgets:
                widget.set_sensitive(bool(enabled))


    def page_switched(self, notebook, page, number):
        if not hasattr(self, 'viewer'):
            return
        if number in (0, 1):
            box = self.preview_box if number == 0 else self.full_box
            if self.viewer.get_parent() != box:
                self.viewer.reparent(box)
                box.set_child_packing(self.viewer, True, True, 0, Gtk.PackType.START)
            self.viewer.resized()
        self.search.set_visible(number == 0)

    def generate(self):
        self.info.hide()
        self.send('generate', save=True)

    def message(self, text, error=False, completion=False):
        if completion and self.is_active():
            return
        if not error:
            Gio.bus_get(Gio.BusType.SESSION, None, self.notification_bus, (text, completion))
            return
        self.show_message(text, error)

    def notification_bus(self, source, result, message):
        text, completion = message
        try:
            bus = Gio.bus_get_finish(result)
            if completion and self.is_active():
                return
            if not getattr(self, '_notification_subscription', None):
                self._notification_subscription = bus.signal_subscribe(
                    'org.freedesktop.Notifications', 'org.freedesktop.Notifications',
                    None, '/org/freedesktop/Notifications', None,
                    Gio.DBusSignalFlags.NONE, self.notification_action, None)
                self._notification_ids = set()
            hints = {'desktop-entry': GLib.Variant('s', 'painter')}
            if completion:
                hints['transient'] = GLib.Variant('b', True)
            bus.call('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                     'org.freedesktop.Notifications', 'Notify',
                     GLib.Variant('(susssasa{sv}i)',
                                  ('Painter', 0, 'painter', 'Painter', text, ['default', 'Open Painter'], hints, -1)),
                     None, Gio.DBusCallFlags.NONE, 3000, None, self.notification_sent, text)
        except GLib.GError:
            self.show_message(text, False)

    def notification_sent(self, bus, result, text):
        try:
            self._notification_ids.add(bus.call_finish(result).unpack()[0])
        except GLib.GError:
            self.show_message(text, False)

    def notification_action(self, bus, sender, path, interface, name, parameters, data=None):
        if name not in ('ActionInvoked', 'NotificationClosed'):
            return
        notification_id, action = parameters.unpack()
        if name == 'NotificationClosed':
            self._notification_ids.discard(notification_id)
            return
        if notification_id in self._notification_ids and action == 'default':
            self._notification_ids.discard(notification_id)
            self.present()

    def show_message(self, text, error=False):
        self.info_label.set_text(text)
        self.info.set_message_type(Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO)
        self.info.get_content_area().show_all()
        self.info.show()

    def search_changed(self, *_):
        self.offset = 0
        self.history_limit = 60
        self.history_anchor = None
        self.gallery_key = None
        self.history_pending = True
        self.history_scroll.get_vadjustment().set_value(0)
        self.send('poll')

    def change_page(self, delta):
        self.offset = max(0, self.offset + delta)
        self.history_pending = True
        self.send('poll')

    def history_scrolled(self, *_):
        self.gallery.load_visible()
        if self.history_fetch_timer is None:
            self.history_fetch_timer = GLib.timeout_add(80, self.request_visible_history)
        if self.history_pending or self.rebuilding_gallery or not self.state:
            return
        adjustment = self.history_scroll.get_vadjustment()
        value, page, upper = adjustment.get_value(), adjustment.get_page_size(), adjustment.get_upper()
        if page <= 0 or upper <= page:
            return
        count = len(self.tiles)
        columns = max(1, self.gallery.get_item_column(Gtk.TreePath.new_from_string(str(count - 1))) + 1) if count else 1
        # Derive columns from the first row, rather than an incomplete final row.
        for n in range(count):
            if self.gallery.get_item_row(Gtk.TreePath.new_from_string(str(n))) > 0:
                columns = n
                break
        step = max(columns, (60 // columns) * columns)
        previous = self.offset
        if value + page >= upper - min(180, page / 2) and self.offset + count < self.state.get('total', 0):
            if self.history_limit + step <= 180:
                self.history_limit += step
            else:
                self.offset += step
        elif value < min(100, page / 4) and self.offset > 0:
            self.offset = max(0, self.offset - step)
        else:
            return
        row_height = upper / max(1, (count + columns - 1) // columns)
        self.history_anchor = max(0, value - (self.offset - previous) / float(columns) * row_height)
        self.history_pending = True
        self.send('poll')

    def request_visible_history(self):
        self.history_fetch_timer = None
        visible = self.gallery.get_visible_range()
        demand = (self.offset, self.history_limit, tuple(str(p) for p in visible) if visible else ())
        if demand != self.history_demand and not self.history_pending:
            self.history_demand = demand
            self.send('poll')
        return False

    def history_settled(self):
        if self.history_anchor is not None:
            self.history_scroll.get_vadjustment().set_value(self.history_anchor)
            self.history_anchor = None
        self.history_pending = False
        self.gallery.load_visible()
        self.request_visible_history()
        return False

    def update_gallery(self, state):
        rows = state['gallery']
        selected = self.selection
        if selected == 'live://generating' and state['replacement'] and not any(r['live'] for r in rows):
            selected = state['replacement']
        live = next((r for r in rows if r['live']), None)
        if live and live['grab'] and not self.grabbed_live:
            selected = live['path']
            self.grabbed_live = True
        elif not live:
            self.grabbed_live = False
        key = [(r['path'], r['thumb'], r['poster']) for r in rows]
        if key != self.gallery_key or selected != self.selection:
            if self.walk_pending is not None and rows:
                selected = rows[self.walk_pending]['path']
                self.walk_pending = None
            if not selected or self.gallery_key is None:
                selected = rows[0]['path'] if rows else ''
            self.rebuilding_gallery = True
            self.gallery.sources = {row['path']: local_path(row['poster'] if row['is_video'] else row['thumb']) for row in rows}
            paths = [row[2] for row in self.tiles]
            if paths != [row['path'] for row in rows]:
                if self.history_anchor is None:
                    self.history_anchor = self.history_scroll.get_vadjustment().get_value()
                self.tiles.clear()
                self.gallery.loaded_sources = {}
                self.gallery.image_sizes = {p: size for p, size in self.gallery.image_sizes.items() if p in self.gallery.sources}
                for row in rows:
                    self.tiles.append([None, row['name'], row['path'], None])
            for n, row in enumerate(rows):
                if row['path'] == selected:
                    self.gallery.select_path(Gtk.TreePath.new_from_string(str(n)))
            self.rebuilding_gallery = False
            self.gallery_key = key
            if self.gallery.get_selected_items():
                self.selected()
        if state['offset'] == self.offset:
            GLib.timeout_add(30, self.history_settled)
        self.history_tally = '%d–%d of %d' % (state['offset'] + 1 if rows else 0,
                                            state['offset'] + len(rows), state['total'])
        self.update_status()

    def copyable_image(self, path):
        return any(row.get('path') == path and not row.get('live') and not row.get('is_video')
                   for row in self.state.get('gallery', []) + [self.selection_row])

    def make_image_menu(self, path):
        if not self.copyable_image(path):
            return None
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label='Copy Image')
        item.connect('activate', lambda *_: self.copy_image(path))
        menu.append(item)
        menu.show_all()
        return menu

    def popup_image_menu(self, path, event):
        self.image_menu = self.make_image_menu(path)
        if self.image_menu is None:
            return False
        self.image_menu.popup(None, None, None, None, event.button, event.time)
        return True

    def preview_menu(self, widget, event):
        if event.button != 3:
            return False
        return self.popup_image_menu(self.selection, event)

    def gallery_menu(self, widget, event):
        if event.button != 3:
            return False
        hit = widget.get_path_at_pos(int(event.x), int(event.y))
        if hit is None:
            return False
        return self.popup_image_menu(self.tiles[hit][2], event)

    def copy_image(self, path):
        if not self.copyable_image(path):
            return
        self.copy_serial += 1
        serial = self.copy_serial

        def load():
            try:
                # Decode the output, never its thumbnail, zoom crop or comparison.
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                GLib.idle_add(publish, pixbuf, '')
            except GLib.GError as exc:
                GLib.idle_add(publish, None, str(exc))

        def publish(pixbuf, error):
            if self.closing or serial != self.copy_serial:
                return False
            if error:
                self.message('Could not copy image: ' + error, True)
                return False
            # Native X11 image targets only: no URI list, path or prompt text.
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_image(pixbuf)
            clipboard.store()
            return False

        worker = threading.Thread(target=load)
        worker.daemon = True
        worker.start()

    def selected(self, *_):
        if self.rebuilding_gallery:
            return
        items = self.gallery.get_selected_items()
        path = self.tiles[items[0]][2] if items else ''
        if path != self.selection:
            if self.heatmap_open:
                self.toggle_heatmap()
            self.selection = path
            self.frame_tick = ''
            row = self.selection_row = next((r for r in self.state['gallery'] if r['path'] == path), {})
            self.viewer.path = None
            self.viewer.load('' if row.get('live') or row.get('is_video') else path,
                             video=bool(row.get('is_video') and not row.get('live')))
            if not path:
                self.viewer.info.set_text('Select an output')
            self.send('view', path=path)
            self.request_parameter_compare()
        self.update_actions()

    def move_viewer(self, box, page):
        if self.viewer.get_parent() != box:
            self.viewer.reparent(box)
            box.set_child_packing(self.viewer, True, True, 0, Gtk.PackType.START)
        self.pages.set_current_page(page)
        self.viewer.resized()

    def browse(self):
        self.move_viewer(self.preview_box, 0)

    def view(self):
        if self.selection:
            self.move_viewer(self.full_box, 1)

    def walk(self, delta):
        if self.pages.get_current_page() != 1:
            return
        rows = self.state.get('gallery', [])
        index = next((i for i, r in enumerate(rows) if r['path'] == self.selection), -1)
        target = index + delta
        if 0 <= target < len(rows):
            self.gallery.select_path(Gtk.TreePath.new_from_string(str(target)))
        elif target < 0 and self.offset > 0:
            self.walk_pending = -1
            self.change_page(-60)
        elif target >= len(rows) and self.offset + len(rows) < self.state.get('total', 0):
            self.walk_pending = 0
            self.change_page(len(rows))

    def zoom_by(self, multiplier):
        self.viewer.zoom_by(multiplier)

    def fit_image(self):
        self.viewer.set_zoom(0)

    def restore(self):
        if self.selection:
            self.send('restore', save=True, path=self.selection)

    def open_output(self):
        if self.selection:
            self.send('open', path=self.selection)


    def close_window(self, *_):
        if self.closing:
            return True
        self.closing = True
        if self.save_timer:
            GLib.source_remove(self.save_timer)
            self.save_timer = None
        geometry = {}
        if self.heights_loaded and self.pages.get_current_page() == 0 and not self.restore_history_width:
            geometry['historyWidth'] = self.history_size()
        if self.connected and not self.send('settings', save=True, **geometry):
            self.closing = False
            return True
        # Queue shutdown after the final settings acknowledgement, so quitting
        # immediately after typing still persists the edit.
        self.send('view', path='')
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

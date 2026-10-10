#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Original GTK 3.6 presentation; compatible with Quantal's Python 2.7."""
from __future__ import unicode_literals
import datetime
import json
import os
import sys

os.environ['UBUNTU_MENUPROXY'] = 'libappmenu.so'
if not os.path.exists('/usr/lib/x86_64-linux-gnu/gtk-3.0/3.0.0/immodules/im-ibus.so'):
    os.environ.setdefault('GTK_IM_MODULE', 'gtk-im-context-simple')
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GObject
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pylib'))
from unitygtk import Connection


def label(text):
    widget = Gtk.Label(label=text)
    widget.set_alignment(0, .5)
    return widget


def scroll(widget):
    box = Gtk.ScrolledWindow()
    box.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    box.set_shadow_type(Gtk.ShadowType.IN)
    if isinstance(widget, (Gtk.TextView, Gtk.TreeView)):
        box.add(widget)
    else:
        box.add_with_viewport(widget)
    return box


def text_view(editable=False):
    widget = Gtk.TextView()
    widget.set_editable(editable)
    widget.set_cursor_visible(editable)
    widget.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    widget.set_left_margin(8)
    widget.set_right_margin(8)
    return widget


def utf8(value):
    # Quantal PyGObject returns UTF-8 bytes, unlike modern Python 3 bindings.
    return value.decode('utf-8') if isinstance(value, bytes) else value


def buffer_text(widget):
    buf = widget.get_buffer()
    return utf8(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True))


def update_text(widget, text):
    # Preserve selection and scroll positions when tokens append to a reply.
    buf = widget.get_buffer()
    old = buffer_text(widget)
    if text == old:
        return
    if text.startswith(old):
        buf.insert(buf.get_end_iter(), text[len(old):])
    else:
        buf.set_text(text)


class Turn(Gtk.Box):
    def __init__(self, owner):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.owner = owner
        self.head = label('')
        self.head.set_padding(8, 4)
        self.pack_start(self.head, False, False, 0)
        self.body = text_view()
        self.pack_start(self.body, False, False, 0)
        self.details = Gtk.Expander(label='Details')
        self.detail_text = text_view()
        self.details.add(self.detail_text)
        self.pack_start(self.details, False, False, 0)
        self.extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.extra.set_border_width(8)
        self.pack_start(self.extra, False, False, 0)
        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        self.extra_key = None

    def update(self, row, state):
        who = ('You' if row.get('isUser') else
               (row.get('who') if state.get('showModelName') else state.get('assistantName')) or 'Chatter')
        stamp = datetime.datetime.fromtimestamp(row.get('ts') or 0).strftime('%H:%M') if row.get('ts') else ''
        self.head.set_text(who + ('  ·  ' + stamp if stamp else ''))
        update_text(self.body, row.get('body', ''))
        details = []
        for key, title in [('thinking', 'Reasoning'), ('tools', 'Tools'), ('files', 'Files'),
                           ('agents', 'Agents'), ('sources', 'Sources'), ('execTail', 'Output')]:
            if row.get(key):
                details.append(title + '\n' + row[key])
        update_text(self.detail_text, '\n\n'.join(details))
        self.details.set_visible(bool(details))
        if row.get('genRunning'):
            self.details.set_label('%s · %d%%' % (row.get('genLabel') or 'Generating', 100 * row.get('genFrac', 0)))
            self.details.show()
        else:
            self.details.set_label('Details' + (' · working…' if row.get('streaming') else ''))
        key = tuple(row.get(k, '[]') for k in ('images', 'userImages', 'videos', 'choices'))
        if key == self.extra_key:
            return
        self.extra_key = key
        for child in self.extra.get_children():
            child.destroy()
        for field in ('images', 'userImages', 'videos'):
            for media in json.loads(row.get(field) or '[]'):
                path = media.get('path') or media.get('url') or ''
                if field != 'videos' and path and os.path.isfile(path):
                    try:
                        image = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 520, 320, True))
                        self.extra.pack_start(image, False, False, 0)
                    except GLib.GError:
                        pass
                title = media.get('alt') or os.path.basename(path) or 'Media'
                if path:
                    uri = path if '://' in path else GLib.filename_to_uri(path, None)
                    self.extra.pack_start(Gtk.LinkButton.new_with_label(uri, title), False, False, 0)
                elif media.get('error'):
                    self.extra.pack_start(label(media['error']), False, False, 0)
        for choice in json.loads(row.get('choices') or '[]'):
            self.extra.pack_start(label(choice.get('question', '')), False, False, 0)
            if choice.get('note'):
                self.extra.pack_start(label(choice['note']), False, False, 0)
            for i, option in enumerate(choice.get('options', [])):
                button = Gtk.Button(label=option['label'])
                button.set_tooltip_text(option.get('note') or option['label'])
                facts = ([option['note']] if option.get('note') else [])
                facts += [('%s: %s' % tuple(pair)) for pair in option.get('details', [])]
                if facts:
                    description = label('\n'.join(facts))
                    description.set_line_wrap(True)
                    self.extra.pack_start(description, False, False, 0)
                button.set_sensitive(choice.get('state') == 'pending')
                button.connect('clicked', lambda _w, cid=choice['id'], index=i:
                               self.owner.send('choice', id=cid, index=index))
                self.extra.pack_start(button, False, False, 0)
            if choice.get('state') != 'pending':
                self.extra.pack_start(label(choice.get('state', '')), False, False, 0)
        self.extra.show_all()


class Window(Gtk.Window):
    def __init__(self, path):
        Gtk.Window.__init__(self, title='Chatter')
        self.set_wmclass('oracle', 'Chatter')
        self.set_icon_name('oracle')
        self.set_default_size(880, 720)
        self.set_size_request(520, 400)
        self.state = {}
        self.error = ""
        self.syncing = False
        self.turns = []
        self.session = None
        self.follow = True
        self.connection = Connection(path, self.receive)
        self.connect('delete-event', self.close)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.accels = Gtk.AccelGroup()
        self.add_accel_group(self.accels)
        menus = Gtk.MenuBar()
        outer.pack_start(menus, False, False, 0)
        self.actions = {}
        for name, entries in [
            ('_File', [('new', '_New Conversation', '<Control>n', lambda: self.send('new')),
                       ('delete', '_Delete Conversation…', '', self.delete),
                       ('attach', '_Attach File…', '<Control>o', self.attach),
                       ('close', '_Close', '<Control>w', self.close)]),
            ('_Edit', [('copy', '_Copy', '<Control>c', lambda: self.edit('copy-clipboard')),
                       ('paste', '_Paste', '<Control>v', lambda: self.edit('paste-clipboard')),
                       ('select', 'Select _All', '<Control>a', self.select_all),
                       ('prompt', '_Base Prompt…', '', self.prompt),
                       ('name', '_Assistant Name…', '', self.assistant_name)]),
            ('_View', [('history', 'Conversation _History', 'F9', self.toggle_history),
                       ('jobs', '_Background Jobs…', '', self.show_jobs),
                       ('show-model-name', 'Show _Model Name', '', self.toggle_model_name)]),
            ('_Tools', [('refresh', '_Refresh', 'F5', lambda: self.send('refresh')),
                        ('continue', '_Continue Reply', '', lambda: self.send('continue')),
                        ('start-server', '_Start Server', '', lambda: self.send('start-server')),
                        ('stop-server', 'S_top Server', '', lambda: self.send('stop-server')),
                        ('unload', '_Unload Models', '', lambda: self.send('unload'))]),
            ('_Help', [('about', '_About Chatter', '', self.about)])]:
            item = Gtk.MenuItem.new_with_mnemonic(name)
            menu = Gtk.Menu()
            item.set_submenu(menu)
            menus.append(item)
            for key, title, shortcut, callback in entries:
                action = (Gtk.CheckMenuItem.new_with_mnemonic(title) if key == 'show-model-name'
                          else Gtk.MenuItem.new_with_mnemonic(title))
                action.connect('activate', lambda _w, fn=callback: fn())
                if shortcut:
                    val, mods = Gtk.accelerator_parse(shortcut)
                    action.add_accelerator('activate', self.accels, val, mods, Gtk.AccelFlags.VISIBLE)
                menu.append(action)
                self.actions[key] = action
        toolbar = Gtk.Toolbar()
        toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)
        outer.pack_start(toolbar, False, False, 0)
        for stock, title, callback in [(Gtk.STOCK_NEW, 'New Conversation', lambda: self.send('new')),
                                       (Gtk.STOCK_OPEN, 'Attach File', self.attach)]:
            button = Gtk.ToolButton.new_from_stock(stock)
            button.set_label(title)
            button.set_tooltip_text(title)
            button.connect('clicked', lambda _w, fn=callback: fn())
            toolbar.insert(button, -1)
        spacer = Gtk.SeparatorToolItem()
        spacer.set_draw(False)
        spacer.set_expand(True)
        toolbar.insert(spacer, -1)
        picker = Gtk.ToolItem()
        model_box = Gtk.Box(spacing=6)
        model_box.pack_start(label('Model:'), False, False, 0)
        self.models = Gtk.ComboBoxText()
        self.models.set_tooltip_text('Model for this conversation')
        self.models.connect('changed', self.model_changed)
        model_box.pack_start(self.models, False, False, 0)
        picker.add(model_box)
        toolbar.insert(picker, -1)
        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(split, True, True, 0)
        self.history_store = Gtk.ListStore(str, str)
        self.history = Gtk.TreeView(model=self.history_store)
        self.history.append_column(Gtk.TreeViewColumn('Conversations', Gtk.CellRendererText(), text=1))
        self.history.get_selection().connect('changed', self.session_changed)
        self.history_scroll = scroll(self.history)
        self.history_scroll.set_size_request(170, -1)
        split.pack1(self.history_scroll, False, False)
        split.set_position(190)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_border_width(6)
        split.pack2(content, True, False)
        self.log = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.transcript = scroll(self.log)
        self.adjustment = self.transcript.get_vadjustment()
        self.adjustment.connect('value-changed', self.scrolled)
        self.adjustment.connect('changed', self.size_changed)
        content.pack_start(self.transcript, True, True, 0)
        self.attachments = Gtk.Box(spacing=4)
        content.pack_start(self.attachments, False, False, 0)
        self.attachment_key = None
        self.compose = text_view(True)
        self.compose.connect('key-press-event', self.key)
        self.drag_dest_set(Gtk.DestDefaults.ALL,
                           [Gtk.TargetEntry.new('text/uri-list', 0, 0)], Gdk.DragAction.COPY)
        self.connect('drag-data-received', self.drop_files)
        entry = scroll(self.compose)
        entry.set_size_request(-1, 100)
        content.pack_start(entry, False, False, 0)
        buttons = Gtk.Box(spacing=6)
        self.hint = label('Ctrl+Enter to send')
        buttons.pack_start(self.hint, True, True, 0)
        self.stop_button = Gtk.Button.new_from_stock(Gtk.STOCK_STOP)
        self.stop_button.connect('clicked', lambda _w: self.send('stop'))
        buttons.pack_start(self.stop_button, False, False, 0)
        self.send_button = Gtk.Button(label='Send')
        self.send_button.connect('clicked', self.submit)
        buttons.pack_start(self.send_button, False, False, 0)
        content.pack_start(buttons, False, False, 0)
        self.status = Gtk.Statusbar()
        outer.pack_start(self.status, False, False, 0)
        self.show_all()
        self.compose.grab_focus()
        self.poll_id = GLib.timeout_add(200, self.poll)
        self.poll()

    def send(self, op, **args):
        args['op'] = op
        self.connection.send(args)

    def poll(self):
        self.send('poll')
        return True

    def receive(self, op, reply):
        if not reply.get('ok'):
            self.status.pop(0)
            self.error = reply.get('error', 'Engine unavailable')
            self.status.push(0, self.error)
            if op == 'disconnected':
                GLib.source_remove(self.poll_id)
                self.send_button.set_sensitive(False)
                self.stop_button.set_sensitive(False)
            return
        if op != 'poll':
            self.error = ''
        state = reply['state']
        self.syncing = True
        if state.get('models') != self.state.get('models'):
            self.models.remove_all()
            for name in state['models']:
                self.models.append_text(name)
        names = state['models']
        self.models.set_active(names.index(state['model']) if state['model'] in names else -1)
        self.models.set_sensitive(not state['busy'])
        self.actions['show-model-name'].set_active(state.get('showModelName', False))
        if state.get('sessions') != self.state.get('sessions'):
            self.history_store.clear()
            for row in state['sessions']:
                self.history_store.append([row['id'], row['title']])
        for row in self.history_store:
            if row[0] == state['session']:
                self.history.get_selection().select_iter(row.iter)
                break
        else:
            self.history.get_selection().unselect_all()
        if self.session != state['session'] or len(self.turns) > len(state['rows']):
            for widget in self.turns:
                widget.destroy()
            self.turns = []
            self.session = state['session']
            self.follow = True
        for i, row in enumerate(state['rows']):
            if i == len(self.turns):
                widget = Turn(self)
                self.turns.append(widget)
                self.log.pack_start(widget, False, False, 0)
                widget.show_all()
            self.turns[i].update(row, state)
        atts = state['attachments']
        if atts != self.attachment_key:
            for child in self.attachments.get_children():
                child.destroy()
            for i, att in enumerate(atts):
                button = Gtk.Button(label=att['name'] + ' ×')
                button.set_tooltip_text('Remove attachment')
                button.connect('clicked', lambda _w, index=i: self.send('detach', index=index))
                self.attachments.pack_start(button, False, False, 0)
            self.attachments.show_all()
            self.attachment_key = atts
        self.send_button.set_sensitive(bool(state['model']) and (not state['busy'] or state['awaitingChoice']))
        self.stop_button.set_sensitive(state['busy'])
        self.actions['delete'].set_sensitive(bool(state['session']))
        self.actions['continue'].set_sensitive(not state['busy'] and bool(state['rows']))
        self.set_title((state['title'] + ' — ' if state['title'] else '') + 'Chatter')
        running = sum(1 for row in state['jobs'] if row.get('state') == 'running')
        activity = self.error or state['status'] or ('Replying…' if state['busy'] else 'Ready' if state['serverUp'] else '')
        self.status.pop(0)
        self.status.push(0, '%s    %s    %s' % (activity, '%d jobs' % running if running else '',
                                               'Server running' if state['serverUp'] else 'Server stopped'))
        self.state = state
        self.syncing = False
        if op == 'send':
            # Only clear a successfully accepted submission, preserving edits
            # typed while the request was in flight.
            if buffer_text(self.compose) == getattr(self, 'submitted', None):
                self.compose.get_buffer().set_text('')
            self.follow = True

    def model_changed(self, widget):
        if not self.syncing and widget.get_active_text():
            self.send('model', value=utf8(widget.get_active_text()))

    def session_changed(self, selection):
        model, it = selection.get_selected()
        if not self.syncing and it is not None and model[it][0] != self.state.get('session'):
            self.send('session', id=model[it][0])

    def scrolled(self, adjustment):
        self.follow = adjustment.get_value() >= adjustment.get_upper() - adjustment.get_page_size() - 4

    def size_changed(self, adjustment):
        if self.follow:
            adjustment.set_value(max(0, adjustment.get_upper() - adjustment.get_page_size()))

    def submit(self, *_):
        if not self.send_button.get_sensitive():
            return
        self.submitted = buffer_text(self.compose)
        if self.submitted.strip() or self.state.get('attachments'):
            self.send('send', text=self.submitted)

    def key(self, _widget, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.submit()
            return True
        return False

    def drop_files(self, _widget, context, _x, _y, selection, _info, timestamp):
        accepted = False
        for uri in selection.get_uris():
            try:
                path, host = GLib.filename_from_uri(uri)
                if host not in (None, '', 'localhost'):
                    continue
                self.send('attach', path=utf8(path))
                accepted = True
            except GLib.GError:
                continue
        context.finish(accepted, False, timestamp)

    def attach(self):
        dialog = Gtk.FileChooserDialog('Attach File', self, Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        dialog.set_select_multiple(True)
        def done(widget, response):
            if response == Gtk.ResponseType.OK:
                for path in widget.get_filenames():
                    self.send('attach', path=utf8(path))
            widget.destroy()
        dialog.connect('response', done)
        dialog.show()

    def delete(self):
        sid = self.state.get('session')
        if not sid:
            return
        dialog = Gtk.MessageDialog(self, Gtk.DialogFlags.MODAL, Gtk.MessageType.QUESTION,
                                   Gtk.ButtonsType.OK_CANCEL, 'Delete this conversation?')
        dialog.format_secondary_text(self.state.get('title', ''))
        def done(widget, response):
            if response == Gtk.ResponseType.OK:
                self.send('delete', id=sid)
            widget.destroy()
        dialog.connect('response', done)
        dialog.show()

    def toggle_model_name(self):
        if not self.syncing:
            self.send('show-model-name', value=self.actions['show-model-name'].get_active())

    def assistant_name(self):
        dialog = Gtk.Dialog('Assistant Name', self, Gtk.DialogFlags.DESTROY_WITH_PARENT,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
        entry = Gtk.Entry()
        entry.set_max_length(24)
        entry.set_text(self.state.get('assistantName', ''))
        dialog.get_content_area().pack_start(entry, False, False, 8)
        def done(widget, response):
            if response == Gtk.ResponseType.OK:
                self.send('assistant-name', value=utf8(entry.get_text()))
            widget.destroy()
        dialog.connect('response', done)
        dialog.show_all()

    def prompt(self):
        dialog = Gtk.Dialog('Base Prompt', self, Gtk.DialogFlags.DESTROY_WITH_PARENT,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
        dialog.set_default_size(520, 360)
        box = dialog.get_content_area()
        picker = Gtk.ComboBoxText()
        presets = list(self.state.get('prompts', [])) + [dict(id='custom', label='Custom', text=self.state.get('customPrompt', ''))]
        editor = text_view(True)
        for row in presets:
            picker.append_text(row['label'])
        def changed(widget):
            row = presets[widget.get_active()]
            editor.get_buffer().set_text(row['text'])
            editor.set_editable(row['id'] == 'custom')
        picker.connect('changed', changed)
        picker.set_active(next((i for i, p in enumerate(presets) if p['id'] == self.state.get('promptChoice')), 0))
        box.pack_start(picker, False, False, 6)
        box.pack_start(scroll(editor), True, True, 6)
        def done(widget, response):
            if response == Gtk.ResponseType.OK:
                self.send('prompt', value=presets[picker.get_active()]['id'], text=buffer_text(editor))
            widget.destroy()
        dialog.connect('response', done)
        dialog.show_all()

    def edit(self, signal):
        widget = self.get_focus()
        if isinstance(widget, (Gtk.TextView, Gtk.Entry)):
            widget.emit(signal)

    def select_all(self):
        widget = self.get_focus()
        if isinstance(widget, Gtk.TextView):
            buf = widget.get_buffer()
            buf.select_range(buf.get_start_iter(), buf.get_end_iter())
        elif isinstance(widget, Gtk.Entry):
            widget.select_region(0, -1)

    def toggle_history(self):
        self.history_scroll.set_visible(not self.history_scroll.get_visible())

    def show_jobs(self):
        dialog = Gtk.Dialog('Background Jobs', self, Gtk.DialogFlags.DESTROY_WITH_PARENT,
                            (Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE))
        dialog.set_default_size(520, 320)
        text = text_view()
        box = dialog.get_content_area()
        def update():
            rows = self.state.get('jobs', [])
            update_text(text, '\n\n'.join('%s — %s\n%s' %
                        (row.get('label', 'Job'), row.get('state', ''), row.get('tail', ''))
                        for row in rows) or 'No background jobs.')
            return True
        update()
        timer = GLib.timeout_add(500, update)
        dialog.connect('destroy', lambda *_: GLib.source_remove(timer))
        box.pack_start(scroll(text), True, True, 0)
        for row in self.state.get('jobs', []):
            if row.get('state') in ('running', 'starting'):
                stop = Gtk.Button(label='Stop ' + row.get('label', 'job'))
                stop.connect('clicked', lambda _w, jid=row['id']: self.send('stop-job', id=jid))
                box.pack_start(stop, False, False, 4)
        dialog.connect('response', lambda w, _r: w.destroy())
        dialog.show_all()

    def about(self):
        dialog = Gtk.AboutDialog(transient_for=self)
        dialog.set_program_name('Chatter')
        dialog.set_comments('Conversations with your local models')
        dialog.connect('response', lambda w, _r: w.destroy())
        dialog.show()

    def close(self, *_):
        GLib.source_remove(self.poll_id)
        self.connection.close()
        self.destroy()
        Gtk.main_quit()
        return True


if __name__ == '__main__':
    GObject.threads_init()
    window = Window(sys.argv[1])
    Gtk.main()

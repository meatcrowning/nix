# -*- coding: utf-8 -*-
"""One native parameter form for live settings and isolated output snapshots."""
from __future__ import unicode_literals
import copy
import random
from gi.repository import Gtk, GLib, Pango
from unity_widgets import ResizableText, CompactSpin
from wildcard_gtk import WildcardCard

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


class ParameterForm(object):
    def build_parameters(self):
        params = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        params.set_border_width(12)
        params_scroll = Gtk.ScrolledWindow()
        self.params_scroll = params_scroll
        params_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        params_scroll.add_with_viewport(params)
        sections = {}
        for name in ('Prompt', 'Latent', 'Model', 'Sampling', 'Regions'):
            expander = Gtk.Expander(label=name)
            expander.set_expanded(True)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            expander.add(body)
            params.pack_start(expander, False, False, 0)
            sections[name] = (expander, body)
        self.sections = sections
        params = sections['Model'][1]
        self.mode_store = Gtk.ListStore(str, str, bool)
        self.mode = Gtk.ComboBox.new_with_model(self.mode_store)
        cell = Gtk.CellRendererText()
        self.mode.pack_start(cell, True)
        self.mode.add_attribute(cell, 'text', 1)
        self.mode.add_attribute(cell, 'sensitive', 2)
        self.mode.connect('changed', self.mode_changed)
        self.selectors = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.selector_columns = []
        params.pack_start(self.selectors, False, False, 0)
        self.models = Gtk.ComboBoxText()
        self.models.connect('changed', self.model_changed)
        for title, selector in [('Mode', self.mode), ('Model', self.models)]:
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            column.pack_start(label(title), False, False, 0)
            column.pack_start(selector, False, False, 0)
            self.selectors.pack_start(column, True, True, 0)
            self.selector_columns.append(column)
            for renderer in selector.get_cells():
                renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
                renderer.set_property('width-chars', 10)
                renderer.set_property('max-width-chars', 18)
        self.selectors.connect('size-allocate', self.arrange_selectors)
        self.model_info = label('Looking for models…')
        self.model_info.set_line_wrap(True)
        self.model_info.set_no_show_all(True)
        params.pack_start(self.model_info, False, False, 0)
        params = sections['Prompt'][1]
        self.wildcard_names = None
        self.wildcard_cards = {}
        self.wildcard_buttons = Gtk.Box(spacing=2)
        wildcard_scroll = Gtk.ScrolledWindow()
        wildcard_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        wildcard_scroll.add_with_viewport(self.wildcard_buttons)
        params.pack_start(wildcard_scroll, False, False, 0)
        self.prompt_writers = {}
        self.token_marks = []
        for key, title, height in [('positive', 'Prompt', 120), ('negative', 'Neg prompt', 65)]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            header = Gtk.Box(spacing=4)
            header.pack_start(label(title), False, False, 0)
            limit = CompactSpin(adjustment=Gtk.Adjustment(128, 16, 512, 16, 64, 0), climb_rate=16, digits=0)
            limit.set_width_chars(3)
            limit.get_accessible().set_name('Token limit')
            limit.set_tooltip_text('Maximum output tokens')
            write, undo = Gtk.Button(label='Write'), Gtk.Button()
            undo.set_image(Gtk.Image.new_from_stock(Gtk.STOCK_UNDO, Gtk.IconSize.MENU))
            undo.set_tooltip_text('Restore the prompt before generation')
            undo.get_accessible().set_name('Undo prompt writing')
            undo.set_sensitive(False)
            for widget in (limit, write, undo):
                header.pack_start(widget, False, False, 0)
            self.prompt_writers[key] = dict(limit=limit, write=write, undo=undo, history=None, busy=False)
            write.connect('clicked', lambda _, k=key: self.write_prompt(k))
            undo.connect('clicked', lambda _, k=key: self.undo_written_prompt(k))
            box.pack_start(header, False, False, 0)
            editor = self.text_box(key, height)
            text = editor.text
            count = label("")
            header.pack_end(count, False, False, 0)
            from moss_gtk import TokenMarks
            self.token_marks.append(TokenMarks(text, count, self.send, hover=key == 'positive'))
            box.pack_start(editor, False, False, 0)
            params.pack_start(box, False, False, 0)
            self.controls[key] = text
            self.rows[key] = box

        self.scene_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        params.pack_start(self.scene_box, False, False, 0)
        self.layout_box = sections['Regions'][1]
        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(6)
        self.grid.set_column_spacing(10)
        self.placement_grid = self.grid
        sections['Latent'][1].pack_start(self.grid, False, False, 0)
        self.grid_row = 0
        seed_actions = Gtk.Box(spacing=4)
        randomize = Gtk.Button()
        randomize.set_image(Gtk.Image.new_from_icon_name('media-playlist-shuffle', Gtk.IconSize.MENU))
        randomize.set_tooltip_text('Randomize seed for each generation')
        randomize.connect('clicked', self.randomize_seed)
        fixed = Gtk.Button()
        fixed.set_image(Gtk.Image.new_from_icon_name('document-new', Gtk.IconSize.MENU))
        fixed.set_tooltip_text('New fixed seed')
        fixed.connect('clicked', self.new_fixed_seed)
        policy = Gtk.ComboBoxText()
        for value in ('Fixed', 'Random', 'Reuse last'): policy.append(value, value)
        policy.connect('changed', self.seed_policy_changed)
        self.controls['seedPolicy'] = policy
        for widget in (randomize, fixed, policy): seed_actions.pack_start(widget, False, False, 0)
        self.rows['seedPolicy'] = (seed_actions,)
        self.grid.attach(seed_actions, 0, self.grid_row, 2, 1)
        self.grid_row += 1
        seed_label = label('Seed number')
        seed_label.set_alignment(0, .5)
        seed = Gtk.Entry()
        seed.set_width_chars(6)
        seed.connect('changed', self.changed)
        seed_actions.pack_start(seed_label, False, False, 4)
        seed_actions.pack_start(seed, True, True, 0)
        self.controls['seed'] = seed
        self.rows['seed'] = (seed_label, seed)
        aspect = Gtk.Box(spacing=2)
        for key in ('aspectW', 'aspectH'):
            if key == 'aspectH':
                aspect.pack_start(label(':'), False, False, 0)
            control = CompactSpin(adjustment=Gtk.Adjustment(1, 1, 999, 1, 10, 0), climb_rate=1, digits=0)
            control.set_width_chars(2)
            control.connect('value-changed', self.changed)
            self.controls[key] = control
            aspect.pack_start(control, False, False, 0)
        dimensions_row = Gtk.Box(spacing=4)
        self.aspect_label = label('AR')
        dimensions_row.pack_start(self.aspect_label, False, False, 0)
        dimensions_row.pack_start(aspect, False, False, 0)
        self.grid.attach(dimensions_row, 0, self.grid_row, 2, 1)
        self.grid_row += 1
        self.rows['aspectW'] = self.rows['aspectH'] = (self.aspect_label, aspect)
        self.number('megapixels', 'MP', .1, 8, .1, 1)
        mp_label, mp = self.rows['megapixels']
        def format_mp(control):
            text = ('%.*f' % (int(control.get_digits()), control.get_value())).rstrip('0').rstrip('.')
            control.set_text(text)
            control.set_width_chars(max(3, len(text)))
            return True
        mp.connect('output', format_mp)
        mp_label.set_tooltip_text('Megapixels')
        self.grid.remove(mp_label)
        self.grid.remove(mp)
        dimensions_row.pack_start(mp_label, False, False, 0)
        dimensions_row.pack_start(mp, False, False, 0)
        mp.set_hexpand(False)
        mp.set_width_chars(3)
        self.grid_row -= 1
        self.dimensions = label('')
        self.dimensions.set_ellipsize(Pango.EllipsizeMode.END)
        dimensions_row.pack_start(self.dimensions, False, False, 0)
        self.sampling = sections['Sampling'][0]
        self.sampling.connect('notify::expanded', self.sampling_toggled)
        params = sections['Sampling'][1]
        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(6)
        self.grid.set_column_spacing(10)
        params.pack_start(self.grid, False, False, 0)
        self.grid_row = 0
        self.number('count', 'Jobs', 1, 100, 1)
        self.number('steps', 'Steps', 1, 1000, 1)
        self.number('cfg', 'Guidance', 0, 100, .5, 2)
        self.combo('sampler_name', 'Sampler', [])
        self.combo('scheduler', 'Schedule', [])
        self.number('denoise', 'Denoise', 0, 1, .05, 2)
        self.number('batch_size', 'Batch size', 1, 64, 1)
        self.entry('slg_single_layers', 'SLG single layers')
        self.controls['slg_single_layers'].set_tooltip_text('Negative-pass block indices, comma-separated; empty disables skipping. MOSS has no double-stream blocks.')
        self.number('slg_start_percent', 'SLG start fraction', 0, 1, .001, 3)
        self.number('slg_end_percent', 'SLG end fraction', 0, 1, .001, 3)
        self.check('still', 'Generate a still frame')
        self.number('duration', 'Seconds', .1, 120, .5, 1)
        self.number('fps', 'Frames per second', 1, 120, 1)
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
        self.advanced = advanced
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
        system_box = self.text_box('system_prompt', 90)
        system_label = label('System prompt')
        self.grid.attach(system_label, 0, self.grid_row, 2, 1)
        self.grid.attach(system_box, 0, self.grid_row + 1, 2, 1)
        self.grid_row += 2
        self.rows['system_prompt'] = (system_label, system_box)
        self.controls['system_prompt'] = system_box.text
        self.combo('krea_sampling', 'Krea sampling', ['native', 'manual', 'turbo_fixed'])
        self.number('krea_shift', 'Krea shift', .01, 100, .1, 2)
        self.number('reference_megapixels', 'Reference budget (MP)', .1, 16, .1, 2)
        loras = Gtk.Button(label='LoRAs…')
        loras.connect('clicked', lambda *_: self.loras_dialog())
        self.grid.attach(loras, 0, self.grid_row, 2, 1)
        self.loras_button = loras

        self.ppm = Gtk.CheckButton(label='PPM')
        self.ppm.set_tooltip_text('Enable NegPiP and prompt weighting for MOSS-Image, e.g. (detail:1.5) or (detail:-1).')
        self.ppm.connect('toggled', lambda control: self.controls['negpip'].set_active(control.get_active()))
        self.controls['negpip'].connect('toggled', lambda control: self.ppm.set_active(control.get_active()))
        params.pack_start(self.ppm, False, False, 0)

        return params_scroll

    def text_box(self, key, height):
        box = ResizableText(height, lambda value: self.send('settings', heights={key: value}))
        box.text.get_buffer().connect('changed', self.changed)
        self.spelling.attach(box.text)
        if key in ('positive', 'negative'):
            from prompt_weight_gtk import attach
            attach(box.text)
        self.text_boxes[key] = box
        return box

    def add_row(self, key, title, control):
        text = label(title)
        self.grid.attach(text, 0, self.grid_row, 1, 1)
        control.set_hexpand(True)
        self.grid.attach(control, 1, self.grid_row, 1, 1)
        self.grid_row += 1
        self.controls[key] = control
        self.rows[key] = (text, control)

    def number(self, key, title, low, high, step, digits=0):
        control = (CompactSpin(adjustment=Gtk.Adjustment(low, low, high, step, step * 10, 0), climb_rate=step, digits=digits)
                   if key == 'megapixels' else Gtk.SpinButton.new_with_range(low, high, step))
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
        values = {'moss_layout': self.layout_doc}
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

    def changed(self, *_):
        if hasattr(self, 'prompt_writers') and not self.loading:
            self.refresh_prompt_undo()
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

    def arrange_selectors(self, widget, allocation):
        horizontal = allocation.width >= 320
        orientation = Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL
        if widget.get_orientation() != orientation:
            widget.set_orientation(orientation)
            widget.set_homogeneous(horizontal)

    def wording_resized(self, height):
        self.wording_height = height
        self.send('settings', wordingHeight=height)

    def region_prompt_resized(self, height):
        self.region_prompt_height = height
        self.send('settings', regionPromptHeight=height)

    def new_fixed_seed(self, *_):
        self.controls['seed'].set_text(str(random.SystemRandom().getrandbits(53)))
        self.controls['seedPolicy'].set_active_id('Fixed')
        self.changed()

    def seed_policy_changed(self, *_):
        if self.loading:
            return
        if self.controls['seedPolicy'].get_active_id() == 'Fixed' and self.controls['seed'].get_text().strip() in ('', '-1'):
            self.new_fixed_seed()
        else:
            self.changed()

    def randomize_seed(self, *_):
        self.controls['seed'].set_text('-1')
        self.controls['seedPolicy'].set_active_id('Random')
        self.changed()

    def region_list_resized(self, height):
        self.region_list_height = height
        self.send('settings', regionListHeight=height)

    def layout_resized(self, height):
        self.layout_height = height
        self.send('settings', layoutHeight=height)

    def sampling_toggled(self, *_):
        if not self.loading:
            self.send('settings', samplingExpanded=self.sampling.get_expanded())

    def prompt_text(self, key):
        buf = self.controls[key].get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

    def prompt_snapshot(self):
        return (self.state.get('model'), self.prompt_text('positive'), self.prompt_text('negative'))

    def write_prompt(self, key):
        writer = self.prompt_writers[key]
        if writer['busy']:
            return
        snapshot = self.prompt_snapshot()
        values = dict(positive=snapshot[1], negative=snapshot[2])
        writer['busy'] = True
        writer['write'].set_sensitive(False)
        writer['undo'].set_sensitive(False)
        self.status.set_text('Writing prompt…')
        def finished(result):
            writer['busy'] = False
            if self.closing:
                return
            writer['write'].set_sensitive(True)
            if self.prompt_snapshot() != snapshot:
                self.status.set_text('Result discarded because the prompt or model changed.')
            elif result.get('error'):
                self.message(result['error'], True)
            elif result.get('prompt'):
                writer['history'] = (snapshot[0], values[key], result['prompt'])
                self.controls[key].get_buffer().set_text(result['prompt'])
                self.status.set_text('Prompt written.')
            self.refresh_prompt_undo()
        self.generate_tags(dict(task='prompt', scope=key, caption=values[key],
                                scene=values['positive'], tokens=writer['limit'].get_value_as_int(),
                                moss=bool(self.state.get('flags', {}).get('layoutSupport'))), finished)

    def refresh_prompt_undo(self):
        for key, writer in self.prompt_writers.items():
            entry = writer['history']
            writer['undo'].set_sensitive(bool(not writer['busy'] and entry and
                entry[0] == self.state.get('model') and self.prompt_text(key) == entry[2]))

    def undo_written_prompt(self, key):
        writer = self.prompt_writers[key]
        entry = writer['history']
        if not writer['busy'] and entry and entry[0] == self.state.get('model') and self.prompt_text(key) == entry[2]:
            writer['history'] = None
            self.controls[key].get_buffer().set_text(entry[1])
            self.refresh_prompt_undo()

    def insert_wildcard(self, name):
        editor = self.controls['positive']
        buffer = editor.get_buffer()
        buffer.begin_user_action()
        buffer.delete_selection(True, True)
        buffer.insert_at_cursor('__' + name + '__')
        buffer.end_user_action()
        editor.grab_focus()

    def apply_settings(self, values):
        self.layout_doc = values.get('moss_layout') or {}
        for key, control in self.controls.items():
            if key == 'seedPolicy':
                control.set_active_id('Reuse last' if values.get('reuseSeed') else 'Random' if values.get('randomSeed') else 'Fixed')
                continue
            value = values.get('ms', {}).get(key[3:]) if key.startswith('ms.') else values.get(key)
            if key == 'seed' and values.get('reuseSeed') and self.state.get('lastSeed', -1) >= 0:
                value = self.state['lastSeed']
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
        for marks in self.token_marks:
            marks.update(self.state)
        self.controls['megapixels'].set_digits(6 if flags.get('layoutSupport') else 1)
        self.controls['megapixels'].set_range(.05 if flags.get('layoutSupport') else .1, 16 if flags.get('layoutSupport') else 8)
        self.sections['Regions'][0].set_visible(bool(flags.get('layoutSupport')))
        self.scene_box.set_visible(bool(flags.get('layoutSupport')))
        self.ppm.set_visible(bool(flags.get('layoutSupport')))
        for key in ('slg_single_layers', 'slg_start_percent', 'slg_end_percent'):
            self.visible(key, flags.get('layoutSupport', False))
        edit, video = flags.get('isEdit', False), flags.get('isVideo', False)
        still = self.controls['still'].get_active()
        sampling = not edit or flags.get('editSampling', False)
        for key in ['steps', 'sampler_name', 'scheduler', 'denoise']:
            self.visible(key, sampling and not flags.get('fixedSampling'))
        for key in ['cfg', 'negative']:
            self.visible(key, sampling and not video)
        from_image = video and not still and (self.controls['useInputImage'].get_active() or
                                                self.controls['useLastFrame'].get_active())
        for key in ['aspectW', 'aspectH']:
            self.visible(key, not edit and not from_image)
        self.dimensions.set_visible(not edit)
        if from_image:
            self.dimensions.set_text('Aspect from the source image')
        self.visible('batch_size', not edit and not video)
        self.visible('still', video)
        for key in ['duration', 'fps', 'useInputImage', 'useLastFrame']:
            self.visible(key, video and not still)
        self.visible('megapixels', not edit)
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
        loras = bool(flags.get('supportsLoras', False))
        self.loras_button.set_sensitive(loras)
        self.loras_button.set_visible(loras)
        self.advanced.set_visible(bool(patches or flags.get('encoderControls') or loras))

    def model_changed(self, *_):
        if not self.loading and self.models.get_active_id():
            self.send('select', save=True, name=self.models.get_active_id())

    def mode_changed(self, *_):
        active = self.mode.get_active_iter()
        if not self.loading and active is not None:
            row = self.mode_store[active]
            if row[2]:
                self.send('mode', save=True, name=row[0])

    def sync_layout(self):
        if self.save_timer and self.layout_model == self.state['model']:
            return
        import moss_layout as layout
        from layout_gtk import open_editor
        values = self.values()
        g = self.state['settings']
        try:
            doc = layout.resize(self.layout_doc, g['width'], g['height']) if self.layout_doc else layout.fresh(g['width'], g['height'])
            doc['summary']['caption'] = values['positive']
            if self.layout_editor and self.layout_model == self.state['model']:
                self.layout_editor.load(doc)
                return
            for container in (self.layout_box, self.scene_box):
                for child in container.get_children():
                    child.destroy()
            self.layout_model = self.state['model']
            self.layout_editor = open_editor(self.layout_box, doc, self.layout_changed, owner=self, scene_parent=self.scene_box)
        except (ValueError, TypeError, KeyError) as exc:
            self.message(str(exc), True)

    def layout_changed(self, result):
        self.layout_doc = result
        was_loading = self.loading
        self.loading = True
        self.controls['positive'].get_buffer().set_text(result['summary']['caption'])
        settings = self.state['settings']
        # Region edits must not replace the requested ratio/budget with the
        # model's rounded pixel dimensions. Only an explicit canvas resize does.
        if (result['width'], result['height']) != (settings['width'], settings['height']):
            from dimensions import controls_for_size
            size = controls_for_size(result['width'], result['height'], self.state.get('multiple', settings.get('multiple', 16)), self.values())
            for key, value in size.items():
                self.controls[key].set_value(value)
        self.loading = was_loading
        self.changed()

    def choose_image(self, op):
        dialog = Gtk.FileChooserDialog('Choose an image', self.params_scroll.get_toplevel(), Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        self.params_scroll.get_toplevel().text_history.watch(dialog)
        filt = Gtk.FileFilter()
        filt.set_name('Images')
        for ext in ['png', 'jpg', 'jpeg', 'webp', 'bmp']:
            filt.add_pattern('*.' + ext)
        dialog.add_filter(filt)
        if dialog.run() == Gtk.ResponseType.OK:
            self.send(op, save=True, path=dialog.get_filename())
        dialog.destroy()

    def loras_dialog(self):
        dialog = Gtk.Dialog('LoRAs', self.params_scroll.get_toplevel(), Gtk.DialogFlags.MODAL,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_APPLY, Gtk.ResponseType.OK))
        self.params_scroll.get_toplevel().text_history.watch(dialog)
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

    def apply_parameter_state(self, state, old):
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
        problem = selected.get('problem') or ''
        self.model_info.set_text(problem)
        self.model_info.set_visible(bool(problem))
        self.models.set_tooltip_text(state['model'])
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
        if old.get('model') != state['model']:
            self.layout_model = ''
        if settings_changed:
            self.revision = state['revision']
            self.apply_settings(state['settings'])
            if old.get('model') != state['model']:
                for control in self.controls.values():
                    if hasattr(control, '_text_history'):
                        control._text_history.reset()

    def update_wildcards(self, state):
        names = state.get('wildcards', [])
        if names != self.wildcard_names:
            self.wildcard_names = names
            for button in self.wildcard_buttons.get_children():
                button.destroy()
            self.wildcard_cards = {}
            for name in names:
                button = Gtk.Button(label=name)
                button.set_focus_on_click(False)
                self.wildcard_cards[name] = WildcardCard(button,
                    lambda index, enabled, name=name: self.send('wildcard_line', name=name, index=index, enabled=enabled),
                    editable=not isinstance(self, SnapshotForm))
                button.connect('clicked', lambda _, name=name: self.insert_wildcard(name))
                self.wildcard_buttons.pack_start(button, False, False, 0)
            self.wildcard_buttons.show_all()
        for name, card in self.wildcard_cards.items():
            card.set_rows(state.get('wildcardOptions', {}).get(name, []))


class SnapshotForm(ParameterForm):
    """The normal form with scratch state and no engine/persistence transport."""
    def __init__(self, owner, state):
        self.loading, self.closing = True, False
        self.controls, self.rows, self.text_boxes = {}, {}, {}
        self.state = copy.deepcopy(state)
        self.revision = None
        self.save_timer = None
        self.layout_doc, self.layout_editor, self.layout_model = {}, None, ''
        self.spelling = owner.spelling
        for name in ('layout_height', 'region_list_height', 'region_prompt_height', 'wording_height'):
            setattr(self, name, getattr(owner, name))
        self.build_parameters()
        self.status = label(state.get('note', ''))
        self.status.set_line_wrap(True)
        content = self.params_scroll.get_child().get_child()
        content.pack_start(self.status, False, False, 0)
        self.apply_parameter_state(self.state, {})
        self.update_wildcards(self.state)
        for key, box in self.text_boxes.items():
            box.set_height(owner.text_boxes[key].height)
        self.sampling.set_expanded(owner.sampling.get_expanded())
        self.params_scroll.show_all()
        self.loading = False
        self.visibility()
        if self.state['flags'].get('layoutSupport'):
            self.sync_layout()
        g = self.state['settings']
        self.dimensions.set_text('%d × %d' % (g['width'], g['height']))
        self.source_info.set_text('\n'.join([p for p in [state['input'], state['last']] + state['references'] if p]))
        self.models.set_sensitive(False)
        self.mode.set_sensitive(False)
        self.model_info.set_visible(bool(self.model_info.get_text()))
        for writer in self.prompt_writers.values():
            writer['write'].set_sensitive(False)
        for widget in (self.input_button, self.last_button, self.reference_button, self.clear_button):
            widget.set_sensitive(False)

    def send(self, op, **kwargs):
        return False

    def changed(self, *_):
        if not self.loading:
            self.state['settings'].update(self.values())
            self.visibility()

    def message(self, text, *args):
        self.status.set_text(text)

    def generate_tags(self, request, callback):
        callback(dict(error='Writing is available in the current settings panel.'))

    def choose_image(self, op):
        pass

    def close(self):
        self.closing = True
        self.params_scroll.destroy()

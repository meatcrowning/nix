#!/usr/bin/env python3
"""Native desktop front end for MOSS-Image-Base LoRA training."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QMimeData, QProcess, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from core import ENGINE, Settings, atomic_json, prepare_run
from sampling import LIVE_KEYS, sample_prompts, load_sampling, sample_entries
from sample_editor import SampleEditor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))
from kdeshell import apply_icon_theme, apply_widget_style, is_plasma

CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'moss-trainer/settings.json'


class DirectoryEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText('Choose or drop a dataset folder')

    def directory(self, event):
        urls = event.mimeData().urls()
        return (urls[0].toLocalFile() if len(urls) == 1 and urls[0].isLocalFile()
                and Path(urls[0].toLocalFile()).is_dir() else '')

    def dragEnterEvent(self, event):
        if self.isEnabled() and self.directory(event):
            self.selectAll()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        directory = self.directory(event)
        if self.isEnabled() and directory:
            self.setText(directory)
            event.acceptProposedAction()
        else:
            event.ignore()


class Gallery(QListWidget):
    def mimeData(self, items):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(i.data(Qt.UserRole)) for i in items])
        return data


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('MOSS Trainer')
        self.resize(1100, 760)
        self.settings = Settings.load(CONFIG)
        self.run = None
        self.proc = None
        self.mode = ''
        self.state = 'ready'
        self.live_sampling = False
        self.sampling_request_id = 0
        self.pending_close = False
        self.widgets = {}
        self.seen_samples = set()
        self.selected_sample = ''
        self.buffer = ''
        self.started = 0
        self.progress_start = None
        self.eta = ''
        self.build()
        self.persist_timer = QTimer(self)
        self.persist_timer.setSingleShot(True)
        self.persist_timer.setInterval(400)
        self.persist_timer.timeout.connect(self.persist_settings)
        for widget in self.widgets.values():
            signal = (widget.toggled if isinstance(widget, QCheckBox) else
                      widget.currentTextChanged if isinstance(widget, QComboBox) else
                      widget.valueChanged if isinstance(widget, (QSpinBox, QDoubleSpinBox)) else widget.textChanged)
            signal.connect(lambda *_: self.persist_timer.start())
        self.sample_editor.changed.connect(self.persist_timer.start)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.scan_samples)
        self.timer.start()
        try:
            prefs = json.loads(CONFIG.with_name('window.json').read_text())
            self.restoreGeometry(bytes.fromhex(prefs['geometry']))
            self.splitter.restoreState(bytes.fromhex(prefs['splitter']))
            self.run = Path(prefs['run']) if prefs.get('run') else None
        except (OSError, KeyError, ValueError):
            pass
        self.update_buttons()

    def build(self):
        menu = self.menuBar().addMenu('&File')
        for text, handler in [('Open run…', self.open_run), ('Open output folder', self.open_output),
                              ('Save preset…', lambda: self.preset_dialog(True)),
                              ('Load preset…', lambda: self.preset_dialog(False)), ('Quit', self.close)]:
            action = QAction(text, self)
            action.triggered.connect(handler)
            menu.addAction(action)
        toolbar = self.addToolBar('Training')
        toolbar.setObjectName('training')
        self.go = QPushButton('Go')
        self.pause = QPushButton('Pause')
        self.save = QPushButton('Save checkpoint now')
        self.stop = QPushButton('Save and stop')
        self.resume = QPushButton('Resume saved run')
        self.install = QPushButton('Set up training engine')
        for button, handler in [(self.go, self.start), (self.pause, self.pause_toggle),
                                (self.save, lambda: self.command('save')),
                                (self.stop, lambda: self.command('stop')),
                                (self.resume, self.resume_run), (self.install, self.setup)]:
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        self.splitter = QSplitter()
        self.setCentralWidget(self.splitter)
        self.tabs = QTabWidget()
        self.splitter.addWidget(self.tabs)
        train = QFormLayout()
        self.add_tab('Training', train)
        self.path_row(train, 'dataset', 'Dataset folder', directory=True, drop=True)
        self.path_row(train, 'output', 'Output folder', directory=True)
        self.line(train, 'name', 'Run name')
        self.line(train, 'fallback_caption', 'Caption for images without .txt')
        length_unit = QComboBox()
        length_unit.addItems(['steps', 'epochs'])
        length_unit.setCurrentText(self.settings.training_unit)
        self.widgets['training_unit'] = length_unit
        train.addRow('Training length in', length_unit)
        self.spin(train, 'steps', 'Training steps', 1, 1000000)
        self.spin(train, 'epochs', 'Training epochs', 1, 1000000)
        def length_mode(unit):
            self.widgets['steps'].setEnabled(unit == 'steps')
            self.widgets['epochs'].setEnabled(unit == 'epochs')
        length_unit.currentTextChanged.connect(length_mode)
        length_mode(length_unit.currentText())
        self.spin(train, 'resolution', 'Training resolution', 256, 2048, 16)
        self.spin(train, 'rank', 'LoRA rank', 1, 256)
        self.spin(train, 'learning_rate', 'Learning rate', 0.000001, 0.01, 0.00001, decimals=6)
        self.spin(train, 'blocks_to_swap', 'Blocks offloaded to CPU', 0, 36)
        note = QLabel('MOSS-Image-Base · batch size 1 · INT8\nCaptions are optional. Original dataset files stay untouched.')
        note.setWordWrap(True)
        train.addRow(note)
        samples = QFormLayout()
        self.add_tab('Sampling & saving', samples)
        self.check(samples, 'sample_enabled', 'Enable sampling')
        self.widgets['sample_enabled'].toggled.connect(lambda *_: self.apply_sampling())
        self.check(samples, 'sample_baseline', 'Take baseline samples without LoRA first')
        self.interval(samples, 'sample', 'Sample every')
        self.spin(samples, 'sample_count', 'Samples per interval', 1, 64)
        self.sample_editor = SampleEditor(sample_entries(self.settings))
        self.widgets['sample_count'].valueChanged.connect(self.sample_editor.set_count)
        samples.addRow(self.sample_editor)
        self.text(samples, 'negative_prompt', 'Negative prompt')
        self.apply_samples = QPushButton('Apply sampling changes')
        self.apply_samples.clicked.connect(self.apply_sampling)
        self.sampling_status = QLabel('Each sample has its own prompt. New rows copy the preceding prompt for editing. Apply edits during training for the next sampling interval.')
        self.sampling_status.setTextFormat(Qt.PlainText)
        self.sampling_status.setWordWrap(True)
        samples.addRow(self.apply_samples)
        samples.addRow(self.sampling_status)
        ar = QComboBox()
        self.sample_ar = ar
        ar.addItems(['Custom', '1:1', '4:3', '3:4', '16:9', '9:16'])
        samples.addRow('Aspect ratio', ar)
        self.spin(samples, 'sample_width', 'Width', 256, 2048, 16)
        self.spin(samples, 'sample_height', 'Height', 256, 2048, 16)
        sizes = {'1:1': (768, 768), '4:3': (896, 672), '3:4': (672, 896), '16:9': (1024, 576), '9:16': (576, 1024)}
        def ratio(value):
            if value in sizes:
                self.widgets['sample_width'].setValue(sizes[value][0])
                self.widgets['sample_height'].setValue(sizes[value][1])
        ar.currentTextChanged.connect(ratio)
        self.spin(samples, 'sample_steps', 'Sampling steps', 1, 100)
        self.spin(samples, 'sample_cfg', 'Guidance', 1, 10, 0.1, decimals=1)
        seed_mode = QComboBox()
        for label, value in [('Increment from first seed', 'increment'),
                             ('Random, fixed across sampling times', 'random'),
                             ('Specific seed per sample', 'explicit')]:
            seed_mode.addItem(label, value)
        seed_mode.setCurrentIndex(seed_mode.findData(self.settings.sample_seed_mode))
        self.widgets['sample_seed_mode'] = seed_mode
        samples.addRow('Sample seeds', seed_mode)
        self.spin(samples, 'seed', 'First seed (also seeds training at start)', 0, 2147483647)
        seed_mode.currentIndexChanged.connect(
            lambda *_: self.sample_editor.set_explicit(seed_mode.currentData() == 'explicit'))
        self.sample_editor.set_explicit(seed_mode.currentData() == 'explicit')
        self.interval(samples, 'save', 'Autosave every')
        note = QLabel('Zero disables an interval. Seeds stay fixed across sampling times; random seeds are chosen anew for each run.\nEvery save includes the LoRA and resumable optimizer state.')
        note.setWordWrap(True)
        samples.addRow(note)
        models = QFormLayout()
        self.add_tab('Models', models)
        for key, label in [('dit', 'MOSS Base'), ('text_encoder', 'Text encoder'), ('vae', 'VAE')]:
            self.path_row(models, key, label)
        self.right = QTabWidget()
        self.splitter.addWidget(self.right)
        preview = QWidget()
        layout = QVBoxLayout(preview)
        self.image = QLabel('Samples will appear here during training')
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(240, 200)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.image, 1)
        self.gallery = Gallery()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(112, 112))
        self.gallery.setMaximumHeight(170)
        self.gallery.setDragEnabled(True)
        self.gallery.setSelectionMode(QListWidget.ExtendedSelection)
        self.gallery.currentItemChanged.connect(self.show_sample)
        layout.addWidget(self.gallery)
        self.right.addTab(preview, 'Samples')
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.right.addTab(self.log, 'Log')
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status = QLabel('Ready')
        self.status.setTextFormat(Qt.PlainText)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.progress, 1)
        self.clock = QLabel()
        self.statusBar().addPermanentWidget(self.clock)
        self.splitter.setSizes([420, 680])
        self.splitter.splitterMoved.connect(lambda *_: self.redraw())

    def add_tab(self, name, form):
        content = QWidget()
        content.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, name)

    def line(self, form, key, label, widget=None):
        widget = widget or QLineEdit()
        widget.setText(str(getattr(self.settings, key)))
        self.widgets[key] = widget
        form.addRow(label, widget)
        return widget

    def text(self, form, key, label):
        widget = QPlainTextEdit(str(getattr(self.settings, key)))
        widget.setMaximumHeight(100)
        self.widgets[key] = widget
        form.addRow(label, widget)

    def check(self, form, key, label):
        widget = QCheckBox(label)
        widget.setChecked(getattr(self.settings, key))
        self.widgets[key] = widget
        form.addRow(widget)

    def persist_settings(self):
        try:
            atomic_json(CONFIG, asdict(self.collect()))
        except OSError as exc:
            self.message('Could not save settings: ' + str(exc))

    def preset_dialog(self, saving):
        if not saving and self.active():
            self.message('Load presets when training is stopped; live sampling controls remain available.')
            return
        folder = CONFIG.parent / 'presets'
        folder.mkdir(parents=True, exist_ok=True)
        dialog = QFileDialog(self, 'Save preset' if saving else 'Load preset', str(folder))
        dialog.setOption(QFileDialog.DontUseNativeDialog)
        dialog.setNameFilter('Trainer presets (*.json)')
        dialog.setDefaultSuffix('json')
        dialog.setAcceptMode(QFileDialog.AcceptSave if saving else QFileDialog.AcceptOpen)
        dialog.setFileMode(QFileDialog.AnyFile if saving else QFileDialog.ExistingFile)
        dialog.fileSelected.connect(lambda path: self.preset_file(path, saving))
        dialog.open()
        self.dialog = dialog

    def preset_file(self, path, saving):
        try:
            if saving:
                atomic_json(path, asdict(self.collect()))
            else:
                if self.active():
                    raise ValueError('Stop training before loading a preset.')
                values = json.loads(Path(path).read_text())
                if not isinstance(values, dict) or not values or not set(values) <= set(Settings.__dataclass_fields__):
                    raise ValueError('This is not a trainer preset.')
                settings = Settings(**values)
                defaults = Settings()
                if any(type(getattr(settings, key)) is not type(getattr(defaults, key))
                       for key in values):
                    raise ValueError('Preset contains an invalid value type.')
                self.load_settings(settings)
                self.persist_settings()
            self.message(('Saved preset: ' if saving else 'Loaded preset: ') + Path(path).stem)
        except (OSError, ValueError, TypeError) as exc:
            self.message(str(exc))

    def spin(self, form, key, label, minimum, maximum, step=1, decimals=None):
        widget = QDoubleSpinBox() if decimals is not None else QSpinBox()
        if decimals is not None:
            widget.setDecimals(decimals)
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setValue(getattr(self.settings, key))
        self.widgets[key] = widget
        form.addRow(label, widget)

    def interval(self, form, prefix, label):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        interval = QSpinBox()
        interval.setRange(0, 1000000)
        interval.setSpecialValueText('Off')
        interval.setValue(getattr(self.settings, prefix + '_every'))
        units = QComboBox()
        units.addItems(['steps', 'epochs'])
        units.setCurrentText(getattr(self.settings, prefix + '_unit'))
        self.widgets[prefix + '_every'] = interval
        self.widgets[prefix + '_unit'] = units
        layout.addWidget(interval)
        layout.addWidget(units)
        form.addRow(label, row)

    def path_row(self, form, key, label, directory=False, drop=False):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = DirectoryEdit() if drop else QLineEdit()
        edit.setText(str(getattr(self.settings, key)))
        self.widgets[key] = edit
        button = QPushButton('Browse…')
        button.clicked.connect(lambda: self.browse(edit, directory))
        layout.addWidget(edit)
        layout.addWidget(button)
        form.addRow(label, row)

    def browse(self, edit, directory):
        dialog = QFileDialog(self, 'Choose folder' if directory else 'Choose model')
        dialog.setFileMode(QFileDialog.Directory if directory else QFileDialog.ExistingFile)
        dialog.setOption(QFileDialog.DontUseNativeDialog)
        dialog.setDirectory(edit.text() or str(Path.home()))
        dialog.fileSelected.connect(edit.setText)
        dialog.open()
        self.dialog = dialog

    def collect(self):
        values = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText()
            elif isinstance(widget, QComboBox):
                value = widget.currentData() if key == 'sample_seed_mode' else widget.currentText()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                value = widget.value()
            else:
                value = widget.text()
            values[key] = value
        values['sample_entries'] = self.sample_editor.entries()
        values['sample_random_seed'] = self.settings.sample_random_seed
        return Settings(**values)

    def message(self, text):
        self.status.setText(text)
        self.log.appendPlainText(text)

    def active(self):
        return ((hasattr(self, "preparing") and not self.preparing.done()) or
                (self.proc is not None and self.proc.state() != QProcess.NotRunning))

    def update_buttons(self):
        active = self.active()
        engine = (ENGINE / 'revision').is_file()
        self.go.setEnabled(not active and engine)
        self.resume.setEnabled(not active and engine and self.run is not None and (self.run / 'latest.json').is_file())
        self.pause.setEnabled(active and self.mode == 'training' and self.state in ('training', 'paused'))
        self.pause.setText('Resume' if self.state == 'paused' else 'Pause')
        self.save.setEnabled(active and self.mode == 'training' and self.state in ('training', 'paused', 'sampling'))
        self.stop.setEnabled(active and self.mode == 'training' and self.state != 'stopping')
        self.install.setEnabled(not active)
        self.install.setText('Check / repair engine' if engine else 'Set up training engine')
        live = active and self.mode == 'training' and self.live_sampling
        self.tabs.setEnabled(not active or live)
        self.tabs.setTabEnabled(0, not active)
        self.tabs.setTabEnabled(2, not active)
        for key, widget in self.widgets.items():
            if key.startswith('sample_') or key in ('negative_prompt', 'seed', 'save_every', 'save_unit'):
                widget.setEnabled(not active or (live and key in LIVE_KEYS))
        self.sample_editor.setEnabled(not active or live)
        self.sample_ar.setEnabled(not active)
        self.apply_samples.setEnabled(live)
        if not engine and not active:
            self.status.setText('Set up the training engine before starting.')

    def launch(self, program, arguments, mode):
        self.mode = mode
        self.live_sampling = False
        self.state = 'preparing'
        self.buffer = ''
        self.started = time.monotonic()
        self.progress_start = None
        self.eta = ''
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self.read_output)
        self.proc.finished.connect(self.finished)
        self.proc.errorOccurred.connect(self.process_error)
        self.proc.setProgram(str(program))
        self.proc.setArguments(list(map(str, arguments)))
        self.progress.setRange(0, 0)
        self.proc.start()
        self.update_buttons()
        self.proc.started.connect(self.update_buttons)

    def process_error(self, error):
        self.message(self.proc.errorString())
        self.update_buttons()
        if error == QProcess.FailedToStart:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)

    def setup(self):
        if not self.active():
            self.launch(sys.executable, ['-u', HERE / 'setup_engine.py'], 'setup')

    def start(self):
        if self.active():
            return
        try:
            self.settings = self.collect()
            self.settings.validate()
            atomic_json(CONFIG, asdict(self.settings))
            # Copying caption text and enumerating files stays off the GUI thread.
            from concurrent.futures import ThreadPoolExecutor
            self.pool = ThreadPoolExecutor(max_workers=1)
            self.preparing = self.pool.submit(prepare_run, self.settings)
            self.go.setEnabled(False)
            self.resume.setEnabled(False)
            self.tabs.setEnabled(False)
            self.mode = 'dataset'
            self.update_buttons()
            self.message('Preparing dataset…')
            self.prepare_timer = QTimer(self)
            self.prepare_timer.setInterval(100)
            self.prepare_timer.timeout.connect(self.prepared)
            self.prepare_timer.start()
        except Exception as exc:
            self.message(str(exc))

    def prepared(self):
        if not self.preparing.done():
            return
        self.prepare_timer.stop()
        self.pool.shutdown(wait=False)
        try:
            self.run = self.preparing.result()
            self.gallery.clear()
            self.seen_samples.clear()
            self.launch(ENGINE / '.venv/bin/python', ['-u', HERE / 'worker.py', self.run], 'training')
        except Exception as exc:
            self.message(str(exc))
            self.update_buttons()

    def apply_sampling(self):
        if not (self.active() and self.mode == 'training' and self.live_sampling):
            return
        try:
            settings = self.collect()
            if settings.sample_enabled and settings.sample_every:
                sample_prompts(settings)
            payload = {key: getattr(settings, key) for key in LIVE_KEYS}
            self.sampling_request_id += 1
            payload['request_id'] = self.sampling_request_id
            message = {'command': 'sampling', 'sampling': payload}
            self.proc.write((json.dumps(message) + '\n').encode())
            atomic_json(CONFIG, asdict(settings))
            self.sampling_status.setText('Sampling changes queued for the next completed training step.')
        except Exception as exc:
            self.sampling_status.setText(str(exc))

    def run_settings(self):
        settings = Settings(**json.loads((self.run / 'run.json').read_text())['settings'])
        return load_sampling(settings, self.run)

    def resume_run(self):
        if self.active() or not self.run:
            return
        try:
            latest = json.loads((self.run / 'latest.json').read_text())
            self.load_settings(self.run_settings())
            self.launch(ENGINE / '.venv/bin/python', ['-u', HERE / 'worker.py', self.run, '--resume', latest['state']], 'training')
        except Exception as exc:
            self.message(str(exc))

    def load_settings(self, settings):
        for key, widget in self.widgets.items():
            value = getattr(settings, key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
            elif isinstance(widget, QComboBox):
                if key == 'sample_seed_mode':
                    widget.setCurrentIndex(widget.findData(value))
                else:
                    widget.setCurrentText(value)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(value)
            else:
                widget.setText(value)
        self.sample_editor.set_entries(sample_entries(settings))
        self.settings = settings
        self.sample_ar.setCurrentText('Custom')

    def open_run(self):
        if self.active():
            self.message('Save and stop the current run before opening another.')
            return
        dialog = QFileDialog(self, 'Open training run')
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter('Training run (run.json)')
        dialog.setOption(QFileDialog.DontUseNativeDialog)
        def selected(path):
            try:
                manifest = json.loads(Path(path).read_text())
                settings = Settings(**manifest['settings'])
                self.load_settings(settings)
                self.run = Path(path).parent
                self.load_settings(self.run_settings())
                self.gallery.clear()
                self.seen_samples.clear()
                self.message('Opened ' + str(self.run))
                self.update_buttons()
            except Exception as exc:
                self.message(str(exc))
        dialog.fileSelected.connect(selected)
        dialog.open()
        self.dialog = dialog

    def open_output(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.run or Path(self.widgets['output'].text()))))

    def pause_toggle(self):
        self.command('resume' if self.state == 'paused' else 'pause')

    def command(self, command):
        if not self.active():
            return
        self.proc.write((json.dumps({'command': command}) + '\n').encode())
        if command == 'stop':
            self.state = 'stopping'
        self.message({'stop': 'Saving and stopping at the next completed step…',
                      'save': 'Checkpoint requested for the next completed step…',
                      'pause': 'Pausing at the next completed step…', 'resume': 'Resuming…'}[command])
        self.update_buttons()

    def read_output(self):
        self.buffer += bytes(self.proc.readAllStandardOutput()).decode('utf-8', errors='replace')
        # tqdm uses carriage returns; normalize them without guessing progress.
        self.buffer = self.buffer.replace('\r', '\n')
        lines = self.buffer.split('\n')
        self.buffer = lines.pop()
        for line in lines:
            if not line:
                continue
            if self.run and self.mode == 'training':
                with (self.run / 'training.log').open('a') as log:
                    log.write(line + '\n')
            if line.startswith('TRAINER:'):
                try:
                    self.handle_event(json.loads(line[len('TRAINER:'):]))
                except (ValueError, KeyError):
                    self.log.appendPlainText(line)
            else:
                self.log.appendPlainText(line)

    def handle_event(self, event):
        kind = event['event']
        if kind == 'capabilities':
            self.live_sampling = bool(event.get('live_sampling'))
        elif kind == 'sampling_update':
            if event.get('request_id') != self.sampling_request_id:
                return
            if event['applied']:
                self.sampling_status.setText('Applied: sampling enabled; prompts encode at the next interval.'
                                            if event['enabled'] else 'Applied: sampling off.')
            else:
                self.sampling_status.setText('Sampling changes rejected: ' + event['message'])
        elif kind == 'status':
            self.state = event['state']
            self.message(self.state.capitalize())
        elif kind == 'progress':
            if self.progress_start is None:
                self.progress_start = (time.monotonic(), event['step'])
            elapsed = time.monotonic() - self.progress_start[0]
            completed = event['step'] - self.progress_start[1]
            if completed > 0:
                remaining = int(elapsed / completed * (event['total'] - event['step']))
                self.eta = f' · ~{remaining // 60} min remaining'
            self.progress.setRange(0, event['total'])
            self.progress.setValue(event['step'])
            if 'current_epoch' in event:
                epoch_text = f"epoch {event['current_epoch']} / {event['total_epochs']}"
                self.progress.setToolTip(f"Step {event['epoch_step']} / {event['steps_per_epoch']} in this epoch")
            else:  # tolerate an already-running worker from before this update
                epoch_text = f"epoch {event['epoch']:.1f}"
            self.progress.setFormat(f"%p% · step {event['step']} / {event['total']} · {epoch_text}")
        elif kind == 'saved':
            self.message('Saved ' + Path(event['path']).name)
        elif kind in ('error', 'warning'):
            self.message(event['message'])
        elif kind == 'samples':
            self.scan_samples()
        self.update_buttons()

    def finished(self, code, _status):
        self.read_output()
        if self.buffer:
            self.log.appendPlainText(self.buffer)
        self.progress.setRange(0, max(1, self.progress.maximum()))
        self.message('Training engine ready' if self.mode == 'setup' and code == 0 else
                     ('Saved and stopped' if code == 0 and self.state == 'stopped' else
                      'Finished' if code == 0 else 'Failed — see Log for details'))
        self.proc.deleteLater()
        self.proc = None
        self.update_buttons()
        if self.pending_close and code == 0:
            self.close()
        elif code != 0:
            self.pending_close = False

    def scan_samples(self):
        if self.active() and self.started:
            seconds = int(time.monotonic() - self.started)
            self.clock.setText(f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02} elapsed' + self.eta)
        if not self.run:
            return
        for path in sorted((self.run / 'sample').glob('*.png')):
            if str(path) in self.seen_samples:
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            self.seen_samples.add(str(path))
            thumbnail = pixmap.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = QListWidgetItem(QIcon(thumbnail), path.stem)
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(path.name)
            self.gallery.addItem(item)
            if self.gallery.currentItem() is None:
                self.gallery.setCurrentItem(item)

    def show_sample(self, item, previous=None):
        if item:
            self.selected_sample = item.data(Qt.UserRole)
            self.redraw()

    def redraw(self):
        if self.selected_sample:
            pixmap = QPixmap(self.selected_sample)
            self.image.setPixmap(pixmap.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.redraw()

    def closeEvent(self, event):
        if hasattr(self, 'preparing') and not self.preparing.done():
            event.ignore()
            self.message('Finishing dataset preparation…')
            return
        if self.active():
            event.ignore()
            if self.mode == 'setup':
                self.message('Wait for engine setup to finish before closing.')
                return
            if not self.pending_close:
                dialog = QMessageBox(self)
                dialog.setOption(QMessageBox.DontUseNativeDialog)
                dialog.setWindowTitle('Training is running')
                dialog.setText('Save the current checkpoint and stop before closing?')
                dialog.setStandardButtons(QMessageBox.Save | QMessageBox.Cancel)
                def result(value):
                    if value == QMessageBox.Save:
                        self.pending_close = True
                        self.command('stop')
                dialog.finished.connect(result)
                dialog.open()
                self.dialog = dialog
            return
        atomic_json(CONFIG, asdict(self.collect()))
        atomic_json(CONFIG.with_name('window.json'), {'geometry': bytes(self.saveGeometry()).hex(),
                    'splitter': bytes(self.splitter.saveState()).hex(), 'run': str(self.run) if self.run else ''})
        super().closeEvent(event)


def main():
    if '--setup-engine' in sys.argv:
        from setup_engine import main as setup
        setup()
        return
    app = QApplication(sys.argv)
    app.setApplicationName('moss-trainer')
    app.setDesktopFileName('moss-trainer')
    if is_plasma():
        apply_icon_theme()
        apply_widget_style(app)
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

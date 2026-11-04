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
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from core import ENGINE, Settings, atomic_json, prepare_run

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
        self.pending_close = False
        self.widgets = {}
        self.seen_samples = set()
        self.selected_sample = ''
        self.buffer = ''
        self.started = 0
        self.progress_start = None
        self.eta = ''
        self.build()
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
        for text, handler in [('Open run…', self.open_run), ('Open output folder', self.open_output), ('Quit', self.close)]:
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
        self.spin(train, 'steps', 'Training steps', 1, 1000000)
        self.spin(train, 'resolution', 'Training resolution', 256, 2048, 16)
        self.spin(train, 'rank', 'LoRA rank', 1, 256)
        self.spin(train, 'learning_rate', 'Learning rate', 0.000001, 0.01, 0.00001, decimals=6)
        self.spin(train, 'blocks_to_swap', 'Blocks offloaded to CPU', 0, 36)
        note = QLabel('MOSS-Image-Base · batch size 1 · INT8\nCaptions are optional. Original dataset files stay untouched.')
        note.setWordWrap(True)
        train.addRow(note)
        samples = QFormLayout()
        self.add_tab('Sampling & saving', samples)
        self.interval(samples, 'sample', 'Sample every')
        self.spin(samples, 'sample_count', 'Samples per interval', 1, 16)
        self.text(samples, 'sample_prompt', 'Sample prompt')
        self.text(samples, 'negative_prompt', 'Negative prompt')
        ar = QComboBox()
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
        self.spin(samples, 'seed', 'First sample seed', 0, 2147483647)
        self.interval(samples, 'save', 'Autosave every')
        note = QLabel('Zero disables an interval. Samples reuse the same seeds for comparison.\nEvery save includes the LoRA and resumable optimizer state.')
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
            if isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText()
            elif isinstance(widget, QComboBox):
                value = widget.currentText()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                value = widget.value()
            else:
                value = widget.text()
            values[key] = value
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
        self.tabs.setEnabled(not active)
        if not engine and not active:
            self.status.setText('Set up the training engine before starting.')

    def launch(self, program, arguments, mode):
        self.mode = mode
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

    def resume_run(self):
        if self.active() or not self.run:
            return
        try:
            latest = json.loads((self.run / 'latest.json').read_text())
            self.launch(ENGINE / '.venv/bin/python', ['-u', HERE / 'worker.py', self.run, '--resume', latest['state']], 'training')
        except Exception as exc:
            self.message(str(exc))

    def load_settings(self, settings):
        for key, widget in self.widgets.items():
            value = getattr(settings, key)
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(value)
            else:
                widget.setText(value)
        self.settings = settings

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
        if kind == 'status':
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
            self.progress.setFormat(f"{event['step']} / {event['total']} steps · epoch {event['epoch']:.1f}")
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

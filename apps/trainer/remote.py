"""SSH transport and native client for the persistent top controller."""
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QComboBox, QFileDialog, QInputDialog

import main
from core import Settings, atomic_json
from sampling import LIVE_KEYS, sample_prompts


class Client:
    def __init__(self, host=None):
        self.host = host
        self.cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'moss-trainer'
        self.uploads = self.cache / 'uploads.json'
        self.ssh = ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                    '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']

    def call(self, action, **values):
        command = (self.ssh + [self.host, 'moss-trainer --rpc'] if self.host else
                   [sys.executable, str(main.HERE / 'service.py')])
        result = subprocess.run(command, input=json.dumps(dict(action=action, **values)) + '\n',
                                capture_output=True, text=True, timeout=150)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Controller connection failed')
        response = json.loads(result.stdout)
        if not response['ok']:
            raise RuntimeError(response['error'])
        return response['value']

    def transfer(self, source, destination):
        args = ['rsync', '-rt', '--partial', '--protect-args', '--timeout=120']
        if self.host:
            args += ['-e', shlex.join(self.ssh)]
        result = subprocess.run(args + ['--', source, destination], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Transfer failed; retry to continue')

    def start(self, settings, local_dataset, request_id):
        self.cache.mkdir(parents=True, exist_ok=True)
        with (self.cache / 'upload.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._start(settings, local_dataset, request_id)

    def _start(self, settings, local_dataset, request_id):
        if local_dataset and self.host:
            source = Path(settings['dataset']).expanduser().resolve()
            if not source.is_dir():
                raise ValueError('Choose a dataset folder on book')
            # Retain an upload id across transfer failures. Successful submissions
            # remove it so later runs never overwrite an earlier run's inputs.
            try:
                uploads = json.loads(self.uploads.read_text())
            except (OSError, ValueError):
                uploads = {}
            key = self.host + ':' + str(source)
            token = uploads.setdefault(key, uuid.uuid4().hex)
            atomic_json(self.uploads, uploads)
            target = self.call('upload', token=token)
            # Dereference local image symlinks; top cannot resolve book paths.
            args = ['rsync', '-rtL', '--partial', '--protect-args', '--timeout=120', '--delete',
                    '--include=*/', '--include=*.txt']
            from core import IMAGE_EXTS
            for ext in sorted(IMAGE_EXTS):
                pattern = ''.join('[' + c.lower() + c.upper() + ']' if c.isalpha() else c for c in ext)
                args.append('--include=*' + pattern)
            args += ['--exclude=*', '-e', shlex.join(self.ssh), '--', str(source) + '/', self.host + ':' + target + '/']
            result = subprocess.run(args, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or 'Upload failed; retry to continue')
            settings = dict(settings, dataset=target)
            # Drop the reusable token before submission: ambiguous replies must
            # never allow rsync to mutate the dataset of a started worker.
            uploads.pop(key, None)
            atomic_json(self.uploads, uploads)
        return self.call('start', settings=settings, id=request_id)

    def samples(self, run):
        root = self.cache / 'samples' / hashlib.sha256(run.encode()).hexdigest()
        root.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        for item in reversed(self.call('samples', run=run)):
            name = item['name']
            if Path(name).name != name:
                raise ValueError('Invalid sample filename')
            path = root / name
            stamp = path.with_suffix('.stamp')
            signature = str((item['size'], item['mtime']))
            if path.exists() and stamp.exists() and stamp.read_text() == signature:
                continue
            raw = base64.b64decode(self.call('sample', run=run, name=name), validate=True)
            temporary = path.with_suffix('.pending')
            temporary.write_bytes(raw)
            temporary.replace(path)
            stamp.write_text(signature)
            downloaded += 1
            if downloaded >= 4:
                break
        return root


class Window(main.Window):
    def __init__(self, client):
        self.client = client
        self.connected = False
        self.busy = False
        self.remote_active = False
        self.engine_ready = False
        self.generation = ''
        self.after = 0
        self.run_info = None
        self.sample_root = None
        self.last_samples = 0
        self.remote_started = 0
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.queued = None
        self.event_values = {}
        self.loading = False
        super().__init__()
        self.setWindowTitle('MOSS Trainer — top')
        self.dataset_source = QComboBox()
        self.dataset_source.addItems(['Dataset on top', 'Upload dataset from book'] if client.host else ['Dataset on top'])
        self.tabs.widget(0).widget().layout().insertRow(0, 'Dataset location', self.dataset_source)
        menu = self.menuBar().actions()[0].menu()
        for label, callback in [('Reconnect to training on top', self.reconnect),
                                ('Download latest LoRA…', self.download)]:
            action = QAction(label, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.timer.stop()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(150)
        self.poll_timer.timeout.connect(self.tick)
        self.poll_timer.start()
        self.next_poll = 0
        self.message('Connecting to top…')

    def active(self):
        return self.busy or self.remote_active

    def update_buttons(self):
        if not hasattr(self, 'go'):
            return
        ready = self.connected and not self.busy
        running = ready and self.remote_active and self.mode == 'training'
        self.go.setEnabled(ready and not self.remote_active and self.engine_ready)
        self.resume.setEnabled(ready and not self.remote_active and self.engine_ready and bool(self.run_info and self.run_info['latest']))
        self.install.setEnabled(ready and not self.remote_active)
        self.pause.setEnabled(running and self.state in ('training', 'paused'))
        self.pause.setText('Resume' if self.state == 'paused' else 'Pause')
        self.save.setEnabled(running)
        self.stop.setEnabled(running)
        self.tabs.setEnabled(not self.busy)
        self.tabs.setTabEnabled(0, not self.active())
        self.tabs.setTabEnabled(2, not self.active())
        live = running and self.live_sampling
        self.apply_samples.setEnabled(live)
        self.sample_now.setEnabled(live and self.can_sample_now)
        self.sample_editor.setEnabled(not self.active() or live)
        for key, widget in self.widgets.items():
            if key.startswith('sample_') or key in ('negative_prompt', 'seed', 'save_every', 'save_unit'):
                widget.setEnabled(not self.active() or (live and key in LIVE_KEYS))
        self.sample_ar.setEnabled(not self.active())

    def submit(self, function, callback=None):
        if self.pending is not None:
            if self.queued is None:
                self.queued = (function, callback)
                self.busy = True
                self.update_buttons()
            return
        self.busy = True
        self.pending = (self.pool.submit(function), callback)
        self.update_buttons()

    def tick(self):
        if self.pending:
            future, callback = self.pending
            if not future.done():
                return
            self.pending = None
            self.busy = False
            try:
                result = future.result()
                if callback:
                    callback(result)
            except Exception as exc:
                self.connected = False
                self.message('Request failed / connection unavailable: ' + str(exc) + '\nTraining on top is unaffected. Reconnecting…')
            self.update_buttons()
            self.next_poll = time.monotonic() + 2
            if self.queued:
                function, callback = self.queued
                self.queued = None
                if self.pending is not None:
                    self.queued = (function, callback)
                else:
                    self.submit(function, callback)
        elif time.monotonic() >= self.next_poll:
            self.pending = (self.pool.submit(self.client.call, 'status', after=self.after), self.status_result)
            self.next_poll = time.monotonic() + 2

    def status_result(self, data):
        was_active = self.remote_active
        self.connected = True
        self.remote_active = data['active']
        self.engine_ready = data['engine']
        self.mode, self.state = data['mode'], data['state']
        self.remote_started = data['started']
        if was_active and not self.remote_active:
            self.run_info = None
        if self.generation != data['generation']:
            self.generation = data['generation']
            self.after = 0
            self.progress_start = None
            self.event_values = {}
            self.live_sampling = False
            self.can_sample_now = False
            if data['run']:
                self.run = Path(data['run'])
                self.run_info = None
                self.gallery.clear()
                self.seen_samples.clear()
                self.sample_root = None
        for number, line in data['lines']:
            if number > self.after:
                self.log.appendPlainText(line)
        self.after = data['sequence']
        self.loading = True
        try:
            for event in data['events']:
                kind = event['event']
                if kind not in ('samples', 'status') and self.event_values.get(kind) != event:
                    self.handle_event(event)
                    self.event_values[kind] = event
        finally:
            self.loading = False
        self.state = data['state']
        if self.remote_active and self.remote_started:
            seconds = max(0, int(time.time() - self.remote_started))
            self.clock.setText(f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02} elapsed' + self.eta)
        self.status.setText('top · ' + self.state + (' · training continues when this window closes' if self.remote_active else ''))
        if not self.engine_ready:
            self.status.setText('top · Set up the training engine before starting')
        if self.run and self.run_info is None and self.queued is None:
            run = str(self.run)
            self.pending = (self.pool.submit(self.client.call, 'inspect', run=run), self.inspected)
        elif self.run and self.queued is None and time.monotonic() - self.last_samples > 10:
            self.last_samples = time.monotonic()
            run = str(self.run)
            self.pending = (self.pool.submit(self.client.samples, run), self.samples_ready)
        self.update_buttons()

    def inspected(self, data):
        self.run_info = data
        self.run = Path(data['run'])
        self.dataset_source.setCurrentIndex(0)
        self.loading = True
        try:
            self.load_settings(Settings.from_run(data['settings']))
        finally:
            self.loading = False
        self.update_buttons()

    def samples_ready(self, root):
        self.sample_root = root
        self.scan_samples()

    def scan_samples(self):
        if self.sample_root:
            for path in sorted(self.sample_root.glob('*.png')):
                if str(path) in self.seen_samples:
                    continue
                pixmap = main.QPixmap(str(path))
                if pixmap.isNull():
                    continue
                self.seen_samples.add(str(path))
                item = main.QListWidgetItem(main.QIcon(pixmap.scaled(112, 112, main.Qt.KeepAspectRatio, main.Qt.SmoothTransformation)), path.stem)
                item.setData(main.Qt.UserRole, str(path))
                self.gallery.addItem(item)
                if self.gallery.currentItem() is None:
                    self.gallery.setCurrentItem(item)

    def reconnect(self):
        self.next_poll = 0
        self.after = 0
        self.run_info = None

    def start(self):
        if self.active():
            return
        settings = asdict(self.collect())
        local = self.dataset_source.currentIndex() == 1
        token = uuid.uuid4().hex
        self.message('Uploading and preparing dataset on top…' if local else 'Preparing run on top…')
        self.submit(lambda: self.client.start(settings, local, token), self.submitted)

    def submitted(self, data):
        self.generation = ''  # next status loads authoritative run and settings
        self.run_info = None
        self.next_poll = 0

    def setup(self):
        if not self.active():
            token = uuid.uuid4().hex
            self.submit(lambda: self.client.call('setup', id=token), self.submitted)

    def resume_run(self):
        if not self.active() and self.run:
            run, token = str(self.run), uuid.uuid4().hex
            self.submit(lambda: self.client.call('resume', run=run, id=token), self.submitted)

    def send_control(self, message):
        generation = self.generation
        self.submit(lambda: self.client.call('control', generation=generation, message=message))

    def command(self, command):
        if self.connected and self.remote_active:
            self.send_control({'command': command})

    def apply_sampling(self, *, force=False):
        if self.loading or not (self.connected and self.remote_active and self.live_sampling):
            return
        try:
            settings = self.collect()
            if force or settings.sample_enabled:
                sample_prompts(settings)
            payload = {key: getattr(settings, key) for key in LIVE_KEYS}
            self.sampling_request_id = uuid.uuid4().hex
            payload.update(force=force, request_id=self.sampling_request_id)
            self.send_control({'command': 'sampling', 'sampling': payload})
            self.sampling_status.setText('Sampling request sent to top; applied at the next completed step.')
        except Exception as exc:
            self.sampling_status.setText(str(exc))

    def remote_path(self, title, initial, callback):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText('Absolute path on top')
        dialog.setTextValue(initial)
        dialog.textValueSelected.connect(callback)
        dialog.open()
        self.dialog = dialog

    def browse(self, edit, directory):
        local = (hasattr(self, 'dataset_source') and self.dataset_source.currentIndex() == 1
                 and edit is self.widgets['dataset'])
        if not self.client.host or local:
            return super().browse(edit, directory)
        self.remote_path('Choose path on top', edit.text(), edit.setText)

    def open_run(self):
        def selected(path):
            run = str(Path(path).parent if path.endswith('/run.json') else Path(path))
            self.gallery.clear()
            self.seen_samples.clear()
            self.sample_root = None
            self.submit(lambda: self.client.call('inspect', run=run), self.inspected)
        if self.remote_active or self.busy:
            self.message('Save and stop the current run before opening another.')
            return
        self.remote_path('Open training run on top', str(self.run or Path.home() / 'Pictures/trainer'), selected)

    def open_output(self):
        path = str(self.run or self.widgets['output'].text())
        url = QUrl.fromLocalFile(path)
        if self.client.host:
            url = QUrl()
            url.setScheme('sftp')
            url.setHost(self.client.host)
            url.setPath(path)
        QDesktopServices.openUrl(url)

    def download(self):
        if not self.run:
            return
        run = str(self.run)
        dialog = QFileDialog(self, 'Download latest LoRA')
        dialog.setOption(QFileDialog.DontUseNativeDialog)
        dialog.setFileMode(QFileDialog.Directory)
        def selected(folder):
            def transfer():
                info = self.client.call('inspect', run=run)
                if not info['latest']:
                    raise ValueError('No checkpoint has been saved yet')
                path = info['latest']['lora']
                destination = str(Path(folder) / Path(path).name)
                if Path(destination).exists():
                    raise ValueError('Destination already exists; choose another folder')
                self.client.transfer((self.client.host + ':' if self.client.host else '') + path, destination)
                return destination
            self.submit(transfer, lambda path: self.message('Downloaded ' + path))
        dialog.fileSelected.connect(selected)
        dialog.open()
        self.dialog = dialog

    def closeEvent(self, event):
        # No worker pipe belongs to the GUI. A transfer already in flight may
        # finish, but leaving the window cannot stop training on top.
        if self.busy:
            event.ignore()
            self.message('Wait for the current submission or transfer to finish before closing.')
            return
        self.poll_timer.stop()
        self.pool.shutdown(wait=False)
        atomic_json(main.CONFIG, asdict(self.collect()))
        atomic_json(main.CONFIG.with_name('window.json'), dict(geometry=bytes(self.saveGeometry()).hex(),
                    splitter=bytes(self.splitter.saveState()).hex(), run=str(self.run) if self.run else ''))
        event.accept()

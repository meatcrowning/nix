#!/usr/bin/env python3
"""Isolated submission cancellation, output accounting, and atomic file tests.

Binds actual controller methods to an inert fixture: no Painter constructor,
windows, compositor, clipboard, backend, notifications, or service commands.
"""
import copy
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import zlib

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DESK_SESSION'] = 'hypr'
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
    os.environ.pop(key, None)
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'apps/painter'), str(ROOT / 'apps/pylib')]
from PySide6.QtCore import QCoreApplication
import main as P
from submission import Submission, build_batch
from output_save import OutputSaver, destination, publish
import media_work
import pngmeta
import mp4meta

app = QCoreApplication([])


class Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class Registry:
    def __init__(self):
        self.name = 'original'
        self.reject_seed = None

    def family_of(self, entry):
        return {'id': 'test'}

    def find(self, name):
        return SimpleNamespace(size=10)

    def build(self, entry, params, object_info=None):
        if params['seed'] == self.reject_seed:
            raise P.G.ValidationError(['synthetic invalid second job'])
        return {'prompt': {'model': entry.name, 'registry': self.name},
                'params': copy.deepcopy(params), 'pairing': {}}


class Client:
    def __init__(self):
        self.uploads, self.jobs, self.acks = [], [], []

    def upload_image(self, path, cb):
        self.uploads.append((path, cb))

    def submit(self, prompt, meta):
        job = SimpleNamespace(prompt=prompt, meta=meta, images=[], duration=1,
                              prompt_id='prompt-' + str(len(self.jobs)))
        self.jobs.append(job)
        return job

    def acknowledge(self, job, saved=True):
        self.acks.append((job, saved))

    def cancel_all(self):
        pass


class Warden:
    def __init__(self):
        self.requests, self.releases = [], []

    def reserve(self, backend, cb=None, **kwargs):
        self.requests.append((kwargs, cb))

    def done(self, backend, token=''):
        self.releases.append(token)


class Controller:
    def __init__(self):
        self.reg = Registry()
        self.entry = SimpleNamespace(name='original', family='test', quant='', size=100)
        self.models = SimpleNamespace(entry_at=lambda idx: self.entry)
        self.lora_rows = [{'name': 'original-lora', 'strength': 1}]
        self.loras = SimpleNamespace(active=lambda: self.lora_rows)
        self._selected = 0
        self._object_info = {}
        self._wildcard_options = {}
        self._last_seed = -1
        self._submissions = {}
        self._input_image = '/synthetic/source.png'
        self._last_image = '/synthetic/last.png'
        self._edit_extra = []
        self._edit_uploads = {}
        self.referenceImages = False
        self.editMultipleImages = False
        self.client, self.warden = Client(), Warden()
        self._jobs = self._batch_pending = self._cancel_epoch = 0
        self._preview_serial = 0
        self._batch_saved = []
        self._batch_toasted = False
        self._batch_start = time.time()
        self._job_start = time.time()
        self._busy = False
        self._clock = SimpleNamespace(stop=lambda: None)
        self.gallery_paths = []
        self.gallery = SimpleNamespace(begin_live=lambda *a, **kw: None,
                                       end_live=lambda *a: None,
                                       add=lambda path, *a: self.gallery_paths.append(path))
        self.save_requests = []
        self._output_saver = SimpleNamespace(enqueue=lambda *args: self.save_requests.append(args))
        for name in ('toast', 'lastSeedChanged', 'busyChanged', 'previewChanged',
                     'statusChanged', 'jobCompleted'):
            setattr(self, name, Signal())

    def _set_status(self, value):
        self.status = value

    def _on_log(self, value):
        pass

    def _maybe_notify(self):
        pass

    def _post_toast(self, *args, **kwargs):
        self.toast.emit(*args)


for name in ('generate', '_submission_cancelled', '_preparation_failed',
             '_release_submission', '_upload_edit_then_start', '_upload_then_start',
             '_weight_bytes', '_start_jobs', '_job_submission', '_job_terminal',
             '_on_finished', '_on_saved', '_on_failed', '_on_recovered', 'cancel', '_collage_key',
             '_collage_for', '_mute_for_drag', '_muted_dest', 'dragUriListFor',
             'dragUriList', 'prepareCollage'):
    setattr(Controller, name, getattr(P.Painter, name))


def params(**extra):
    return dict(seed=10, positive='A red fox', negative='', **extra)


def test_lifecycle():
    ctl = Controller()
    ctl.generate(params(), 1)
    assert len(ctl.warden.requests) == 1 and not ctl.client.jobs
    ctl.entry.name = 'changed'
    ctl.reg.name = 'changed'
    ctl.lora_rows[0]['strength'] = 7
    ctl.warden.requests[0][1](True, '')
    job = ctl.client.jobs[0]
    assert job.prompt == {'model': 'original', 'registry': 'original'}
    assert job.meta['params']['loras'][0]['strength'] == 1

    ctl = Controller()
    ctl.generate(params(), 1)
    token = ctl.warden.requests[0][0]['token']
    ctl.cancel()
    ctl.warden.requests[0][1](True, '')
    assert not ctl.client.jobs and token in ctl.warden.releases
    assert not ctl._submissions

    for options in ({'use_input_image': True}, {'edit': True}):
        ctl = Controller()
        ctl.generate(params(**options), 1)
        assert len(ctl.client.uploads) == 1
        ctl.cancel()
        ctl.client.uploads[0][1]('painter/unique.png', '')
        assert not ctl.warden.requests and not ctl.client.jobs

    ctl = Controller()
    ctl.reg.reject_seed = 11
    ctl.generate(params(), 2)
    assert not ctl.client.jobs and not ctl.warden.requests
    assert not ctl._submissions and ctl.toast.calls
    print('PASS frozen inputs; cancelled reserve/uploads; atomic batch validation')


def test_late_saves():
    ctl = Controller()
    ctl.generate(params(), 1)
    ctl.warden.requests[0][1](True, '')
    old = ctl.client.jobs[-1]
    old.images = [{'filename': 'old.png'}]
    ctl._on_finished(old)
    assert ctl._batch_pending == 1 and ctl._jobs == 0
    assert old.meta['submission_id'] in ctl.warden.releases
    ctl.cancel()
    ctl.generate(params(), 1)
    ctl.warden.requests[-1][1](True, '')
    new = ctl.client.jobs[-1]
    new.images = [{'filename': 'new.png'}]
    ctl._on_finished(new)
    assert ctl._batch_pending == 1
    ctl._on_saved(old, old.images[0], '/synthetic/old.png', '')
    assert ctl._batch_pending == 1 and ctl._batch_saved == []
    ctl._on_saved(new, new.images[0], '/synthetic/new.png', '')
    assert ctl._batch_pending == 0 and ctl._batch_saved == ['/synthetic/new.png']
    assert not ctl._submissions and len(ctl.client.acks) == 2
    assert len(ctl.jobCompleted.calls) == 1

    ctl = Controller()
    ctl.generate(params(), 1)
    ctl.warden.requests[0][1](True, '')
    job = ctl.client.jobs[-1]
    job.images = [{'filename': 'failed.png'}]
    ctl._on_finished(job)
    ctl._on_saved(job, job.images[0], '', 'disk full')
    assert ctl.client.acks == [(job, False)]
    assert not ctl.jobCompleted.calls and ctl.toast.calls
    ctl = Controller()
    ctl.generate(params(), 1)
    ctl.warden.requests[0][1](True, '')
    old = ctl.client.jobs[-1]
    old.images = [{'filename': 'late-terminal.png'}]
    ctl.cancel()
    ctl.generate(params(), 1)
    ctl.warden.requests[-1][1](True, '')
    ctl._on_finished(old)
    assert ctl._jobs == 1 and ctl._batch_pending == 0
    ctl._on_failed(old, 'late interruption')
    assert ctl._jobs == 1 and not ctl.toast.calls
    ctl = Controller()
    recovered = SimpleNamespace(meta={}, prompt_id='recovered-cancelled', cancelled=True)
    ctl._on_recovered(recovered)
    assert ctl._jobs == 1 and ctl._busy
    ctl._on_failed(recovered, 'cancelled')
    assert ctl._jobs == 0 and not ctl._busy and not ctl.toast.calls
    print('PASS late saves cannot alter a new batch; failed saves remain recoverable')


def png_bytes():
    return (pngmeta.SIG + pngmeta._chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + pngmeta._chunk(b'paHm', b'saved-attention-maps')
            + pngmeta._chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00'))
            + pngmeta._chunk(b'IEND', b''))


def movie_bytes():
    def moov(offsets):
        tables = b''
        for kind, fmt in ((b'stco', '>II'), (b'co64', '>QQ')):
            tables += mp4meta._box(kind, b'\0' * 4 + struct.pack('>I', 2) + struct.pack(fmt, *offsets))
        for kind in (b'stbl', b'minf', b'mdia', b'trak', b'moov'):
            tables = mp4meta._box(kind, tables)
        return tables
    first = mp4meta._box(b'mdat', b'first-payload')
    mid = moov((0, 0))
    return first + moov((8, len(first) + len(mid) + 8)) + mp4meta._box(b'mdat', b'second-payload')


def test_files(tmp):
    source, dest = tmp / 'source.part', tmp / 'output.png'
    source.write_bytes(png_bytes())
    publish(source, dest, {'params': params()})
    chunks = list(pngmeta._chunks(dest.read_bytes()))
    assert any(kind == b'paHm' and body == b'saved-attention-maps' for kind, body, crc in chunks)
    assert 'painter' in pngmeta.read_text_path(dest)
    assert not source.exists()

    source, dest = tmp / 'movie.part', tmp / 'output.mp4'
    original = movie_bytes()
    source.write_bytes(original)
    publish(source, dest, {'params': params()})
    updated = dest.read_bytes()
    delta = len(updated) - len(original)
    assert delta > 0
    for kind, fmt in ((b'stco', '>II'), (b'co64', '>QQ')):
        path = (b'moov', b'trak', b'mdia', b'minf', b'stbl', kind)
        old, new = mp4meta._find(original, path), mp4meta._find(updated, path)
        before = struct.unpack_from(fmt, original, old[0] + old[1] + 8)
        after = struct.unpack_from(fmt, updated, new[0] + new[1] + 8)
        assert after == (before[0], before[1] + delta)
        assert updated[after[0]:after[0] + 13] == b'first-payload'
        assert updated[after[1]:after[1] + 14] == b'second-payload'
    assert 'painter' in mp4meta.read_tags_path(dest)

    source, dest = tmp / 'broken.part', tmp / 'existing.png'
    source.write_bytes(png_bytes())
    dest.write_bytes(b'previous complete output')
    original_writer = pngmeta.upsert_text_file
    def fail(*_):
        raise OSError('synthetic disk failure')
    try:
        pngmeta.upsert_text_file = fail
        try:
            publish(source, dest, {'params': params()})
            raise AssertionError('write failure did not propagate')
        except OSError:
            pass
        assert dest.read_bytes() == b'previous complete output'
    finally:
        pngmeta.upsert_text_file = original_writer
    for image in ({'filename': '../escape.png'}, {'filename': 'x', 'subfolder': '../../'},
                  {'filename': '/absolute.png'}):
        try:
            destination(tmp, image)
            raise AssertionError('unsafe path accepted')
        except ValueError:
            pass
    print('PASS atomic publication, paHm preservation, stco/co64 media offsets, path containment')


def test_saver(tmp):
    pending, finished = [], []
    def download(image, path, callback):
        pending.append((path, callback))
    saver = OutputSaver(SimpleNamespace(download_to_file=download), tmp)
    saver.finished.connect(lambda *args: finished.append(args))
    job = SimpleNamespace(meta={'params': params()})
    for i in range(3):
        saver.enqueue(job, {'filename': '%d.png' % i})
    assert len(pending) == 2 and saver.active == 2
    deadline = time.monotonic() + 5
    while len(finished) < 3 and time.monotonic() < deadline:
        for path, callback in list(pending):
            pending.remove((path, callback))
            path.write_bytes(png_bytes())
            callback(str(path), '')
        app.processEvents()
        time.sleep(.005)
    saver.pool.waitForDone()
    app.processEvents()
    assert len(finished) == 3 and all(path and not error for _, _, path, error in finished)
    assert saver.active == 0 and not saver.workers
    print('PASS bounded streamed transfer and worker publication')


def test_drag(tmp):
    ctl = Controller()
    queued = []
    ctl._derivatives = SimpleNamespace(prepare=lambda key, fn: queued.append((key, fn)))
    ctl.gallery.cache_stamp = lambda path: 'synthetic-stamp'
    ctl._build_collage = lambda paths, dest, key: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b'ready'))
    ctl._prepare_muted = lambda src, dest: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b'ready'))
    previous = P.CACHE
    P.CACHE = tmp
    try:
        assert ctl.dragUriListFor(['/synthetic/a.png', '/synthetic/b.png']) == ''
        assert len(queued) == 1 and queued[0][0].startswith('collage:')
        queued.pop()[1]()
        assert ctl.dragUriListFor(['/synthetic/a.png', '/synthetic/b.png']).startswith('file:')
        assert ctl.dragUriList('/synthetic/clip.mp4') == ''
        assert len(queued) == 1 and queued[0][0].startswith('muted:')
        queued.pop()[1]()
        assert ctl.dragUriList('/synthetic/clip.mp4').startswith('file:')
    finally:
        P.CACHE = previous
    print('PASS dragging schedules missing derivatives without waiting or building synchronously')


def pump_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    assert predicate(), 'worker fixture timed out'


def test_media_workers():
    decoder = media_work.PreviewDecoder()
    started, release = threading.Event(), threading.Event()
    decoded, displayed = [], []
    original_run = media_work._Preview.run

    def controlled_decode(work):
        decoded.append(work.meta)
        if work.meta == 0:
            started.set()
            if not release.wait(3):
                raise RuntimeError('decode fixture timed out')
        original_run(work)

    media_work._Preview.run = controlled_decode
    decoder.ready.connect(lambda image, meta: displayed.append((image.size(), meta)))
    try:
        decoder.submit(png_bytes(), 'png', 0)
        assert started.wait(1)
        for frame in range(1, 21):
            decoder.submit(png_bytes(), 'png', frame)
        assert decoder.active is not None and decoder.latest[2] == 20
        release.set()
        pump_until(lambda: decoder.active is None and decoder.latest is None)
        assert decoded == [0, 20], decoded
        assert [meta for _, meta in displayed] == [20], displayed
        assert displayed[0][0].width() == 1
    finally:
        release.set()
        decoder.pool.waitForDone()
        media_work._Preview.run = original_run

    derivatives = media_work.Derivatives()
    release = threading.Event()
    invoked = []
    def work(number):
        invoked.append(number)
        if number < 2 and not release.wait(3):
            raise RuntimeError('derivative fixture timed out')
    try:
        for number in range(10):
            derivatives.prepare(str(number), lambda n=number: work(n))
        assert len(derivatives.active) == 2 and len(derivatives.pending) == 2
        assert set(derivatives.pending) == {'8', '9'}
        release.set()
        pump_until(lambda: not derivatives.active and not derivatives.pending)
        assert set(invoked) == {0, 1, 8, 9}, invoked
    finally:
        release.set()
        derivatives.pool.waitForDone()
    print('PASS preview drops superseded frames; derivatives execute only active and newest pending tasks')


with tempfile.TemporaryDirectory(prefix='painter-submission-test-') as scratch:
    tmp = Path(scratch)
    test_lifecycle()
    test_late_saves()
    test_files(tmp)
    test_saver(tmp / 'saved')
    test_drag(tmp / 'derivatives')
    test_media_workers()
print('all submission/output checks passed')

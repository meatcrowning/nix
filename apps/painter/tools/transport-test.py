#!/usr/bin/env python3
"""Isolated transport faults: synthetic replies/files, no backend or GUI effects."""
import ast
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types

if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
    raise SystemExit('Run with QT_QPA_PLATFORM=offscreen and the offscreen session guard.')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtNetwork
import comfy
from job_journal import JobJournal

app = QtCore.QCoreApplication([])
checks = 0

def check(value, name):
    global checks
    assert value, name
    checks += 1
    print('ok:', name)

class Reply:
    def __init__(self, doc, error=False):
        self.doc, self.bad = doc, error
    def readAll(self):
        return json.dumps(self.doc).encode()
    def error(self):
        return QtNetwork.QNetworkReply.NetworkError.ConnectionRefusedError if self.bad else QtNetwork.QNetworkReply.NetworkError.NoError
    def errorString(self):
        return 'synthetic connection failure'
    def deleteLater(self):
        pass

check(comfy._upload_name('/a/image.png') != comfy._upload_name('/b/image.png'), 'same-basename uploads have unique immutable names')
check('\n' not in comfy._upload_name('image.png\nheader'), 'upload filenames cannot inject multipart headers')
c = comfy.ComfyClient()
posts = []
c._post = lambda path, body, cb=None: posts.append((path, body, cb))
c.cancel_all()
check(not posts, 'empty client cancellation never interrupts backend')
submitted = c.submit({'1': {'class_type': 'SaveImage', 'inputs': {}}}, {
    'params': {'seed': 17}, 'pairing': {'family_id': 'family', 'model': types.SimpleNamespace(name='model')}})
payload = posts.pop()[1]
check(payload['extra_data']['painter_request_id'] == submitted.request_id
      and payload['extra_data']['extra_pnginfo']['painter']['model'] == 'model'
      and payload['extra_data']['extra_pnginfo']['painter']['seed'] == 17,
      'backend output receives complete Painter metadata alongside recovery marker')
c._pending.remove(submitted)
submitted.setParent(None)
submitted.deleteLater()
j = comfy.Job({}, parent=c)
j.prompt_id, j.owner_id = 'ours', c.client_id
c._jobs[j.prompt_id] = j
c._active = j
check(c._job_for({'prompt_id': 'foreign'}) is None, 'foreign prompt cannot mutate active job')
check(c._job_for({}) is j, 'legacy events without identifiers retain active fallback')
c._get = lambda path, cb: cb(Reply({}, error=True))
before = len(posts)
c.stop_and_save()
check(len(posts) == before, 'old backend soft-stop endpoint is never called without ownership capability')
c._get = lambda path, cb: cb(Reply({'ownership_version': 1}))
c.stop_and_save()
check(posts[-1][0] == '/painter/stop' and posts[-1][1]['prompt_id'] == 'ours', 'soft stop carries explicit owner and prompt')
c.cancel_all()
check(all(p != '/interrupt' for p, _, _ in posts), 'cancellation never calls global interrupt')
check(j.terminal and not c._jobs and j.parent() is None, 'cancel releases tracking and QObject ownership')

finished = []
c.jobFinished.connect(finished.append)
for n in range(100):
    job = comfy.Job({}, parent=c)
    job.prompt_id = str(n)
    job.images = [{'filename': 'fake.png'}]
    c._jobs[job.prompt_id] = job
    c._complete(job)
check(not [x for x in c.children() if isinstance(x, comfy.Job)], '100 completed jobs leave no parent-owned Job objects')
check(len(finished) == 100, 'each terminal job emits completion once')
c._complete(finished[-1])
check(len(finished) == 100, 'duplicate completion is idempotent')
finished.clear()

job = comfy.Job({'1': {'_meta': {'painter_role': 'save'}}}, parent=c)
job.prompt_id = 'missed'
c._jobs['missed'] = job
history = {'missed': {'outputs': {'1': {'images': [{'filename': 'result.png'}]}}, 'status': {'completed': True}}}
c._get = lambda path, cb: cb(Reply(history))
c.reconcile_outstanding()
check(job.terminal and job.images[0]['role'] == 'save', 'reconnect recovers missed completion from history')

race = comfy.Job({}, parent=c)
race.prompt_id = 'race'
c._jobs['race'] = race
waiting = []
c._get = lambda path, cb: waiting.append((path, cb))
c._reconcile(race, check_queue=True)
waiting.pop(0)[1](Reply({}))
check(race.reconciling and waiting[0][0] == '/queue', 'history-to-queue handoff retains reconciliation lock')
c._reconcile(race, check_queue=True)
check(len(waiting) == 1, 'concurrent recovery requests are coalesced')
waiting.pop(0)[1](Reply({'queue_running': [], 'queue_pending': []}))
check(race.reconciling and waiting[0][0] == '/history/race', 'queue disappearance rechecks history before failure')
waiting.pop(0)[1](Reply({'race': {'outputs': {'1': {'images': [{'filename': 'race.png'}]}}}}))
check(race.terminal and not race.error, 'completion between history and queue reads survives')

unknown = comfy.Job({}, parent=c)
unknown.owner_id = c.client_id
c._pending.append(unknown)
row = [0, 'accepted', {}, {'client_id': c.client_id, 'painter_request_id': unknown.request_id}]
queries = []
def get(path, cb):
    queries.append(path)
    cb(Reply({'queue_running': [], 'queue_pending': [row]} if path == '/queue' else {}))
c._get = get
c._find_pending(unknown)
check(unknown.prompt_id == 'accepted' and unknown not in c._pending, 'lost submission acknowledgement resolves by request identity')
check(not any(path == '/prompt' for path, _, _ in posts), 'recovery never blindly resubmits')

cancelled = comfy.Job({}, parent=c)
cancelled.prompt_id, cancelled.owner_id, cancelled.cancelled = 'cancel-recover', 'old-client', True
c._jobs[cancelled.prompt_id] = cancelled
cancel_row = [0, cancelled.prompt_id, {}, {'client_id': cancelled.owner_id}]
def cancel_get(path, cb):
    cb(Reply({'queue_running': [cancel_row], 'queue_pending': []} if path == '/queue'
             else {'ownership_version': 1} if path == '/painter/control' else {}))
c._get = cancel_get
c._reconcile(cancelled, check_queue=True)
check(cancelled.terminal and any(path == '/painter/interrupt' and body['prompt_id'] == cancelled.prompt_id
      for path, body, _ in posts), 'recovery retries cancellation only for the recorded owned job')
failed = []
c.jobFailed.connect(lambda job, error: failed.append(error))
c._get = lambda path, cb: cb(Reply({}))
c._reconcile(unknown, check_queue=True)
check(unknown.terminal and unknown.recovery_required and failed, 'missing queue/history is explicit and remains recoverable')

with tempfile.TemporaryDirectory(prefix='painter-transport-') as root:
    serial = comfy.ComfyClient(journal_dir=Path(root) / 'serial')
    paired = comfy.Job({}, {'params': {'seed': 42}, 'pairing': {
        'family_id': 'test-family', 'model': types.SimpleNamespace(name='model.safetensors'),
        'encoder': types.SimpleNamespace(name='encoder.safetensors'), 'vae': None}}, parent=serial)
    serial._remember(paired)
    stored = json.loads(serial._journal.path.read_text())['jobs'][paired.request_id]['meta']
    check(stored['params']['model'] == 'model.safetensors' and stored['params']['seed'] == 42
          and stored['params']['family'] == 'test-family' and 'pairing' not in stored,
          'journal flattens registry objects into lossless output metadata')
    serial.close()
    serial._journal.close()
    active = JobJournal(root, 'active', 'backend')
    active.put('a', {'request_id': 'a', 'prompt_id': 'p'})
    receiver = JobJournal(root, 'receiver', 'backend')
    check(receiver.recover() == [], 'recovery cannot steal another live window journal')
    active.close()
    check(receiver.recover()[0]['request_id'] == 'a', 'closed/crashed window journal can be claimed')
    other = JobJournal(root, 'other', 'different-backend')
    other.put('b', {'request_id': 'b'})
    other.close()
    check(receiver.recover() == [], 'recovery isolates different backends')
    receiver.remove('a')
    check(not json.loads(receiver.path.read_text())['jobs'], 'save acknowledgement removes durable job')
    receiver.close()

    data = b'chunk' * 200000
    class Response(io.BytesIO):
        headers = {'Content-Length': str(len(data))}
    old = comfy.urllib.request.urlopen
    comfy.urllib.request.urlopen = lambda *a, **k: Response(data)
    try:
        path = Path(root) / 'result.bin'
        task = comfy._Download('http://unused.invalid', path)
        result = []
        task.signals.done.connect(lambda path, error: result.append((path, error)))
        task.run()
        check(path.read_bytes() == data and result[0][1] == '', 'streaming download publishes exact complete file')
        delivered = []
        c.download_to_file({'filename': 'mock.bin'}, Path(root) / 'thread.bin',
                           lambda path, error: delivered.append((path, error, threading.get_ident())))
        deadline = time.monotonic() + 5
        while not delivered and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.001)
        check(delivered and delivered[0][2] == threading.get_ident() and not c._downloads,
              'worker download callbacks return to Qt thread and release retained workers')
        class Truncated(Response):
            headers = {'Content-Length': str(len(data) + 1)}
        comfy.urllib.request.urlopen = lambda *a, **k: Truncated(data)
        task = comfy._Download('http://unused.invalid', path)
        task.signals.done.connect(lambda path, error: result.append((path, error)))
        task.run()
        check(result[-1][0] is None and path.read_bytes() == data, 'truncated download leaves prior destination intact')
        check(not list(Path(root).glob('*.part')), 'failed download cleans temporary files')
    finally:
        comfy.urllib.request.urlopen = old

# Exercise actual backend ownership predicate without importing torch/Comfy.
source = Path(__file__).resolve().parents[1] / 'comfy_nodes/painter_partial_stop.py'
tree = ast.parse(source.read_text())
fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_owned_request')
queue = types.SimpleNamespace(mutex=threading.Lock(), currently_running={0: [0, 'ours', {}, {'client_id': 'owner'}]})
namespace = {'PromptServer': types.SimpleNamespace(instance=types.SimpleNamespace(prompt_queue=queue))}
exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), namespace)
called = []
request = namespace['_owned_request']
check(not request({'prompt_id': 'ours', 'client_id': 'foreign'}, lambda: called.append(1)), 'backend refuses foreign owner')
check(not request({'prompt_id': 'old', 'client_id': 'owner'}, lambda: called.append(1)), 'backend refuses stale prompt')
check(request({'prompt_id': 'ours', 'client_id': 'owner'}, lambda: True), 'backend accepts exact running job ownership')
check(not called, 'rejected ownership executes no interrupt')
c.close()
print('%d transport checks passed' % checks)

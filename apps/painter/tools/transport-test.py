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
c._active = None
c.stop_job_and_save(j)
check(posts[-1][0] == '/painter/stop' and posts[-1][1]['prompt_id'] == 'ours',
      'per-job Stop uses owned soft-stop endpoint even if another job is active')
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
# Reordering preserves IDs and payloads, and cannot race a job starting.
import heapq
fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_reorder_owned')
namespace['heapq'] = heapq
exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), namespace)
queue.server = types.SimpleNamespace(queue_updated=lambda: None)
queue.queue = [(1, 'one', {'graph': 1}, {'client_id': 'owner'}),
               (2, 'foreign', {}, {'client_id': 'other'}),
               (3, 'two', {'graph': 2}, {'client_id': 'owner'})]
reorder = namespace['_reorder_owned']
check(reorder({'prompt_ids': ['one', 'two'], 'client_id': 'owner'}), 'owned pending jobs can swap')
check([r[1] for r in sorted(queue.queue)] == ['two', 'foreign', 'one'], 'foreign queue position is preserved')
check(next(r for r in queue.queue if r[1] == 'one')[2] == {'graph': 1}, 'reorder preserves exact graph identity')
before = list(queue.queue)
check(not reorder({'prompt_ids': ['one', 'foreign'], 'client_id': 'owner'}) and queue.queue == before,
      'reorder refuses another window without mutation')
check(not reorder({'prompt_ids': ['one', 'ours'], 'client_id': 'owner'}) and queue.queue == before,
      'queue-to-running race refuses reorder without mutation')
check(not reorder({'prompt_ids': ['one', 'one'], 'client_id': 'owner'}), 'duplicate IDs cannot corrupt the heap')

queue.queue = [(1, 'one', {}, {'client_id': 'owner'}),
               (2, 'foreign', {}, {'client_id': 'other'}),
               (3, 'two', {}, {'client_id': 'owner'}),
               (4, 'three', {}, {'client_id': 'owner'})]
check(reorder({'prompt_ids': ['three', 'one', 'two'], 'client_id': 'owner', 'ordered': True}),
      'drag can reorder an owned range atomically')
check([r[1] for r in sorted(queue.queue)] == ['three', 'foreign', 'one', 'two'],
      'insertion preserves intervening job order and foreign priority slots')
before = list(queue.queue)
check(not reorder({'prompt_ids': ['one', 'two', 'ours'], 'client_id': 'owner', 'ordered': True})
      and queue.queue == before, 'a started job rejects the whole dragged range without partial changes')

from job_queue import JobQueue
class Controller(QtCore.QObject):
    toast = QtCore.Signal(str, bool)
controller = Controller()
controller.client = comfy.ComfyClient()
controller._submissions = {}
model = JobQueue(controller)
model._timer.stop()
jobs = []
for index, seed in enumerate([17, 18, 19]):
    j = comfy.Job({}, {'params': {'positive': 'fox' if index < 2 else 'wolf', 'seed': seed}}, parent=controller.client)
    j.prompt_id, j.owner_id = str(index), controller.client.client_id
    controller.client._jobs[j.prompt_id] = j
    jobs.append(j)
def snapshot():
    return {'queue_running': [[0, '0']], 'queue_pending': [[2, '2'], [1, '1']]}
controller.client._get = lambda path, cb: cb(Reply(snapshot()))
model.refresh()
check([r['seed'] for r in model.rows] == ['17', '18', '19'], 'queue uses backend priority order, not heap order')
check(model.rows[0]['state'] == 'Running' and not model.rows[0]['canDown'], 'running job cannot move')
check(model.rows[1]['prompt'] == 'fox' and model.rows[1]['seed'] == '18', 'rerolls retain frozen prompt and distinct seed')
check(model.rows[2]['prompt'] == 'wolf', 'edited prompt identifies its own job')
check(model.rows[0]['promptLabel'] == model.rows[1]['promptLabel'] != model.rows[2]['promptLabel'],
      'prompt revisions share labels across seed rerolls but distinguish edits')
soft = []
controller.client.stop_job_and_save = lambda job, cb: soft.append((job, cb))
check(model.rows[0]['canStop'] and not model.rows[1]['canStop'] and model.rows[1]['canCancel'],
      'only running jobs offer Stop; waiting jobs offer Cancel')
model.stop(jobs[1].request_id)
check(not soft, 'Stop never cancels a waiting job')
model.stop(jobs[0].request_id)
check(soft[0][0] is jobs[0] and not jobs[0].cancelled and not jobs[0].terminal,
      'Stop sends a soft stop for this job and retains its output lifecycle')
check(not model.rows[0]['canStop'] and model.rows[0]['canCancel'], 'stop request disables duplicate soft stops but retains Cancel')
soft[0][1](False, 'Not sampling')
check(model.rows[0]['canStop'], 'refused soft stop restores the control')
requests = []
controller.client._post = lambda path, body, cb=None: requests.append((path, body, cb))
model.move(jobs[2].request_id, -1)
check(requests[-1][0] == '/painter/reorder' and requests[-1][1]['prompt_ids'] == ['2', '1'],
      'move addresses stable job IDs')
check(not any(r['canUp'] or r['canDown'] for r in model.rows), 'overlapping moves are disabled until acknowledged')
errors = []
controller.toast.connect(lambda message, bad: errors.append(message))
requests[-1][2](Reply({}, error=True))
check(errors and len(requests) == 1, 'old backend refusal is visible and never resubmits jobs')
model.move(jobs[2].request_id, -1)
controller.client._get = lambda *args: None  # delay the next queue snapshot
requests[-1][2](Reply({'reordered': True}))
check([r['seed'] for r in model.rows] == ['17', '19', '18'], 'acknowledged reorder updates neighbors before the next click')
numbers = {r['id']: r['number'] for r in model.rows}
model._fetching = False
model.moveTo(jobs[1].request_id, jobs[2].request_id, False)
check(requests[-1][1]['prompt_ids'] == ['1', '2'] and requests[-1][1]['ordered'],
      'drop names the desired order using stable IDs')
requests[-1][2](Reply({'reordered': True}))
check(numbers == {r['id']: r['number'] for r in model.rows}, 'job numbers survive reordering')
count = len(requests)
model.moveTo(jobs[0].request_id, jobs[1].request_id, True)
check(len(requests) == count, 'running jobs cannot be dragged into the waiting queue')
model.setDragging(True)
rows = model.rows
model._snapshot = {'queue_running': [], 'queue_pending': []}
model.publish()
check(model.rows == rows, 'polling does not destroy delegates during a drag')
model.setDragging(False)
check(all(r['state'] == 'Checking status' for r in model.rows), 'drag release reconciles fresh status')
model._snapshot = snapshot()
model.publish()
# Cancelling preparation invalidates delayed upload/reservation callbacks.
from submission import Submission
sub = Submission.freeze({'positive': 'pending', 'seed': 12}, types.SimpleNamespace(name='fixture'), None, {}, 1, [], -1)
controller._submissions[sub.id] = sub
released = []
controller._release_submission = released.append
model.publish()
check(any(r['id'] == sub.id and r['state'] == 'Preparing' for r in model.rows), 'preparing submissions are visible and stoppable')
model.cancel(sub.id)
check(sub.cancelled and released == [sub] and sub.id not in controller._submissions,
      'stopping preparation releases its lease and invalidates delayed callbacks')
cancelled = []
controller.client.cancel = cancelled.append
model.cancel(jobs[1].request_id)
check(cancelled == [jobs[1]], 'cancel targets only the selected job')
controller.client.close()
c.close()
# Queue clearing never interrupts, including a queue-to-running race.
q = comfy.ComfyClient()
requests = []
queue_rows = {'queue_running': [[0, 'running']], 'queue_pending': []}
history_rows = {}
def queue_get(path, cb):
    cb(Reply(queue_rows if path == '/queue' else history_rows))
def queue_post(path, body, cb=None):
    requests.append((path, body))
    if cb:
        cb(Reply({}))
q._get, q._post = queue_get, queue_post
running = comfy.Job({}, parent=q)
running.prompt_id, running.owner_id = 'running', q.client_id
waiting = comfy.Job({}, parent=q)
waiting.prompt_id, waiting.owner_id = 'waiting', q.client_id
q._jobs = {'running': running, 'waiting': waiting}
q._active = running
q.cancel_queued()
check(not running.cancelled and not running.terminal and q._active is running,
      'queue clearing preserves a job that is already running or wins the start race')
check(waiting.cancelled and waiting.terminal and waiting.error == 'cancelled',
      'confirmed queue deletion retires waiting jobs without an error toast')
check(all(path == '/queue' for path, body in requests), 'queue clearing sends no interrupt requests')
# The submit callback is captured separately to exercise a late acknowledgement.
callbacks = []
q._post = lambda path, body, cb=None: callbacks.append((path, body, cb))
late = q.submit({}, {})
submit_callback = callbacks.pop()[2]
q.cancel_queued_job(late)
check(not callbacks and not late.cancelled, 'unacknowledged queue cancellation waits without discarding results')
q._post = queue_post
submit_callback(Reply({'prompt_id': 'late'}))
check(late.terminal and late.cancelled and requests[-1] == ('/queue', {'delete': ['late']}),
      'late acknowledgement deletes only that queued job')
completed = comfy.Job({}, parent=q)
completed.prompt_id, completed.owner_id = 'completed', q.client_id
q._jobs['completed'] = completed
history_rows = {'completed': {'outputs': {'1': {'images': [{'filename': 'saved.png'}]}}}}
q.cancel_queued_job(completed)
check(completed.terminal and completed.images and not completed.cancelled,
      'a job that finishes during queue clearing keeps its output')
hard_waiting = comfy.Job({}, parent=q)
hard_waiting.prompt_id, hard_waiting.owner_id = 'hard-waiting', q.client_id
q._jobs['hard-waiting'] = hard_waiting
q._get = lambda path, cb: cb(Reply({'ownership_version': 1}))
q.cancel_all()
check(running.cancelled and running.terminal and hard_waiting.cancelled and hard_waiting.terminal,
      'hard stop cancels both running and queued jobs')
check(any(path == '/painter/interrupt' and body['prompt_id'] == 'running' for path, body in requests),
      'hard stop interrupts the owned running job explicitly')
q.close()
print('%d transport checks passed' % checks)

"""Owned job queue shared by the Qt and GTK frontends."""
import collections
import hashlib
import json

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer


class JobQueue(QObject):
    changed = Signal()

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.client = controller.client
        self._prompts = collections.OrderedDict()
        self._prompt_serial = 0
        self._numbers = collections.OrderedDict()
        self._job_serial = 0
        self._dragging = False
        self._stopping = set()
        self._rows = []
        self._snapshot = None
        self._fetching = False
        self._moving = False
        self._revision = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    rows = Property('QVariantList', lambda self: self._rows, notify=changed)

    def jobs(self):
        return [j for j in list(self.client._jobs.values()) + self.client._pending
                if not j.terminal]

    def refresh(self):
        jobs = self.jobs()
        self.publish()
        if not jobs or self._fetching or self._moving:
            return
        self._fetching = True
        revision = self._revision

        def received(reply):
            try:
                doc = self.client._read_json(reply)
                if revision == self._revision:
                    self._snapshot = doc
            except (ValueError, TypeError):
                if revision == self._revision:
                    self._snapshot = None
            finally:
                reply.deleteLater()
                self._fetching = False
            self.publish()

        self.client._get('/queue', received)

    def prompt_label(self, params):
        boxes = params.get('prompt_boxes', params)
        key = hashlib.sha256(json.dumps([boxes.get('positive', ''), boxes.get('negative', ''),
                                         params.get('moss_layout')], sort_keys=True).encode()).digest()
        if key not in self._prompts:
            self._prompt_serial += 1
            self._prompts[key] = 'Prompt %d' % self._prompt_serial
        self._prompts.move_to_end(key)
        while len(self._prompts) > 4096:
            self._prompts.popitem(last=False)
        return self._prompts[key]

    def job_number(self, request_id):
        if request_id not in self._numbers:
            self._job_serial += 1
            self._numbers[request_id] = self._job_serial
        self._numbers.move_to_end(request_id)
        while len(self._numbers) > 4096:
            self._numbers.popitem(last=False)
        return self._numbers[request_id]

    @Slot(bool)
    def setDragging(self, dragging):
        # Keep delegates alive until release; validate against live jobs on drop.
        self._dragging = dragging
        if not dragging:
            self.publish()

    def publish(self):
        if self._dragging:
            return
        snapshot = self._snapshot or {}
        pending = [r[1] for r in sorted(snapshot.get('queue_pending', []), key=lambda r: r[0])]
        running = {r[1] for r in snapshot.get('queue_running', [])}
        jobs = self.jobs()
        self._stopping.intersection_update(j.request_id for j in jobs)
        jobs.sort(key=lambda j: (-1 if j.prompt_id in running else
                                pending.index(j.prompt_id) if j.prompt_id in pending else len(pending)))
        rows = []
        waiting = [j for j in jobs if j.prompt_id in pending and j.prompt_id not in running]
        for job in jobs:
            p = job.meta.get('params', {})
            prompt = p.get('prompt_boxes', {}).get('positive', p.get('positive', ''))
            model = str(p.get('model') or getattr(job.meta.get('pairing', {}).get('model'), 'name', ''))
            state = ('Stopping and saving' if job.request_id in self._stopping else
                     'Cancelling' if job.cancelled else 'Running' if job.prompt_id in running
                     else 'Waiting' if job.prompt_id in pending else
                     'Submitting' if not job.prompt_id else 'Checking status')
            i = waiting.index(job) if job in waiting else -1
            rows.append(dict(id=job.request_id, label=job.request_id[:8], prompt=prompt,
                             promptLabel=self.prompt_label(p), number=self.job_number(job.request_id),
                             seed=str(p.get('seed', '?')), model=model,
                             details='Positive: ' + prompt + '\n\nNegative: ' + p.get('negative', '')
                             + '\n\nSeed: ' + str(p.get('seed', '?')) + '\nModel: ' + model
                             + '\nSize: %s × %s · Steps: %s' % (p.get('width', '?'), p.get('height', '?'), p.get('steps', '?')),
                             state=state, canStop=state == 'Running', canCancel=not job.cancelled,
                             canDrag=not self._moving and i >= 0 and not job.cancelled,
                             canUp=not self._moving and i > 0 and waiting[i-1].owner_id == job.owner_id,
                             canDown=not self._moving and 0 <= i < len(waiting)-1 and waiting[i+1].owner_id == job.owner_id))
        for sub in self.controller._submissions.values():
            if sub.state not in ('preparing', 'reserving') or sub.cancelled:
                continue
            p = sub.params
            prompt = p.get('positive', '')
            rows.append(dict(id=sub.id, label=sub.id[:8], prompt=prompt,
                             promptLabel=self.prompt_label(p), number=self.job_number(sub.id),
                             seed='assigning' if p.get('randomSeed') else str(p.get('seed', '?')),
                             model=getattr(sub.entry, 'name', ''), details=prompt,
                             state=('Preparing %d jobs' % sub.count if sub.count > 1 else 'Preparing'),
                             canStop=False, canCancel=True, canDrag=False, canUp=False, canDown=False))
        if rows != self._rows:
            self._rows = rows
            self.changed.emit()

    @Slot(str)
    def stop(self, request_id):
        job = next((j for j in self.jobs() if j.request_id == request_id), None)
        running = {r[1] for r in (self._snapshot or {}).get('queue_running', [])}
        if (not job or job.cancelled or request_id in self._stopping
                or (job.prompt_id not in running and self.client._active is not job)):
            return
        self._stopping.add(request_id)
        self.publish()

        def stopped(ok, detail):
            if not ok:
                self._stopping.discard(request_id)
                self.controller.toast.emit(detail or 'This job is not sampling.', True)
            self.refresh()

        self.client.stop_job_and_save(job, stopped)

    @Slot(str)
    def cancel(self, request_id):
        sub = self.controller._submissions.get(request_id)
        if sub and sub.state in ('preparing', 'reserving'):
            sub.cancel()
            self.controller._release_submission(sub)
            self.controller._submissions.pop(sub.id, None)
            self.publish()
            return
        job = next((j for j in self.jobs() if j.request_id == request_id), None)
        if job:
            self.client.cancel(job)
            self.refresh()

    @Slot(str, int)
    def move(self, request_id, direction):
        if self._moving or direction not in (-1, 1):
            return
        self.publish()
        row = next((r for r in self._rows if r['id'] == request_id), None)
        if not row or not row['canUp' if direction < 0 else 'canDown']:
            return
        waiting = [r for r in self._rows if r['state'] == 'Waiting']
        other = waiting[waiting.index(row) + direction]
        jobs = {j.request_id: j for j in self.jobs()}
        job, peer = jobs[request_id], jobs[other['id']]
        self._reorder(job, [peer.prompt_id, job.prompt_id] if direction > 0
                      else [job.prompt_id, peer.prompt_id])

    @Slot(str, str, bool)
    def moveTo(self, request_id, target_id, after):
        if self._moving or request_id == target_id:
            return
        self.publish()
        waiting = [r for r in self._rows if r['state'] == 'Waiting' and r['canDrag']]
        ids = [r['id'] for r in waiting]
        if request_id not in ids or target_id not in ids:
            return
        original = list(ids)
        ids.remove(request_id)
        ids.insert(ids.index(target_id) + int(after), request_id)
        changed = [i for i in range(len(ids)) if ids[i] != original[i]]
        if not changed:
            return
        segment = ids[min(changed):max(changed) + 1]
        jobs = {j.request_id: j for j in self.jobs()}
        job = jobs.get(request_id)
        if not job or any(key not in jobs or jobs[key].owner_id != job.owner_id for key in segment):
            return
        self._reorder(job, [jobs[key].prompt_id for key in segment])

    def _reorder(self, job, order):
        self._moving = True
        self._revision += 1
        self.publish()

        def received(reply):
            try:
                doc = self.client._read_json(reply)
                if not doc.get('reordered'):
                    raise ValueError(doc.get('error', 'Queue changed; try again.'))
                # Reflect the acknowledged order before allowing another drag.
                pending = [list(r) for r in (self._snapshot or {}).get('queue_pending', [])]
                selected = {r[1]: r for r in pending if r[1] in order}
                if len(selected) == len(order):
                    priorities = sorted(r[0] for r in selected.values())
                    for pid, priority in zip(order, priorities):
                        selected[pid][0] = priority
                    self._snapshot = dict(self._snapshot, queue_pending=pending)
            except (ValueError, TypeError) as exc:
                self.controller.toast.emit('Could not reorder jobs: %s' % exc, True)
            finally:
                reply.deleteLater()
                self._moving = False
            self.refresh()

        # This endpoint only reorders waiting, owned jobs under the queue lock.
        # An older backend returns 404 without changing or resubmitting anything.
        self.client._post('/painter/reorder', dict(client_id=job.owner_id,
                          prompt_ids=order, ordered=True), received)

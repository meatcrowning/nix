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

    def publish(self):
        snapshot = self._snapshot or {}
        pending = [r[1] for r in sorted(snapshot.get('queue_pending', []), key=lambda r: r[0])]
        running = {r[1] for r in snapshot.get('queue_running', [])}
        jobs = self.jobs()
        jobs.sort(key=lambda j: (-1 if j.prompt_id in running else
                                pending.index(j.prompt_id) if j.prompt_id in pending else len(pending)))
        rows = []
        waiting = [j for j in jobs if j.prompt_id in pending and j.prompt_id not in running]
        for job in jobs:
            p = job.meta.get('params', {})
            prompt = p.get('prompt_boxes', {}).get('positive', p.get('positive', ''))
            model = str(p.get('model') or getattr(job.meta.get('pairing', {}).get('model'), 'name', ''))
            state = ('Stopping' if job.cancelled else 'Running' if job.prompt_id in running
                     else 'Waiting' if job.prompt_id in pending else
                     'Submitting' if not job.prompt_id else 'Checking status')
            i = waiting.index(job) if job in waiting else -1
            rows.append(dict(id=job.request_id, label=job.request_id[:8], prompt=prompt,
                             promptLabel=self.prompt_label(p),
                             seed=str(p.get('seed', '?')), model=model,
                             details='Positive: ' + prompt + '\n\nNegative: ' + p.get('negative', '')
                             + '\n\nSeed: ' + str(p.get('seed', '?')) + '\nModel: ' + model
                             + '\nSize: %s × %s · Steps: %s' % (p.get('width', '?'), p.get('height', '?'), p.get('steps', '?')),
                             state=state, canStop=not job.cancelled,
                             canUp=not self._moving and i > 0 and waiting[i-1].owner_id == job.owner_id,
                             canDown=not self._moving and 0 <= i < len(waiting)-1 and waiting[i+1].owner_id == job.owner_id))
        for sub in self.controller._submissions.values():
            if sub.state not in ('preparing', 'reserving') or sub.cancelled:
                continue
            p = sub.params
            prompt = p.get('positive', '')
            rows.append(dict(id=sub.id, label=sub.id[:8], prompt=prompt,
                             promptLabel=self.prompt_label(p),
                             seed='assigning' if p.get('randomSeed') else str(p.get('seed', '?')),
                             model=getattr(sub.entry, 'name', ''), details=prompt,
                             state=('Preparing %d jobs' % sub.count if sub.count > 1 else 'Preparing'),
                             canStop=True, canUp=False, canDown=False))
        if rows != self._rows:
            self._rows = rows
            self.changed.emit()

    @Slot(str)
    def stop(self, request_id):
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
        self._moving = True
        self._revision += 1
        self.publish()

        def received(reply):
            try:
                doc = self.client._read_json(reply)
                if not doc.get('reordered'):
                    raise ValueError(doc.get('error', 'Queue changed; try again.'))
                # Reflect the acknowledged move before allowing another click;
                # a second Up must use the new neighbor, not undo this swap.
                pending = [list(r) for r in (self._snapshot or {}).get('queue_pending', [])]
                selected = [r for r in pending if r[1] in (job.prompt_id, peer.prompt_id)]
                if len(selected) == 2:
                    selected[0][0], selected[1][0] = selected[1][0], selected[0][0]
                    self._snapshot = dict(self._snapshot, queue_pending=pending)
            except (ValueError, TypeError) as exc:
                self.controller.toast.emit('Could not reorder jobs: %s' % exc, True)
            finally:
                reply.deleteLater()
                self._moving = False
            self.refresh()

        # This endpoint only swaps two waiting, owned jobs under the queue lock.
        # An older backend returns 404 without changing or resubmitting anything.
        self.client._post('/painter/reorder', dict(client_id=job.owner_id,
                          prompt_ids=[job.prompt_id, peer.prompt_id]), received)

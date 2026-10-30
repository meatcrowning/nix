"""Crash recovery for accepted Painter jobs; live windows retain exclusive ownership."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import tempfile


class JobJournal:
    def __init__(self, root, client_id, backend):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / (client_id + '.json')
        self.backend = backend
        self.rows = {}
        self.lock = self._lock(self.path)

    @staticmethod
    def _lock(path):
        fd = os.open(str(path.with_suffix('.lock')), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def write(self):
        fd, name = tempfile.mkstemp(prefix='.jobs-', dir=self.root)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'version': 1, 'backend': self.backend, 'jobs': self.rows}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def put(self, key, row):
        self.rows[key] = row
        self.write()

    def remove(self, key):
        self.rows.pop(key, None)
        self.write()

    def recover(self):
        recovered = []
        for path in self.root.glob('*.json'):
            if path == self.path:
                continue
            try:
                fd = self._lock(path)
            except (OSError, BlockingIOError):
                continue
            try:
                doc = json.loads(path.read_text())
                if doc.get('version') != 1 or doc.get('backend') != self.backend:
                    continue
                rows = doc.get('jobs', {})
                if not isinstance(rows, dict):
                    continue
                for key, row in rows.items():
                    if (key not in self.rows and isinstance(row, dict)
                            and row.get("request_id") == key
                            and isinstance(row.get("prompt", {}), dict)
                            and isinstance(row.get("meta", {}), dict)):
                        self.rows[key] = row
                        recovered.append(row)
                # Publish our copy before removing the old one. A crash between
                # these steps can duplicate records, never lose a completed job.
                self.write()
                path.unlink()
            except (OSError, ValueError, TypeError):
                continue
            finally:
                os.close(fd)
        return recovered

    def close(self):
        if self.lock is not None:
            if not self.rows:
                self.path.unlink(missing_ok=True)
            os.close(self.lock)
            self.lock = None
            if not self.rows:
                self.path.with_suffix(".lock").unlink(missing_ok=True)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass  # Process exit also releases the OS lock.

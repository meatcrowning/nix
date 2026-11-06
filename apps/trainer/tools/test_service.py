#!/usr/bin/env python3
"""Synthetic subprocesses and temporary files only; no GPU or user runs."""
from dataclasses import asdict
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service
from core import Settings

FAKE = '''import json,sys
print('TRAINER:'+json.dumps(dict(event='status',state='training')),flush=True)
for line in sys.stdin:
 d=json.loads(line)
 print('TRAINER:'+json.dumps(dict(event='status',state=d['command'])),flush=True)
 if d['command']=='stop': break
'''

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = self.root / 'engine'
        self.engine.mkdir()
        (self.engine / 'revision').touch()
        self.source = self.root / 'dataset'
        self.source.mkdir()
        (self.source / 'a.png').write_bytes(b'synthetic')
        self.model = self.root / 'model'
        self.model.touch()
        self.settings = asdict(Settings(dataset=str(self.source), output=str(self.root / 'out'),
                                       dit=str(self.model), text_encoder=str(self.model), vae=str(self.model)))
        self.launches = []
        def launch(args, **kw):
            self.launches.append(args)
            return subprocess.Popen([sys.executable, '-u', '-c', FAKE], **kw)
        self.c = service.Controller(self.root / 'state', self.engine, launch)
        self.patch = patch.object(service, 'legacy_worker', return_value=False)
        self.patch.start()

    def tearDown(self):
        if self.c.proc and self.c.proc.poll() is None:
            self.c.proc.stdin.write('{"command":"stop"}\n')
            self.c.proc.stdin.flush()
            self.c.proc.wait(timeout=5)
        deadline = time.monotonic() + 5
        while self.c.collecting and time.monotonic() < deadline:
            time.sleep(.01)
        self.patch.stop()
        self.tmp.cleanup()

    def start(self):
        doc = dict(action='start', settings=self.settings, id=uuid.uuid4().hex)
        return doc, self.c.request(doc)

    def test_disconnect_and_duplicate_start(self):
        doc, result = self.start()
        self.assertEqual(result, self.c.request(doc))
        self.assertEqual(len(self.launches), 1)
        # No connected GUI is required; control pipe remains owned by controller.
        time.sleep(.05)
        self.assertTrue(self.c.request(dict(action='status'))['active'])
        with self.assertRaises(ValueError):
            self.c.request(dict(doc, id=uuid.uuid4().hex))
        with self.assertRaises(ValueError):
            self.c.request(dict(action='control', generation='old', message={'command':'stop'}))
        self.c.request(dict(action='control', generation=result['generation'], message={'command':'stop'}))
        self.c.proc.wait(timeout=5)

    def test_inspect_existing_run_does_not_write(self):
        run = service.prepare_run(Settings(**self.settings))
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in run.rglob('*') if p.is_file()}
        result = self.c.request(dict(action='inspect', run=str(run)))
        self.assertIsNone(result['latest'])
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in run.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(self.launches)

    def test_upload_sealed_and_sample_traversal(self):
        token = uuid.uuid4().hex
        path = Path(self.c.request(dict(action='upload', token=token)))
        (path / 'a.png').write_bytes(b'synthetic')
        self.settings['dataset'] = str(path)
        self.start()
        with self.assertRaises(ValueError):
            self.c.request(dict(action='upload', token=token))
        with self.assertRaises(ValueError):
            self.c.request(dict(action='sample', run=str(self.c.run), name='../run.json'))

    def test_private_socket_and_rpc_disconnect(self):
        runtime = self.root / 'runtime'
        runtime.mkdir()
        script = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import service; "
                  "service.SOCKET = Path(sys.argv[2]); original = service.Controller; "
                  "service.Controller = lambda: original(state=Path(sys.argv[3]), engine=Path(sys.argv[4])); "
                  "service.serve()")
        proc = subprocess.Popen([sys.executable, '-c', script, str(service.HERE),
                                 str(runtime / 'moss-trainer.sock'), str(self.root / 'state'), str(self.engine)])
        try:
            path = runtime / 'moss-trainer.sock'
            for _ in range(100):
                if path.exists():
                    break
                time.sleep(.01)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            for _ in range(2):
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.connect(str(path))
                    sock.sendall(b'{"action":"status"}\n')
                    response = json.loads(sock.makefile('rb').readline())
                    self.assertTrue(response['ok'])
                    self.assertFalse(response['value']['active'])
            reply = subprocess.run([sys.executable, str(service.HERE / 'service.py')],
                                   input='{"action":"status"}\n', text=True, capture_output=True,
                                   env=dict(os.environ, XDG_RUNTIME_DIR=str(runtime)), timeout=5)
            self.assertEqual(reply.returncode, 0, reply.stderr)
            self.assertTrue(json.loads(reply.stdout)['ok'])
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_legacy_worker_refuses_before_any_run_write(self):
        with patch.object(service, 'legacy_worker', return_value=True):
            with self.assertRaises(ValueError):
                self.start()
        self.assertFalse((self.root / 'out').exists())
        self.assertFalse(self.launches)

if __name__ == '__main__':
    unittest.main()

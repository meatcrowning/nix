# -*- coding: utf-8 -*-
"""Python 2.7 / GTK 3.6 client for the private app engine socket."""
from __future__ import unicode_literals
import json
import socket
import threading
try:
    import Queue as queue
except ImportError:
    import queue
from gi.repository import GLib


class Connection:
    def __init__(self, path, deliver):
        self.path, self.deliver = path, deliver
        self.requests = queue.Queue()
        self.pending_poll = False
        self.closed = False
        self.finished = False
        worker = threading.Thread(target=self.work)
        worker.daemon = True
        worker.start()

    def send(self, request):
        if self.closed or (request['op'] in ('poll', 'frame') and self.pending_poll):
            return
        if request['op'] in ('poll', 'frame'):
            self.pending_poll = True
        self.requests.put(request)

    def work(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        try:
            sock.connect(self.path)
            stream = sock.makefile('rb')
            while not self.closed:
                request = self.requests.get()
                if request is None:
                    break
                sock.sendall((json.dumps(request) + '\n').encode('utf-8'))
                line = stream.readline(8 * 1024 * 1024)
                if not line or not line.endswith(b'\n'):
                    raise IOError('Application engine disconnected')
                reply = json.loads(line.decode('utf-8'))
                GLib.idle_add(self.deliver, request['op'], reply)
                if request['op'] in ('poll', 'frame'):
                    self.pending_poll = False
        except Exception as exc:
            if not self.closed:
                GLib.idle_add(self.deliver, 'disconnected', dict(ok=False, error=str(exc)))
        finally:
            sock.close()
            self.finished = True

    def close(self):
        self.closed = True
        self.requests.put(None)

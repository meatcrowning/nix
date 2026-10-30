#!/usr/bin/env python3
"""Qt-free-of-desktop warden wire tests; all requests/replies are stubs.

Run with painter-qtenv on top or Fedora Python on book. No backend, filesystem
state, systemd, notifications, or sockets are accessed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps' / 'pylib'))
from PySide6.QtCore import QByteArray, QCoreApplication
from PySide6.QtNetwork import QNetworkReply
from warden import Warden

app = QCoreApplication([])
client = Warden()
requests = []
client._post = lambda path, body, cb=None: requests.append((path, body, cb))
client.reserve('comfy', nbytes=123, token='job-a')
client.renew('comfy', lease=90, token='job-a')
client.done('comfy', token='job-a')
assert [path for path, _, _ in requests] == ['/reserve-owned', '/renew-owned', '/done-owned']
assert all(body['token'] == 'job-a' for _, body, _ in requests)
assert requests[0][1]['bytes'] == 123 and requests[1][1]['lease'] == 90
requests.clear()
client.reserve('ollama')
client.renew('ollama')
client.done('ollama')
assert [path for path, _, _ in requests] == ['/reserve', '/renew', '/done']
assert all('token' not in body for _, body, _ in requests)


class Reply:
    def __init__(self, data, error=False):
        self.data, self.failed, self.deleted = data, error, False

    def error(self):
        return (QNetworkReply.NetworkError.ConnectionRefusedError if self.failed
                else QNetworkReply.NetworkError.NoError)

    def errorString(self):
        return 'synthetic refusal'

    def readAll(self):
        return QByteArray(self.data)

    def deleteLater(self):
        self.deleted = True


for data, failed in ((b'', True), (b'{', False), (b'[]', False), (b'{}', False)):
    reply, results, box = Reply(data, failed), [], {'stale': 1}
    Warden._done(reply, lambda ok, reason: results.append((ok, reason)), box)
    assert results[0][0] is True and 'protection unavailable' in results[0][1]
    assert box['bypassed'] is True and 'stale' not in box and reply.deleted

reply, results, box = Reply(b'{"ok":false,"reason":"busy"}'), [], {}
Warden._done(reply, lambda ok, reason: results.append((ok, reason)), box)
assert results == [(False, 'busy')] and not box.get('bypassed') and reply.deleted
print('warden client: token routes, legacy compatibility, explicit fail-open, refusal passed')

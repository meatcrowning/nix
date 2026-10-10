"""Private JSON request socket shared by historical GTK app frontends."""
import json
from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer


class Server(QObject):
    def __init__(self, path, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self.accept)
        if not self.server.listen(str(path)):
            raise RuntimeError(self.server.errorString())
        self.clients = {}

    def accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self.clients[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self.read(s))
            sock.disconnected.connect(lambda s=sock: self.drop(s))

    def drop(self, sock):
        self.clients.pop(sock, None)
        sock.deleteLater()

    def read(self, sock):
        buf = self.clients[sock]
        buf.extend(bytes(sock.readAll()))
        if len(buf) > 2 * 1024 * 1024:
            sock.abort()
            return
        while b'\n' in buf:
            line, _, rest = buf.partition(b'\n')
            buf[:] = rest
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('Invalid request')
                response = dict(ok=True, state=self.engine.dispatch(request))
                payload = json.dumps(response, allow_nan=False).encode() + b'\n'
            except (ValueError, KeyError, TypeError, OSError) as exc:
                response = dict(ok=False, error=str(exc))
                payload = json.dumps(response).encode() + b'\n'
            sock.write(payload)

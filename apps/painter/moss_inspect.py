"""Asynchronous prompt inspection and selected-output heatmap presentation."""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QCoreApplication
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtCore import Qt
from PySide6.QtNetwork import QNetworkReply
import moss_data


class MossInspect(QObject):
    tokenized = Signal(str, str, 'QVariantMap')
    changed = Signal()
    _loaded = Signal(int, object)
    _rendered = Signal(int, str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._closed = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='moss-inspect')
        self._generation = 0
        self._render_serial = 0
        self._data = None
        self._path = self._overlay = self._error = ''
        self._tokens = []
        self._future = None
        self._cache = tempfile.TemporaryDirectory(prefix='painter-heatmaps-')
        self._loaded.connect(self._accept)
        self._rendered.connect(self._accept_render)
        QCoreApplication.instance().aboutToQuit.connect(self.close)

    def close(self):
        self._closed = True
        self._pool.shutdown(wait=True, cancel_futures=True)
        self._cache.cleanup()

    @Slot(str, str)
    def tokenize(self, identity, text):
        if "PainterMossSampler" not in (self.client.object_info or {}):
            self.tokenized.emit(identity, text, {"error": "Token counts require a connected MOSS inspection backend"})
            return
        def done(reply):
            try:
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    result = {'error': 'Token counts require a connected MOSS inspection backend'}
                else:
                    result = json.loads(bytes(reply.readAll()))
                self.tokenized.emit(identity, text, result)
            except (ValueError, TypeError):
                self.tokenized.emit(identity, text, {'error': 'Invalid tokenizer reply'})
            finally:
                reply.deleteLater()
        reply = self.client._post('/painter/moss/tokenize', {'text': text}, done)
        reply.setProperty('moss_request', identity)
        # Bounded requests; stale replies are rejected by each editor.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(5000, reply, reply.abort)

    @Property(bool, notify=changed)
    def available(self):
        return self._data is not None and bool(self._tokens)

    @Property('QVariantList', notify=changed)
    def tokens(self):
        return self._tokens

    @Property(str, notify=changed)
    def overlay(self):
        return QUrl.fromLocalFile(self._overlay).toString() if self._overlay else ''

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Slot(str)
    def load(self, path):
        if self._closed:
            return
        path = QUrl(path).toLocalFile() if path.startswith('file:') else path
        self._generation += 1
        serial = self._generation
        self._render_serial += 1
        if self._overlay:
            Path(self._overlay).unlink(missing_ok=True)
        self._path, self._data, self._tokens, self._overlay, self._error = path, None, [], '', ''
        self.changed.emit()
        if self._future:
            self._future.cancel()
        if not path or not path.lower().endswith('.png'):
            return
        def read():
            try:
                value = moss_data.read(path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                value = str(exc)
            self._loaded.emit(serial, value)
        self._future = self._pool.submit(read)

    def _accept(self, serial, value):
        if serial != self._generation:
            return
        if isinstance(value, str):
            self._error = value
        elif value:
            self._data = value
            self._tokens = [dict(t, label='%d · %s' % (t['index'] + 1, t['text'].replace('\n', '↵')))
                            for t in value[0]['tokens'] if t['visible']]
        self.changed.emit()

    @Slot(int)
    def select(self, index):
        if self._closed:
            return
        if not self._data or not (0 <= index < len(self._tokens)):
            return
        self._render_serial += 1
        serial = self._render_serial
        doc, pixels = self._data
        token = self._tokens[index]['index']
        path = self._path
        destination = str(Path(self._cache.name) / ('map-%d.png' % serial))
        if self._future:
            self._future.cancel()
        def render():
            image = QImage(path)
            if image.isNull():
                return
            w, h = doc['width'], doc['height']
            mask = QImage(w, h, QImage.Format.Format_ARGB32)
            for y in range(h):
                for x in range(w):
                    value = pixels[token * w * h + y * w + x] / 255
                    strength = max(0, min(1, (value - .35) / .3))
                    alpha = round(204 * strength * strength * (3 - 2 * strength))
                    mask.setPixelColor(x, y, QColor(255, 220, 0, alpha))
            overlay = mask.scaled(image.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter = QPainter(image)
            painter.drawImage(0, 0, overlay)
            painter.end()
            if image.save(destination):
                self._rendered.emit(serial, destination)
        self._future = self._pool.submit(render)

    def _accept_render(self, serial, path):
        if serial != self._render_serial:
            Path(path).unlink(missing_ok=True)
            return
        previous = self._overlay
        self._overlay = path
        self.changed.emit()
        if previous and previous != path:
            Path(previous).unlink(missing_ok=True)

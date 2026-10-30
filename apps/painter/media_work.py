"""Coalesced derivative preparation: two workers and two newest pending tasks."""
from collections import OrderedDict
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage


class _Signals(QObject):
    finished = Signal(str)


class _Work(QRunnable):
    def __init__(self, key, fn):
        super().__init__()
        self.key, self.fn = key, fn
        self.signals = _Signals()

    def run(self):
        try:
            self.fn()
        finally:
            self.signals.finished.emit(self.key)


class Derivatives(QObject):
    ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.active = {}
        self.pending = OrderedDict()

    def prepare(self, key, fn):
        if key in self.active:
            return
        self.pending.pop(key, None)
        self.pending[key] = fn
        while len(self.pending) > 2:
            self.pending.popitem(last=False)
        self._next()

    def _next(self):
        while len(self.active) < 2 and self.pending:
            key, fn = self.pending.popitem(last=True)
            work = _Work(key, fn)
            self.active[key] = work
            work.signals.finished.connect(self._done)
            self.pool.start(work)

    def _done(self, key):
        self.active.pop(key, None)
        self._next()
        self.ready.emit()


class _PreviewSignals(QObject):
    finished = Signal(object, object)


class _Preview(QRunnable):
    def __init__(self, data, fmt, meta):
        super().__init__()
        self.data, self.fmt, self.meta = data, fmt, meta
        self.signals = _PreviewSignals()

    def run(self):
        image = QImage()
        image.loadFromData(self.data, self.fmt.upper())
        self.signals.finished.emit(image, self.meta)


class PreviewDecoder(QObject):
    ready = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.active = None
        self.latest = None

    def submit(self, data, fmt, meta):
        # One active decode plus the newest frame; obsolete frames never form
        # a backlog while sampling is faster than rendering or the UI is busy.
        self.latest = (data, fmt, meta)
        self._next()

    def _next(self):
        if self.active is not None or self.latest is None:
            return
        work = _Preview(*self.latest)
        self.latest = None
        self.active = work
        work.signals.finished.connect(self._done)
        self.pool.start(work)

    def _done(self, image, meta):
        self.active = None
        if self.latest is None and not image.isNull():
            self.ready.emit(image, meta)
        self._next()

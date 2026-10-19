"""Asynchronous tag worker shared by the Qt face and Unity's engine."""
import json
from pathlib import Path
import sys
from PySide6.QtCore import QObject, QProcess, QCoreApplication


class Tagger(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.result = dict(busy=False, tags=[], error='')
        self.callback = None
        QCoreApplication.instance().aboutToQuit.connect(self.cancel)

    def start(self, request, callback=None):
        if self.process is not None:
            result = dict(busy=True, error='Tag generation is already running.')
            if callback:
                callback(result)
            return result
        self.callback = callback
        self.result = dict(busy=True, tags=[], error='')
        proc = self.process = QProcess(self)
        proc.finished.connect(self.finished)
        proc.errorOccurred.connect(lambda error: self.finished() if error == QProcess.FailedToStart else None)
        proc.start(sys.executable, [str(Path(__file__).with_name('tagger_worker.py'))])
        proc.write(json.dumps(request).encode() + b'\n')
        proc.closeWriteChannel()
        return self.result

    def finished(self, *_):
        proc = self.process
        if proc is None:
            return
        try:
            result = json.loads(bytes(proc.readAllStandardOutput()))
        except (ValueError, UnicodeError):
            result = dict(tags=[], error='Local tag worker stopped unexpectedly.')
        self.result = dict(result, busy=False)
        self.process, callback, self.callback = None, self.callback, None
        proc.deleteLater()
        if callback:
            callback(self.result)

    def cancel(self):
        if self.process is not None:
            self.callback = None
            self.process.terminate()
            # Only shutdown waits; normal operation never blocks the GUI thread.
            if not self.process.waitForFinished(1500):
                self.process.kill()
                self.process.waitForFinished(1000)

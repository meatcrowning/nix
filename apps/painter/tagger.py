"""Asynchronous tag worker shared by the Qt face and Unity's engine."""
import json
import os
import socket
from pathlib import Path
import sys
from PySide6.QtCore import QObject, QProcess, QCoreApplication, QTimer


def worker_command():
    """Only top runs inference; Book reuses the launcher's authenticated route."""
    if socket.gethostname().split('.')[0] == 'top':
        return [sys.executable, str(Path(__file__).with_name('tagger_worker.py'))]
    command = [os.environ.get('PAINTER_BACKEND_SSH_BIN', '/usr/bin/ssh'),
               '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
               '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']
    control = os.environ.get('PAINTER_BACKEND_SSH_CTL', '')
    if control:
        command += ['-o', 'ControlMaster=auto', '-o', 'ControlPersist=30',
                    '-o', 'ControlPath=' + control]
    return command + [os.environ.get('PAINTER_BACKEND_SSH') or 'top',
                      'exec /etc/profiles/per-user/lam/bin/painter --prompt-worker']


class Tagger(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.result = dict(busy=False, tags=[], error='')
        self.callback = None
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)
        QCoreApplication.instance().aboutToQuit.connect(self.cancel)

    def start(self, request, callback=None):
        if self.process is not None:
            result = dict(busy=True, error='The writer on top is already running.')
            if callback:
                callback(result)
            return result
        self.callback = callback
        self.result = dict(busy=True, tags=[], error='')
        proc = self.process = QProcess(self)
        proc.finished.connect(self.finished)
        proc.errorOccurred.connect(lambda error: self.finished() if error == QProcess.FailedToStart else None)
        command = worker_command()
        proc.start(command[0], command[1:])
        self.deadline.start(110000)
        proc.write(json.dumps(request).encode() + b'\n')
        proc.closeWriteChannel()
        return self.result

    def timed_out(self):
        callback, self.callback = self.callback, None
        self.cancel()
        self.result = dict(busy=False, tags=[], error='Prompt writing on top timed out.')
        if callback:
            callback(self.result)

    def finished(self, *_):
        proc = self.process
        if proc is None:
            return
        self.deadline.stop()
        try:
            result = json.loads(bytes(proc.readAllStandardOutput()))
        except (ValueError, UnicodeError):
            result = dict(tags=[], error='Could not complete prompt writing on top. Check that top is reachable and Painter is up to date there.')
        self.result = dict(result, busy=False)
        self.process, callback, self.callback = None, self.callback, None
        proc.deleteLater()
        if callback:
            callback(self.result)

    def cancel(self):
        self.deadline.stop()
        if self.process is not None:
            self.callback = None
            self.process.terminate()
            # Shutdown/deadline cleanup waits briefly; inference never blocks the GUI thread.
            if not self.process.waitForFinished(1500):
                self.process.kill()
                self.process.waitForFinished(1000)

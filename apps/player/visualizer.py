"""On-demand G-Force bridge. No subprocess, audio tap, or frame timer when hidden."""
import json
import os
from pathlib import Path
import signal
import struct
import sys

from PySide6.QtCore import QEvent, QObject, Property, QProcess, QProcessEnvironment, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickPaintedItem

APPS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APPS))
from gforce.settings import DEFAULTS, DIALS, TOGGLES


class Visualizer(QObject):
    changed = Signal()
    choicesChanged = Signal()
    presetsChanged = Signal()
    frame = Signal(QImage)

    def __init__(self, stream_name, parent=None):
        super().__init__(parent)
        self.stream_name = stream_name
        self.worker_command = ["gforce-qtenv","python3",str(APPS/"gforce/embedded_worker.py"),stream_name]
        self.process = None
        self.window = None
        self.requested = False
        self.closed = False
        self.state = {'values':dict(DEFAULTS), 'choices':{}, 'selections':{},
                      'presets':[], 'status':'', 'ready':False, 'paused':False, 'comparing':False}
        self._choices = {}
        self._presets = []
        self.size = (640,360)
        self.buffer = bytearray()
        self.diagnostic = ''

    @Property('QVariantMap', notify=changed)
    def stateInfo(self): return self.state

    @Property('QVariantMap', notify=choicesChanged)
    def choices(self): return self._choices

    @Property('QStringList', notify=presetsChanged)
    def presetNames(self): return self._presets

    @Property('QVariantList', constant=True)
    def dials(self):
        return [dict(name=n,label=label,minimum=lo,maximum=hi,step=step,logarithmic=log)
                for n,label,lo,hi,step,log in DIALS]

    @Property('QVariantList', constant=True)
    def toggles(self): return [dict(name=n,label=label) for n,label in TOGGLES]

    def bind_window(self, window):
        self.window = window
        window.installEventFilter(self)
        self.reconcile()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.WindowStateChange,
                            QEvent.Type.Expose):
            QTimer.singleShot(0,self.reconcile)
        return False

    def shown(self):
        if self.window is None: return False
        state = self.window.windowState()
        # QWidget returns flags, QWindow returns an enum.
        return self.window.isVisible() and not bool(state & Qt.WindowState.WindowMinimized)

    @Slot(bool)
    def setShown(self, shown):
        self.requested = shown
        self.reconcile()

    def reconcile(self):
        want = self.requested and not self.closed and self.shown()
        if not want:
            self.stop()
        elif self.process is None:
            self.start()

    def start(self):
        p = QProcess(self)
        p.setUnixProcessParameters(QProcess.UnixProcessFlag.CreateNewSession)
        env = QProcessEnvironment.systemEnvironment()
        # The worker uses surfaceless EGL exclusively, even on a live desktop.
        for name in ('DISPLAY','WAYLAND_DISPLAY','QT_QPA_PLATFORMTHEME'):
            env.remove(name)
        env.insert('QT_QPA_PLATFORM','offscreen')
        p.setProcessEnvironment(env)
        self.process = p
        self.buffer.clear()
        self.diagnostic = ''
        self.state = {**self.state,'ready':False,'status':'starting visualizer…'}
        self.changed.emit()
        p.readyReadStandardOutput.connect(lambda:self.read_output(p))
        p.readyReadStandardError.connect(lambda:self.read_error(p))
        def started():
            p.worker_pid = int(p.processId())
            if getattr(p, "stopping", False):
                try: os.killpg(p.worker_pid, signal.SIGTERM)
                except ProcessLookupError: pass
            else:
                self.send_size()
        p.started.connect(started)
        p.finished.connect(lambda code,status:self.finished(p,code))
        p.errorOccurred.connect(lambda error:self.failed(p,error))
        p.start(self.worker_command[0],self.worker_command[1:])

    def failed(self, process, error):
        if process is not self.process: return
        if error == QProcess.ProcessError.FailedToStart:
            self.finished(process,1)

    def finished(self, process, code):
        if process is not self.process: return
        stopping = getattr(process,'stopping',False) and not getattr(process,'protocol_failed',False)
        # A native renderer crash must not orphan its audio recorder.
        pid = getattr(process,'worker_pid',0)
        if pid:
            try: os.killpg(pid,signal.SIGKILL)
            except ProcessLookupError: pass
        self.process = None
        self.buffer.clear()
        self.state = {**self.state,'ready':False,
                      'status':'' if stopping else 'visualizer stopped: '+(self.diagnostic.strip()[-400:] or process.errorString())}
        self.changed.emit()
        process.deleteLater()
        if stopping: self.reconcile()

    def stop(self):
        p = self.process
        if p is None or getattr(p,'stopping',False): return
        p.stopping = True
        self.state = {**self.state,'ready':False}
        self.changed.emit()
        pid = int(p.processId())
        if pid:
            try: os.killpg(pid,signal.SIGTERM)
            except ProcessLookupError: pass
        else:
            p.kill()
        def force_stop():
            if self.process is p and p.state()!=QProcess.ProcessState.NotRunning:
                try: os.killpg(int(p.processId()),signal.SIGKILL)
                except ProcessLookupError: pass
        QTimer.singleShot(2500,self,force_stop)

    @Slot()
    def toggleFullscreen(self):
        if self.window is None: return
        if self.window.windowState() & Qt.WindowState.WindowFullScreen:
            if getattr(self,'was_maximized',False): self.window.showMaximized()
            else: self.window.showNormal()
        else:
            self.was_maximized = bool(self.window.windowState() & Qt.WindowState.WindowMaximized)
            self.window.showFullScreen()

    @Slot()
    def retry(self):
        if self.process is None: self.reconcile()
        else: self.stop()

    @Slot()
    def shutdown(self):
        self.closed = True
        self.stop()
        if self.process:
            p = self.process
            if not p.waitForFinished(3000):
                try: os.killpg(int(p.processId()),signal.SIGKILL)
                except ProcessLookupError: pass
                p.waitForFinished(1000)

    def read_error(self,p):
        self.diagnostic = (self.diagnostic+bytes(p.readAllStandardError()).decode(errors='replace'))[-4096:]

    def read_output(self,p):
        if p is not self.process: return
        self.buffer.extend(bytes(p.readAllStandardOutput()))
        while len(self.buffer)>=5:
            kind = self.buffer[0]
            size = struct.unpack_from('!I',self.buffer,1)[0]
            if kind not in (ord('J'),ord('F')) or size > 1920*1080*4+8:
                self.diagnostic = 'invalid renderer response'
                p.protocol_failed = True
                self.stop()
                return
            if len(self.buffer)<5+size: return
            data = bytes(self.buffer[5:5+size])
            del self.buffer[:5+size]
            if getattr(p,'stopping',False): continue
            if kind==ord('J'):
                try:
                    state = json.loads(data)
                    if not isinstance(state,dict): raise ValueError('invalid state')
                except (ValueError,UnicodeDecodeError):
                    self.diagnostic = 'invalid renderer state'
                    p.protocol_failed = True
                    self.stop()
                    return
                if state.get("choices",{}) != self._choices:
                    self._choices = state.get("choices",{})
                    self.choicesChanged.emit()
                if state.get("presets",[]) != self._presets:
                    self._presets = state.get("presets",[])
                    self.presetsChanged.emit()
                self.state = state
                self.changed.emit()
            elif kind==ord('F') and size>=8:
                w,h = struct.unpack_from('!II',data)
                if w*h*4!=size-8 or not w or not h: continue
                frame = QImage(data[8:],w,h,w*4,QImage.Format.Format_RGBA8888).copy()
                self.frame.emit(frame)
                self.command({'op':'ack'})

    @Slot('QVariantMap')
    def command(self, message):
        p = self.process
        if p and p.state()==QProcess.ProcessState.Running and not getattr(p,'stopping',False):
            p.write(json.dumps(message).encode()+b'\n')

    @Slot(int,int)
    def setSize(self,width,height):
        self.size = (max(1,width),max(1,height))
        self.send_size()

    def send_size(self):
        self.command({'op':'size','width':self.size[0],'height':self.size[1]})

    @Slot(str)
    def key(self,key):
        self.command({'op':'savePreset'} if key=='s' else {'op':'key','key':key})


class VisualizerSurface(QQuickPaintedItem):
    sourceChanged = Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self._source = None
        self._image = QImage()
        self.setFillColor(QColor('black'))
        self.setOpaquePainting(True)

    @Property(QObject,notify=sourceChanged)
    def source(self): return self._source

    @source.setter
    def source(self,value):
        if self._source is value: return
        if self._source: self._source.frame.disconnect(self.receive)
        self._source = value
        if value: value.frame.connect(self.receive)
        self.sourceChanged.emit()

    @Slot(QImage)
    def receive(self,image):
        self._image = image
        self.update()

    def paint(self,painter):
        if not self._image.isNull():
            painter.translate(0,self.height())
            painter.scale(1,-1)
            painter.drawImage(self.boundingRect(),self._image)


def register():
    qmlRegisterType(VisualizerSurface,'Player.Visualizer',1,0,'VisualizerSurface')

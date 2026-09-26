"""On-demand G-Force bridge. No subprocess, audio tap, or frame timer when hidden."""
import json
import mmap
import os
from pathlib import Path
import signal
import struct
import sys

from PySide6.QtCore import QEvent, QObject, Property, QProcess, QProcessEnvironment, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickItem, QQuickWindow, QSGImageNode, QSGTexture

import perftrace

APPS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APPS))
from gforce.settings import DEFAULTS, DIALS, TOGGLES


class Visualizer(QObject):
    changed = Signal()
    statisticsChanged = Signal()
    choicesChanged = Signal()
    presetsChanged = Signal()
    frame = Signal(QImage)

    def __init__(self, stream_name, parent=None):
        super().__init__(parent)
        self.stream_name = stream_name
        self.worker_command = ["gforce-qtenv","python3",str(APPS/"gforce/embedded_worker.py"),stream_name]
        self.process = None
        self.generation = 0
        self.window = None
        self.requested = False
        self.closed = False
        self.state = {'values':dict(DEFAULTS), 'choices':{}, 'selections':{},
                      'presets':[], 'status':'', 'ready':False, 'paused':False, 'comparing':False}
        self._statistics = {}
        self._choices = {}
        self._presets = []
        self.size = (640,360)
        self.buffer = bytearray()
        self.diagnostic = ''

    @Property('QVariantMap', notify=changed)
    def stateInfo(self): return self.state

    @Property('QVariantMap', notify=statisticsChanged)
    def statistics(self): return self._statistics

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
        # Linux memfd keeps pixels out of the pipe and off disk. The child
        # opens this private descriptor through procfs, without inherited fds.
        p.frame_fd = os.memfd_create('player-visualizer', os.MFD_CLOEXEC)
        os.ftruncate(p.frame_fd,1920*1080*4)
        p.frame_map = mmap.mmap(p.frame_fd,1920*1080*4)
        env.insert('GF_PLAYER_FRAME_FILE',f'/proc/{os.getpid()}/fd/{p.frame_fd}')
        p.setProcessEnvironment(env)
        self.generation += 1
        perftrace.reset_visualizer_frames()
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
        process.frame_map.close()
        os.close(process.frame_fd)
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
            if kind not in (ord('J'),ord('F'),ord('M')) or size > 1920*1080*4+8:
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
                statistics = {key:state.pop(key,0) for key in ('actualFps','renderWidth','renderHeight')}
                if statistics != self._statistics:
                    self._statistics = statistics
                    self.statisticsChanged.emit()
                if state != self.state:
                    self.state = state
                    self.changed.emit()
            elif kind in (ord('F'),ord('M')) and size>=8:
                w,h = struct.unpack_from('!II',data)
                shared = kind==ord('M')
                if not (0<w<=1920 and 0<h<=1080): continue
                if size != (8 if shared else 8+w*h*4): continue
                pixels = p.frame_map if shared else data[8:]
                frame = QImage(pixels,w,h,w*4,QImage.Format.Format_RGBA8888).copy()
                # The copy owns its pixels now. Release shared storage before
                # waiting for a repaint: the producer and display clocks must
                # not lock-step or a missed refresh also delays the next render.
                self.command({'op':'ack'})
                # QProcess.write only queues bytes. Flush the tiny ACK with
                # a zero timeout before Qt can enter another vblank wait;
                # otherwise the producer waits an extra display refresh.
                p.waitForBytesWritten(0)
                perftrace.visualizer_frame('received')
                self.frame.emit(frame)

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


class VisualizerSurface(QQuickItem):
    sourceChanged = Signal()
    consumed = Signal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._source = None
        self._image = QImage(1,1,QImage.Format.Format_RGB32)
        self._image.fill(QColor('black'))
        self._dirty = True
        self._generation = -1
        self.setFlag(QQuickItem.Flag.ItemHasContents)

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
        self._generation = self._source.generation if self._source else -1
        self._dirty = True
        self.update()

    def updatePaintNode(self,node,data):
        # Upload the original image once. QQuickPaintedItem first rescaled it
        # into another full-size CPU image and then uploaded the scaled result.
        # Qt calls this with the GUI thread blocked; all texture creation and
        # destruction stay on the scene-graph thread.
        if node is None:
            node = self.window().createImageNode()
            self._dirty = True
        if self._dirty:
            texture = self.window().createTextureFromImage(
                self._image, QQuickWindow.CreateTextureOption.TextureIsOpaque)
            node.setOwnsTexture(True)
            node.setTexture(texture)
            node.setFiltering(QSGTexture.Filtering.Nearest)
            node.setTextureCoordinatesTransform(QSGImageNode.TextureCoordinatesTransformFlag.MirrorVertically)
            self._dirty = False
            if self._generation >= 0:
                perftrace.visualizer_frame('uploaded')
                self.consumed.emit(self._generation)
                self._generation = -1
        node.setRect(self.boundingRect())
        return node


def register():
    qmlRegisterType(VisualizerSurface,'Player.Visualizer',1,0,'VisualizerSurface')

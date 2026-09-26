"""Native Wayland window with a dock of live dials; rendering and FFT stay in renderer.so."""
from audio_window import AudioWindow
from shared_dials import SharedDials
import ctypes as C
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from PySide6.QtCore import Qt, QTimer, QSocketNotifier, QFileSystemWatcher
from PySide6.QtGui import QAction, QSurfaceFormat, QKeySequence, QShortcut
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget, QGridLayout, QLabel, QMenu,
                               QMainWindow, QPushButton, QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

ROOT=Path(__file__).resolve().parent
STATE=Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'gforce-vis'
STATE.mkdir(parents=True,exist_ok=True)
DIALS=STATE/'dials.json'
PRESETS=STATE/'presets.json'
# Preset files carry the look; these are the dials that shape it.
from settings import LOOK_DIALS, DEFAULTS
FPS=30   # the original's frame rate; trail and flow dials are in its frames
assert os.environ.get('QT_QPA_PLATFORM') == 'wayland'
assert (Path(os.environ['XDG_RUNTIME_DIR'])/os.environ['WAYLAND_DISPLAY']).is_socket()
fmt=QSurfaceFormat()
fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGLES)
fmt.setVersion(3,0)
fmt.setSwapInterval(1)
fmt.setDepthBufferSize(0)
fmt.setStencilBufferSize(0)
QSurfaceFormat.setDefaultFormat(fmt)
app=QApplication(sys.argv)
assert app.platformName()=='wayland'
from native import load_renderer
lib=load_renderer(os.environ['GF_RENDERER_PATH'])

PARTICLE_RATE='.09/((NUM_PARTICLES+1)^1.66)'
INTERVAL=re.compile(r'^\s*([\d.]+)\s*\+\s*rnd\s*\(\s*([\d.]+)\s*\)\s*$',re.I)
RATE=re.compile(r'^\s*(?:([\d.]+)\s*\*\s*)?'+re.escape(PARTICLE_RATE)+r'\s*$',re.I)


class Dial:
    """One labelled slider. `to_ui`/`from_ui` map the value onto 0..steps."""
    def __init__(self,grid,row,label,lo,hi,default,fmt,apply,log=False,steps=400,live=True):
        self.lo,self.hi,self.log,self.steps=lo,hi,log,steps
        self.default,self.fmt,self.apply=default,fmt,apply
        self.name=QLabel(label)
        self.value=QLabel()
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.slider=QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0,steps)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid.addWidget(self.name,row,0)
        grid.addWidget(self.value,row,1)
        grid.addWidget(self.slider,row+1,0,1,2)
        self.slider.valueChanged.connect(self.moved)
        if not live:
            # Re-mapping the distortion field is a one-off cost: apply on release.
            self.slider.sliderReleased.connect(lambda: self.apply(self.get()))
        self.live=live

    def to_ui(self,v):
        v=min(max(v,self.lo),self.hi)
        f=math.log(v/self.lo)/math.log(self.hi/self.lo) if self.log else (v-self.lo)/(self.hi-self.lo)
        return round(f*self.steps)

    def get(self):
        f=self.slider.value()/self.steps
        return self.lo*(self.hi/self.lo)**f if self.log else self.lo+f*(self.hi-self.lo)

    def set(self,v,notify=False):
        self.slider.blockSignals(True)
        self.slider.setValue(self.to_ui(v))
        self.slider.blockSignals(False)
        self.value.setText(self.fmt(self.get()))
        if notify:
            self.apply(self.get())

    def moved(self,_):
        v=self.get()
        self.value.setText(self.fmt(v))
        if self.live or not self.slider.isSliderDown():
            self.apply(v)


class View(QOpenGLWidget):
    def __init__(self,window):
        super().__init__(window)
        self.window_=window
        self.ready=False
        self.closed=False
        self.audio=AudioWindow()
        self.hit_hold=0.
        self.pcm=(C.c_float*550)()
        self.peak=0.
        self.frames=0
        self.started=time.monotonic()
        self.last_report=self.started
        self.report_frames=0
        self.cpu_start=time.process_time()
        self.draw_ms=0.
        self.capture=None
        self.notifier=None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer=QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(round(1000/FPS))
        self.timer.timeout.connect(self.update)

    def require(self,ok):
        if not ok:
            print('Renderer failed:',lib.gf_error().decode(),flush=True)
            self.window_.close()
            app.exit(1)
        return bool(ok)

    def dimensions(self):
        dpr=self.devicePixelRatioF()
        return max(1,round(self.width()*dpr)),max(1,round(self.height()*dpr))

    def initializeGL(self):
        self.ready=self.require(lib.gf_init(*self.dimensions()))
        if not self.ready:
            return
        sink=os.environ.get('GF_SINK') or subprocess.check_output(['pactl','get-default-sink'],text=True).strip()
        self.capture=subprocess.Popen(['parec','--device='+sink+'.monitor',
            '--format=float32le','--rate=22050','--channels=1','--latency-msec=5','--process-time-msec=5',
            '--client-name=G-Force GPU demo','--stream-name=Desktop audio visualization'],stdout=subprocess.PIPE)
        print('Audio monitor:',sink+'.monitor',flush=True)
        os.set_blocking(self.capture.stdout.fileno(),False)
        self.notifier=QSocketNotifier(self.capture.stdout.fileno(),QSocketNotifier.Type.Read,self)
        self.notifier.activated.connect(self.read_audio)
        self.started=self.last_report=time.monotonic()
        self.cpu_start=time.process_time()
        self.timer.start()
        # Seed after initializeGL returns: the grid dial makes the context current itself.
        QTimer.singleShot(0,self.window_.renderer_ready)

    def set_dial(self,name,value):
        if not self.ready:
            return
        # Field remaps and render-size changes need the GL context.
        if name in ('grid','resolution'):
            self.makeCurrent()
        ok=lib.gf_set(name.encode(),value)
        if name in ('grid','resolution'):
            self.doneCurrent()
        if not ok:
            print('Dial failed:',lib.gf_error().decode(),flush=True)

    def resizeGL(self,w,h):
        if self.ready:
            self.require(lib.gf_resize(*self.dimensions()))

    def paintGL(self):
        if not self.ready or self.closed:
            return
        # Wayland can settle fractional scaling after the initial resizeGL.
        # Reconcile the physical size here as well; unchanged sizes are a no-op.
        if not self.require(lib.gf_resize(*self.dimensions())):
            return
        t=time.monotonic()
        self.pcm[:]=self.audio.sample(t,self.hit_hold)
        if not self.require(lib.gf_frame(self.pcm,round((t-self.started)*1000),self.defaultFramebufferObject())):
            return
        self.draw_ms+=(time.monotonic()-t)*1000
        self.frames+=1
        self.report_frames+=1
        now=time.monotonic()
        if now-self.last_report >= 1.:
            cpu=time.process_time()
            w,h=self.dimensions()
            actual=self.report_frames/(now-self.last_report)
            fw,fh=round(lib.gf_get(b'fieldWidth')),round(lib.gf_get(b'fieldHeight'))
            self.window_.field_resolution.setText(f'{fw} × {fh} map')
            rw,rh=round(lib.gf_get(b'renderWidth')),round(lib.gf_get(b'renderHeight'))
            self.window_.actual_fps.setText(f'{actual:.1f} fps actual · {rw} × {rh}')
            print(f'fps={actual:.1f} cpu={100*(cpu-self.cpu_start)/(now-self.last_report):.1f}% '
                  f'submit={self.draw_ms/self.report_frames:.2f}ms render={w}x{h} peak={self.peak:.4f}',flush=True)
            self.last_report=now
            self.cpu_start=cpu
            self.draw_ms=0.
            self.report_frames=0

    def read_audio(self):
        try:
            chunk=os.read(self.capture.stdout.fileno(),65536)
        except BlockingIOError:
            return
        if not chunk:
            print('Audio capture ended',flush=True)
            self.window_.close()
            return
        self.audio.feed(chunk,time.monotonic())
        self.peak=max(abs(x) for x in self.audio.latest)

    def keyPressEvent(self,event):
        if event.isAutoRepeat():
            return
        if event.key()==Qt.Key.Key_Escape:
            self.window_.close()
        elif event.key()==Qt.Key.Key_F11:
            w=self.window_
            w.showNormal() if w.isFullScreen() else w.showFullScreen()
        elif event.text() in ('s','S') and self.ready:
            self.window_.save_preset()
        elif event.text() and self.ready:
            self.send_key(event.text()[0])

    def send_key(self,ch):
        lib.gf_key(ord(ch))
        self.sync_state()

    def sync_state(self):
        state=(C.c_long*6)()
        lib.gf_control_state(state)
        self.window_.update_title(bool(state[0]))
        self.window_.sync_components()
        self.window_.changed()
        print(f'Controls: paused={bool(state[0])} shape={state[1]} flow={state[2]} colour={state[3]} particle={state[4]}',flush=True)
        self.update()

    def cleanup(self):
        if self.closed:
            return
        if self.window_.comparison is not None:
            self.window_.compare_defaults(False)
        self.closed=True
        self.timer.stop()
        if self.capture:
            self.notifier.setEnabled(False)
            if self.capture.poll() is None:
                self.capture.terminate()
                self.capture.wait(timeout=3)
        if self.ready:
            self.makeCurrent()
            lib.gf_close()   # the engine writes its settings to .G-Force here
            self.doneCurrent()
            self.ready=False


class Window(QMainWindow):
    # Every dial persists in dials.json, in the units the panel shows (trail
    # half-life in frames, fade in 1/255ths). It is written on each change and
    # re-read when edited by hand. Without it, engine dials start from .G-Force.
    DEFAULTS=DEFAULTS
    ENGINE=('sensitivity','steps','transitionLo','transitionHi')

    def __init__(self):
        super().__init__()
        self.resize(1260,700)
        self.shared=SharedDials(self.DEFAULTS,STATE)
        self.view=View(self)
        self.setCentralWidget(self.view)
        self.loading=True
        self.written=None
        self.dials={}
        self.intervals={}
        self.components={}
        self.summaries={}
        self.tween=None
        self.comparison=None
        self.paused=False
        self.build_panel()
        self.presets=[]
        self.build_menus()
        self.update_title(False)
        self.save_timer=QTimer(self,singleShot=True,interval=300)
        self.save_timer.timeout.connect(self.save)
        self.watcher=QFileSystemWatcher(self)
        # The directory catches atomic replaces (ours, most editors); the file
        # catches in-place writes. A replaced file drops out of the watch.
        self.watcher.addPath(str(DIALS.parent))
        self.watcher.directoryChanged.connect(self.reload)
        self.watcher.directoryChanged.connect(self.load_presets)
        self.watcher.fileChanged.connect(self.reload)
        QShortcut(QKeySequence(Qt.Key.Key_Tab),self,self.toggle_panel,context=Qt.ShortcutContext.ApplicationShortcut)
        app.aboutToQuit.connect(self.view.cleanup)
        self.view.setFocus()
        self.statusBar().messageChanged.connect(self.status_cleared)
        self.statusBar().hide()
        self.component_timer=QTimer(self,interval=250)
        self.component_timer.timeout.connect(self.sync_components)
        self.component_timer.start()

    # ---- persistence -------------------------------------------------------
    def read(self):
        path=DIALS
        try:
            data=json.loads(path.read_text())
            data=data if isinstance(data,dict) else {}
        except (OSError,ValueError):
            data={}
        return self.shared.read(data)

    def values(self):
        data={k:round(d.get(),4) for k,d in self.dials.items()}
        data['forceConnect']=self.force_connect.isChecked()
        data['forcePoints']=self.force_points.isChecked()
        data['particles']=self.particles.isChecked()
        data['normalize']=self.normalize.isChecked()
        data['audioOnly']=self.audio_only.isChecked()
        data['intervals']={k:[round(lo.get()),max(0,round(hi.get())-round(lo.get()))] for k,(lo,hi) in self.intervals.items()}
        data['panel']=self.dock.isVisible()
        return data

    def changed(self):
        if not self.loading and self.comparison is None:
            self.save_timer.start()

    def save(self):
        if self.comparison is not None:
            return
        values=self.values()
        text=json.dumps(values,indent=1)+'\n'
        try:
            tmp=DIALS.with_suffix('.tmp')
            tmp.write_text(text)
            os.replace(tmp,DIALS)
            self.written=text
            if str(DIALS) not in self.watcher.files():
                self.watcher.addPath(str(DIALS))
        except OSError as e:
            print('Could not save dials:',e,flush=True)
        try:
            if self.view.ready: self.shared.save(values)
        except OSError as e:
            print('Could not share dials:',e,flush=True)

    def reload(self,_=None):
        """dials.json changed on disk: apply a hand edit live (ignore our own writes)."""
        if self.comparison is not None:
            return
        if DIALS.exists() and str(DIALS) not in self.watcher.files():
            self.watcher.addPath(str(DIALS))
        try:
            text=DIALS.read_text()
        except OSError:
            return
        if text==self.written or not self.view.ready:
            return
        try:
            data=json.loads(text)
        except ValueError:
            return
        if isinstance(data,dict) and data:
            print('Dials reloaded from',DIALS,flush=True)
            self.apply(data)
            self.written=text
            try:
                self.shared.save(self.values())
            except OSError as e:
                print('Could not share dials:',e,flush=True)

    @staticmethod
    def migrate_scales(data):
        data=dict(data)
        if 'sceneScale' in data:
            value=data.pop('sceneScale')
            for key in ('waveScale','particleScale','distortionScale'):
                data.setdefault(key,value)
        return data

    def apply(self,data):
        """Push a full set of values into the panel and the renderer."""
        self.loading=True
        d=dict(self.DEFAULTS); d.update(self.migrate_scales(data))
        for name in self.dials:
            self.dials[name].set(float(d[name]),notify=True)
        self.force_connect.setChecked(bool(d['forceConnect'])); self.view.set_dial('forceConnect',int(bool(d['forceConnect'])))
        self.force_points.setChecked(bool(d['forcePoints'])); self.view.set_dial('forcePoints',int(bool(d['forcePoints'])))
        self.particles.setChecked(bool(d['particles'])); self.view.set_dial('particles',int(bool(d['particles'])))
        self.normalize.setChecked(bool(d['normalize'])); self.view.set_dial('normalize',int(bool(d['normalize'])))
        self.audio_only.setChecked(bool(d['audioOnly'])); self.view.set_dial('audioOnly',int(bool(d['audioOnly'])))
        for kind,(lo,hi) in self.intervals.items():
            a,b=(d.get('intervals') or {}).get(kind,self.DEFAULTS['intervals'][kind])
            lo.set(a); hi.set(a+b); self.set_interval(kind)
        if 'panel' in data:
            self.dock.setVisible(bool(data['panel']))
        self.loading=False

    # ---- panel ---------------------------------------------------------------
    def section(self,layout,title,collapsed=False):
        box=QWidget()
        inner=QVBoxLayout(box)
        inner.setContentsMargins(0,0,0,0)
        label=QToolButton() if collapsed else QLabel(title)
        if collapsed:
            label.setText(title)
            label.setCheckable(True)
            label.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            label.setArrowType(Qt.ArrowType.RightArrow)
        font=label.font(); font.setBold(True); label.setFont(font)
        inner.addWidget(label)
        content=QWidget()
        grid=QGridLayout(content)
        grid.setContentsMargins(0,0,0,0)
        grid.setColumnStretch(0,1)
        grid.setVerticalSpacing(0)
        inner.addWidget(content)
        if collapsed:
            content.hide()
            label.toggled.connect(content.setVisible)
            label.toggled.connect(lambda on:label.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow))
        layout.addWidget(box)
        return grid,box

    def dial(self,g,row,name,label,lo,hi,fmt,apply,**kw):
        def applied(x):
            apply(x); self.changed()
        self.dials[name]=Dial(g,row,label,lo,hi,self.DEFAULTS[name],fmt,applied,**kw)

    def build_panel(self):
        body=QWidget()
        col=QVBoxLayout(body)
        v=self.view.set_dial
        secs=lambda x: f'{x:.0f} s'

        g,_=self.section(col,'setup · not saved in presets',collapsed=True)
        global_controls=QVBoxLayout()
        g.addLayout(global_controls,0,0,1,2)
        g,_=self.section(col,'look · saved in presets')
        preset_controls=QVBoxLayout()
        g.addLayout(preset_controls,0,0,1,2)
        everyday,_=self.section(preset_controls,'everyday')

        g,_=self.section(global_controls,'display')
        self.dial(g,0,'fps','FPS limit',15,120,lambda x: f'{round(x)} fps',self.set_fps,steps=105)
        self.actual_fps=QLabel('measuring FPS…')
        g.addWidget(self.actual_fps,2,0,1,2)
        note=QLabel('animation speed stays the same; actual FPS depends on the display and load')
        note.setWordWrap(True)
        g.addWidget(note,3,0,1,2)
        self.dial(g,4,'resolution','render scale',.5,2,lambda x: f'{x:.2f}×',lambda x:v('resolution',x),steps=6,live=False)
        self.dials['resolution'].slider.setToolTip('1× follows the window and display scaling; 2× smooths edges using up to four times the pixels')

        g,_=self.section(preset_controls,'advanced scale',collapsed=True)
        for row,(name,label) in enumerate((('waveScale','wave'),('particleScale','particles'),('distortionScale','distortion'))):
            self.dial(g,row*2,name,label,.25,3,lambda x:f'{x:.2f}×',lambda x,n=name:v(n,x),steps=110,live=name!='distortionScale')
        self.dials['waveScale'].slider.setToolTip('resize the main wave; existing trails fade naturally')
        self.dials['particleScale'].slider.setToolTip('resize secondary particles independently of the main wave')
        self.dials['distortionScale'].slider.setToolTip('resize the flow pattern while keeping it across the full window; applies on release')

        self.dial(everyday,4,'masterSpeed','master speed',0,4,lambda x:f'{x:.2f}×',lambda x:v('masterSpeed',x),steps=80)
        g,_=self.section(preset_controls,'advanced speed',collapsed=True)
        for row,(name,label) in enumerate((('flowSpeed','trail flow'),
                ('waveSpeed','wave motion'),('particleSpeed','particle motion / lifetime'),('colourSpeed','colour motion'))):
            self.dial(g,row*2,name,label,0,4,lambda x:f'{x:.2f}×',lambda x,n=name:v(n,x),steps=80)
        note=QLabel('master includes change intervals and trail decay; sound stays live')
        note.setWordWrap(True)
        g.addWidget(note,10,0,1,2)

        g,components_box=self.section(preset_controls,'components')
        preset_controls.insertWidget(1,components_box)
        for row,(kind,label,key) in enumerate((('W','wave shape','W'),('D','distortion','C'),('C','colours','X'),('P','secondary / particles','N'))):
            g.addWidget(QLabel(f'{label} ({key})'),row*2,0,1,2)
            combo=QComboBox()
            combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
            combo.activated.connect(lambda i,k=kind:self.choose_component(k,i))
            g.addWidget(combo,row*2+1,0,1,2)
            self.components[kind]=combo

        g,_=self.section(preset_controls,'advanced trails',collapsed=True)
        self.dial(everyday,6,'persist','trail length',3,240,lambda h: f'{h/FPS:.2f} s',lambda h: v('persist',.5**(1/h)),log=True)
        self.dials['persist'].slider.setToolTip('time for trails to fade to half their brightness at normal master speed; fade to black adds extra darkening')
        self.dial(g,2,'fadeBias','fade to black',0,4,lambda x: f'{x:.1f}/255',lambda x: v('fadeBias',x/255))
        self.dials['fadeBias'].slider.setToolTip('extra darkening on top of trail length; higher values erase faint trails sooner')

        self.dial(g,4,'hitHold','hit hold',0,250,lambda x:f'{round(x)} ms',lambda x:setattr(self.view,'hit_hold',x),steps=50)
        self.dials['hitHold'].slider.setToolTip('hold a brief loud audio shape long enough to leave a trail; 0 keeps the latest audio block')
        self.dial(g,6,'trailSharpness','trail sharpness',0,1,lambda x:f'{x:.0%}',lambda x:v('trailSharpness',x),steps=100)
        self.dials['trailSharpness'].slider.setToolTip('0% blends trails softly; 100% preserves finer detail as distortion moves them')
        self.dial(g,8,'trailFill','trail fill',1,8,lambda x:f'{round(x)}×',lambda x:v('trailFill',round(x)),steps=7)
        self.dials['trailFill'].slider.setToolTip('extra wave impressions between flow steps fill gaps; higher values can brighten trails and use more GPU time')

        g,_=self.section(preset_controls,'advanced lines',collapsed=True)
        self.dial(everyday,8,'widthScale','line width',.25,4,lambda x: f'x{x:.2f}',lambda x: v('widthScale',x),log=True)
        self.dial(g,2,'minWidth','minimum width',1,8,lambda x: f'{x:.1f} px',lambda x: v('minWidth',x))
        self.dial(g,4,'softness','edge softness',.25,4,lambda x: f'{x:.2f} px',lambda x: v('softness',x),log=True)
        self.dials['softness'].slider.setToolTip('soften the edges of drawn lines without changing their shape or motion')

        self.dial(everyday,10,'waveSmoothing','wave smoothing',0,12,lambda x:f'{x:.1f}',lambda x:v('waveSmoothing',x),steps=120)
        self.dials['waveSmoothing'].slider.setToolTip('smooth neighbouring waveform samples without lowering wave detail; edge softness smooths the drawn edges')
        self.dial(g,8,'waveResponse','wave response',0,250,lambda x:f'{round(x)} ms',lambda x:v('waveResponse',x),steps=50)
        self.dials['waveResponse'].slider.setToolTip('ease wave movement over time; 0 ms is immediate, higher values take longer to reach a new shape')
        self.force_connect=QCheckBox('force connected points')
        self.force_connect.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.force_connect.setToolTip('connect consecutive points in every wave and particle preset; off restores each preset’s normal behavior')
        self.force_connect.toggled.connect(lambda on:(v('forceConnect',int(on)),self.changed()))
        g.addWidget(self.force_connect,10,0,1,2)
        self.force_points=QCheckBox('force point count')
        self.force_points.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.force_points.setToolTip('use the wave detail dial’s point count for every wave and particle, including both waves during transitions; off restores preset point counts')
        self.force_points.toggled.connect(lambda on:(v('forcePoints',int(on)),self.changed()))
        g.addWidget(self.force_points,11,0,1,2)

        g,_=self.section(preset_controls,'advanced distortion',collapsed=True)
        self.dial(g,0,'grid','map resolution',128,2048,lambda x: f'{round(x/32)*32:.0f}',
                  lambda x: v('grid',round(x/32)*32),steps=60,live=False)
        self.dials['grid'].slider.setToolTip('map points along the longer edge; higher values add flow detail but take more memory and time to calculate')
        self.field_resolution=QLabel('')
        g.addWidget(self.field_resolution,2,0,1,2)

        # Outside the boxes it explains, so it stays readable while they are greyed.
        self.paused_note=QLabel('paused (Space): automatic changes and particle spawning resume with Space')
        self.paused_note.setWordWrap(True)
        self.paused_note.setVisible(False)
        global_controls.addWidget(self.paused_note)
        g,self.changes_box=self.section(global_controls,'automatic changes')
        note=QLabel('each part switches on its own, at a random time between its two waits')
        note.setWordWrap(True)
        g.addWidget(note,0,0,1,2)
        row=1
        for kind,label in (('W','wave shape'),('D','distortion'),('C','colours')):
            self.interval_dials(g,row,kind,label,'every'); row+=5

        g,_=self.section(global_controls,'blend between looks')
        self.dial(g,0,'transitionLo','shortest',0,30,secs,lambda x: self.transition('transitionLo',x),steps=30)
        self.dial(g,2,'transitionHi','longest',0,30,secs,lambda x: self.transition('transitionHi',x),steps=30)
        note=QLabel('W, C, X and R use the shortest')
        g.addWidget(note,4,0,1,2)

        g,self.particles_box=self.section(global_controls,'particles')
        self.particles=QCheckBox('particles on')
        self.particles.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.particles.toggled.connect(self.set_particles)
        g.addWidget(self.particles,0,0,1,2)
        self.interval_dials(g,1,'P','each particle','lasts')
        self.dial(g,6,'rate','spawn rate',.1,10,lambda x: f'x{x:.2f}',self.set_rate,log=True)

        g,_=self.section(global_controls,'audio')
        self.dial(everyday,2,'sensitivity','sensitivity',.1,5,lambda x: f'{x*100:.0f}%',lambda x: v('sensitivity',x),log=True)
        self.dial(everyday,0,'steps','wave detail',16,550,lambda x: f'{round(x)} points',lambda x: v('steps',round(x)),steps=534)
        self.normalize=QCheckBox('normalise level')
        self.normalize.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.normalize.toggled.connect(lambda on: (v('normalize',1 if on else 0),self.changed()))
        g.addWidget(self.normalize,4,0,1,2)
        self.audio_only=QCheckBox('audio-reactive only')
        self.audio_only.setToolTip('skip shapes and particles that move the same without sound')
        self.audio_only.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.audio_only.toggled.connect(lambda on: (v('audioOnly',1 if on else 0),self.changed()))
        g.addWidget(self.audio_only,5,0,1,2)

        self.compare_button=QPushButton('compare defaults')
        self.compare_button.setCheckable(True)
        self.compare_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.compare_button.setToolTip('preview the application defaults without saving; click again to restore your current settings')
        self.compare_button.toggled.connect(self.compare_defaults)
        col.addWidget(self.compare_button)
        self.reset_button=QPushButton('reset all')
        self.reset_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reset_button.clicked.connect(self.reset)
        col.addWidget(self.reset_button)
        col.addStretch(1)

        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dock=QDockWidget('dials',self)
        self.dock.setObjectName('dials')
        self.dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable|QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.dock.setWidget(scroll)
        self.dock.setMinimumWidth(260)
        self.dock.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.dock)
        self.dock.setVisible(self.read().get('panel',True))
        self.dock.visibilityChanged.connect(lambda _: self.changed())
        body.setEnabled(False)   # until the renderer exists
        self.body=body

    # The engine takes "A + rnd( B )"; the panel shows the range A..A+B as a
    # shortest and a longest wait. dials.json keeps [A, B].
    def interval_dials(self,g,row,kind,label,verb):
        a,b=self.DEFAULTS['intervals'][kind]
        name=QLabel(label)
        font=name.font(); font.setItalic(True); name.setFont(font)
        summary=QLabel()
        summary.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        g.addWidget(name,row,0); g.addWidget(summary,row,1)
        s=lambda x: f'{x:.0f} s'
        lo=Dial(g,row+1,'shortest',1,180,a,s,lambda _: self.set_interval(kind,'lo'),steps=179)
        hi=Dial(g,row+3,'longest',1,180,a+b,s,lambda _: self.set_interval(kind,'hi'),steps=179)
        self.intervals[kind]=(lo,hi)
        self.summaries[kind]=(summary,verb)

    def set_interval(self,kind,moved=None):
        lo,hi=self.intervals[kind]
        # Keep the range ordered: moving one end past the other drags it.
        if lo.get()>hi.get():
            (hi if moved=='lo' else lo).set(lo.get() if moved=='lo' else hi.get())
        a=round(lo.get()); b=max(0,round(hi.get())-a)
        summary,verb=self.summaries[kind]
        summary.setText(f'{verb} {a} s' if b==0 else f'{verb} {a}–{a+b} s')
        lib.gf_set_interval(ord(kind),f'{a} + rnd( {b} )'.encode())
        self.changed()

    def set_fps(self,x):
        self.view.timer.setInterval(math.ceil(1000/x))
        self.view.set_dial('fps',round(x))

    def set_rate(self,x):
        lib.gf_set_interval(ord('R'),(f'{x:.3f}*'+PARTICLE_RATE).encode())

    def transition(self,name,x):
        # Keep the blend range ordered: moving one end past the other drags it.
        self.view.set_dial(name,round(x))
        lo,hi=self.dials['transitionLo'],self.dials['transitionHi']
        if lo.get()>hi.get():
            (hi if name=='transitionLo' else lo).set(round(x),notify=True)

    def renderer_ready(self):
        """Seed from the engine (.G-Force), overlaid by whatever dials.json holds."""
        saved=self.read()
        data={name:lib.gf_get(name.encode()) for name in self.ENGINE}
        data['particles']=bool(lib.gf_get(b'particles'))
        data['normalize']=bool(lib.gf_get(b'normalize'))
        data['audioOnly']=False
        data['intervals']={}
        for kind in self.intervals:
            m=INTERVAL.match(lib.gf_get_interval(ord(kind)).decode())
            if m:
                data['intervals'][kind]=[float(m[1]),float(m[2])]
        m=RATE.match(lib.gf_get_interval(ord('R')).decode())
        data['rate']=float(m[1] or 1) if m else 1.
        data.update(saved)
        self.apply(data)
        self.body.setEnabled(True)
        self.sync_components()
        self.set_paused_ui(self.paused)
        self.rebuild_presets_menu()
        self.save()

    def set_particles(self,on):
        self.view.set_dial('particles',int(on))
        self.particles.blockSignals(True)
        self.particles.setChecked(on)
        self.particles.blockSignals(False)
        if hasattr(self,'particles_action'): self.particles_action.setChecked(on)
        self.changed()

    def sync_components(self):
        if not self.view.ready: return
        self.full_action.setChecked(self.isFullScreen())
        for kind,combo in self.components.items():
            if combo.view().isVisible(): continue
            names=lib.gf_choices(ord(kind)).decode().splitlines()
            current=lib.gf_selection(ord(kind)).decode()
            if current and current not in names: names.append(current)
            if names!=[combo.itemData(i) for i in range(combo.count())]:
                combo.blockSignals(True)
                combo.clear()
                for name in names: combo.addItem(name.replace('_',' '),name)
                combo.blockSignals(False)
            combo.setCurrentIndex(combo.findData(current))
        on=bool(lib.gf_get(b'particles'))
        self.particles.blockSignals(True)
        self.particles.setChecked(on)
        self.particles.blockSignals(False)
        self.particles_action.setChecked(on)

    def choose_component(self,kind,index):
        name=self.components[kind].itemData(index)
        if self.view.ready and name:
            if not lib.gf_select(ord(kind),name.encode()):
                self.flash('could not load '+name)
            self.sync_components()
            self.changed()
            self.view.update()
        self.view.setFocus()

    def reset(self):
        if self.comparison is not None:
            return
        if self.tween:
            self.tween.stop(); self.tween=None
        self.apply({'panel':self.dock.isVisible()})
        self.save()

    def compare_defaults(self,on):
        if on and self.comparison is None:
            if self.tween:
                self.tween.stop(); self.tween=None
            self.save_timer.stop()
            self.save()
            self.comparison=(self.values(),self.paused)
            self.view.set_dial('paused',1)
            self.update_title(True)
            self.apply({'panel':self.dock.isVisible()})
            self.flash('previewing defaults · temporary adjustments are not saved')
        elif not on and self.comparison is not None:
            if self.tween:
                self.tween.stop(); self.tween=None
            values,paused=self.comparison
            self.apply(values)
            self.view.set_dial('paused',int(paused))
            self.update_title(paused)
            self.comparison=None
            self.flash('restored your settings')
        self.compare_button.blockSignals(True)
        self.compare_button.setChecked(self.comparison is not None)
        self.compare_button.blockSignals(False)
        self.compare_button.setText('return to my settings' if self.comparison is not None else 'compare defaults')
        self.reset_button.setEnabled(self.comparison is None)

    def toggle_panel(self):
        self.dock.setVisible(not self.dock.isVisible())
        self.view.setFocus()

    def set_paused_ui(self,paused):
        # While paused the engine schedules no changes and spawns no particles,
        # so those dials would move without visible effect: grey them out.
        self.changes_box.setEnabled(not paused)
        # Visibility remains available while automatic spawning is paused.
        for dial in self.intervals['P']: dial.slider.setEnabled(not paused)
        self.dials['rate'].slider.setEnabled(not paused)
        self.paused_note.setVisible(paused)

    def update_title(self,paused):
        self.paused=paused
        if self.body.isEnabled():
            self.set_paused_ui(paused)
        if hasattr(self,'pause_action'):
            self.pause_action.setChecked(paused)
        self.setWindowTitle('G-Force — '+('changes paused' if paused else 'auto changes'))

    # ---- menus -------------------------------------------------------------
    # The keys are handled by the view; the menus name them after a tab (Qt's
    # shortcut column) instead of binding QAction shortcuts, which would fire
    # twice or steal the letters from the engine.
    def action(self,menu,label,key,slot,checkable=False):
        a=QAction(f'{label}\t{key}' if key else label,self)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def build_menus(self):
        bar=self.menuBar()
        m=bar.addMenu('visualizer')
        self.action(m,'next wave shape','W',lambda: self.view.send_key('w'))
        self.action(m,'next distortion','C',lambda: self.view.send_key('c'))
        self.action(m,'next colours','X',lambda: self.view.send_key('x'))
        self.action(m,'next secondary / particles','N',lambda: self.view.send_key('n'))
        self.particles_action=self.action(m,'show secondary / particles','P',lambda: self.view.send_key('p'),checkable=True)
        self.action(m,'randomise','R',lambda: self.view.send_key('r'))
        self.pause_action=self.action(m,'pause changes','Space',lambda: self.view.send_key(' '),checkable=True)
        m.addSeparator()
        self.action(m,'close','Esc',self.close)
        self.presets_menu=bar.addMenu('presets')
        v=bar.addMenu('view')
        self.dials_action=self.action(v,'dials','Tab',self.toggle_panel,checkable=True)
        self.dials_action.setChecked(self.dock.isVisible())
        self.dock.visibilityChanged.connect(self.dials_action.setChecked)
        self.full_action=self.action(v,'fullscreen','F11',
            lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen(),checkable=True)
        self.load_presets()

    # ---- presets -----------------------------------------------------------
    def load_presets(self,_=None):
        try:
            data=json.loads(PRESETS.read_text())
            self.presets=[p for p in data if isinstance(p,dict) and p.get('components')] if isinstance(data,list) else []
        except (OSError,ValueError):
            self.presets=[]
        self.rebuild_presets_menu()

    def write_presets(self):
        tmp=PRESETS.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.presets,indent=1)+'\n')
        os.replace(tmp,PRESETS)

    def rebuild_presets_menu(self):
        m=self.presets_menu
        m.clear()
        self.action(m,'save current look','S',self.save_preset).setEnabled(self.view.ready)
        m.addSeparator()
        if not self.presets:
            m.addAction('no saved presets').setEnabled(False)
            return
        for i,p in enumerate(self.presets):
            self.action(m,f'{i+1}  {p["name"]}',None,lambda _=False,i=i: self.recall_preset(i))
        m.addSeparator()
        delete=QMenu('delete',m)
        for i,p in enumerate(self.presets):
            self.action(delete,f'{i+1}  {p["name"]}',None,lambda _=False,i=i: self.delete_preset(i))
        m.addMenu(delete)

    def save_preset(self):
        if not self.view.ready:
            return
        text=lib.gf_preset_capture().decode()
        comps=[l.split('\t') for l in text.strip().split('\n') if l.count('\t')==2]
        comps=[[k,n,int(seed)] for k,n,seed in comps]
        pretty=lambda k: next((n.replace('_',' ') for kk,n,_ in comps if kk==k),'?')
        preset={'name':f"{pretty('W')} · {pretty('D')} · {pretty('C')}",
                'saved':time.strftime('%Y-%m-%dT%H:%M:%S'),
                'components':comps,
                'dials':{**{k:round(self.dials[k].get(),4) for k in LOOK_DIALS},'forceConnect':self.force_connect.isChecked(),'forcePoints':self.force_points.isChecked()}}
        self.load_presets()   # pick up edits from elsewhere before appending
        self.presets.append(preset)
        try:
            self.write_presets()
        except OSError as e:
            self.flash(f'could not save preset: {e}')
            return
        self.rebuild_presets_menu()
        self.flash(f'saved preset {len(self.presets)}: {preset["name"]}')

    def recall_preset(self,i):
        if self.comparison is not None:
            self.compare_defaults(False)
        p=self.presets[i]
        missing=[]
        lib.gf_preset_clear_particles()
        # Shapes and colours blend in over the blend dials; the look they end
        # on is the saved one, seeded rnd() constants included.
        for kind,name,seed in p['components']:
            if not lib.gf_preset_recall(ord(kind),name.encode(),int(seed),1):
                missing.append(name)
        self.force_connect.setChecked(bool(p.get('dials',{}).get('forceConnect',False)))
        self.force_points.setChecked(bool(p.get('dials',{}).get('forcePoints',False)))
        self.ease_look({k:float(v) for k,v in self.migrate_scales(p.get('dials',{})).items() if k in self.dials})
        # A recalled look should stay put: pause automatic changes (Space resumes).
        self.view.set_dial('paused',1)
        self.view.sync_state()
        self.flash(f'preset {i+1}: {p["name"]}'+(f' (not installed: {", ".join(missing)})' if missing else '')+' · Space resumes changes')

    def ease_look(self,target):
        # Glide the look dials over the shortest blend instead of jumping, so
        # trails and line widths change with the shapes and colours.
        if self.tween:
            self.tween.stop()
        # These rebuild the field; apply once instead of re-evaluating every tween tick.
        for name in ('grid','distortionScale'):
            if name in target:
                self.dials[name].set(target.pop(name),notify=True)
        start={k:self.dials[k].get() for k in target}
        steps=max(1,round(max(1.,self.dials['transitionLo'].get())*FPS))
        n=[0]
        def tick():
            n[0]+=1
            f=n[0]/steps
            f=f*f*(3-2*f)
            self.loading=True
            for k,v in target.items():
                self.dials[k].set(start[k]+(v-start[k])*f,notify=True)
            self.loading=False
            if n[0]>=steps:
                self.tween.stop(); self.tween=None
                self.changed()
        self.tween=QTimer(self,interval=round(1000/FPS))
        self.tween.timeout.connect(tick)
        self.tween.start()
        tick()

    def delete_preset(self,i):
        self.load_presets()
        if i<len(self.presets):
            name=self.presets.pop(i)['name']
            self.write_presets()
            self.rebuild_presets_menu()
            self.flash(f'deleted preset {i+1}: {name}')

    def flash(self,text):
        # A status line only while there is something to say.
        bar=self.statusBar()
        bar.show()
        bar.showMessage(text,4000)
        print(text,flush=True)

    def status_cleared(self,text):
        if not text:
            self.statusBar().hide()

    def changeEvent(self,event):
        if event.type()==event.Type.WindowStateChange and hasattr(self,'full_action'):
            self.full_action.setChecked(self.isFullScreen())
        super().changeEvent(event)

    def closeEvent(self,event):
        if self.view.ready:
            self.save()
        self.view.cleanup()
        event.accept()
        app.quit()


window=Window()
# systemctl stop / logout send SIGTERM: close cleanly so the engine and dials save.
signal.signal(signal.SIGTERM,lambda *_: window.close())
signal.signal(signal.SIGINT,lambda *_: window.close())
window.show()
sys.exit(app.exec())

#!/usr/bin/env python3
"""Isolated QML layout and disposable worker lifecycle; no mpv or audio server."""
import importlib.util
import os
import json
import struct
from pathlib import Path
import sys

assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fixture',HERE/'now-allinone-test.py')
f=importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlFileSelector
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
sys.path.insert(0,str(HERE.parent))
import visualizer

app=QGuiApplication([])
assert app.platformName()=='offscreen'
visualizer.register()
qInstallMessageHandler(f.on_qml_message)
f.seed_db()
prefs=f.P.Prefs(); library=f.P.Library(f.P.TagWriter(prefs)); player=f.StubPlayer()
bridge=f.P.Bridge(library,player,None)
visual=visualizer.Visualizer('isolated-player')
frame_worker="""import json,struct,sys,time
state=json.loads(sys.argv[1]);state['ready']=True
state['choices']={'W':['fixture wave'],'D':['fixture flow'],'C':['fixture colours'],'P':[]}
state['presets']=['fixture look']
state['selections']={'W':'fixture wave','D':'fixture flow','C':'fixture colours','P':''}
for kind,data in [(b'J',json.dumps(state).encode()),(b'F',struct.pack('!II',1,1)+bytes([255,0,0,255]))]:
    sys.stdout.buffer.write(kind+struct.pack('!I',len(data))+data);sys.stdout.buffer.flush()
time.sleep(60)
"""
visual.worker_command=[sys.executable,'-c',frame_worker,json.dumps(visual.state)]
frames=[]
visual.frame.connect(lambda image:frames.append((image.width(),image.height())))
keep=[prefs,library,player,bridge,visual]
for plasma in (False,True):
    engine=QQmlApplicationEngine(); keep.append(engine)
    if plasma:
        selector=QQmlFileSelector(engine,engine); selector.setExtraSelectors(['plasma']); keep.append(selector)
    ctx=engine.rootContext()
    for name,obj in {'Prefs':prefs,'Library':bridge,'Player':player,'Visualizer':visual,
        'DeskStyle':f.StubStyle(),'WalPalette':f.StubPalette(),'Lyrics':f.StubLyrics(),
        'QueueModel':bridge.queueModel}.items():
        keep.append(obj); ctx.setContextProperty(name,obj)
    ctx.setContextProperty('OnAir',False)
    tc=QQmlComponent(engine,QUrl.fromLocalFile(str(f.QML/'theme/Theme.qml')))
    theme=tc.create(); assert theme,tc.errorString(); keep.extend([tc,theme]);ctx.setContextProperty('Theme',theme)
    comp=QQmlComponent(engine,QUrl.fromLocalFile(str(f.QML/'VisualizerPage.qml')))
    page=comp.create(); assert page,comp.errorString();keep.extend([comp,page])
    scene=QQuickWindow();keep.append(scene);page.setParentItem(scene.contentItem());scene.show()
    for width,height in ((960,700),(1400,950),(480,320)):
        page.setWidth(width);page.setHeight(height);QTest.qWait(50)
        surface=page.findChild(QObject,'visualizerSurface')
        queue=page.findChild(QObject,'visualizerQueue')
        info=page.findChild(QObject,'visualizerInformation')
        assert surface.height()>0 and info.width()>0
        assert info.x()>=queue.width()
        assert page.findChild(QObject,'visualizerInfoPane') is not None
        scroll=page.findChild(QObject,'visualizerInformationScroll')
        assert scroll.property('contentHeight') >= scroll.height()
        if height == 320:
            assert scroll.property('contentHeight') > scroll.height()
            scroll.setProperty('contentY',40.)
            assert scroll.property('contentY') == 40.
            scroll.setProperty('contentY',0.)
        stars=page.findChild(QObject,'visualizerStars')
        heart=page.findChild(QObject,'visualizerFavorite')
        assert abs(stars.y()+stars.height()/2-heart.y()-heart.height()/2)<.5
        assert stars.x()+stars.width() <= heart.x()
        before=surface.width();page.setProperty('sidebar',False);QTest.qWait(10)
        assert surface.width()>before
        page.setProperty('sidebar',True)
    assert not f.QML_MSGS, f.QML_MSGS
    scene.hide()
    assert visual.process is None,'page construction started worker without visibility authorization'
    print('PASS layout and sidebar', 'Plasma' if plasma else 'Hyprland')

window=QQuickWindow();window.show();QTest.qWait(20)
visual.bind_window(window)
assert visual.process is None
visual.setShown(True);QTest.qWait(200)
assert visual.process is not None
pid=visual.process.processId();assert pid
assert frames==[(1,1)]
assert visual.choices["W"]==["fixture wave"] and visual.presetNames==["fixture look"]
visual.setShown(False);QTest.qWait(200)
assert visual.process is None,'hidden worker remains'
try: os.kill(pid,0)
except ProcessLookupError: pass
else: raise AssertionError('worker survived hiding')
visual.setShown(True);QTest.qWait(100)
assert visual.process is not None
window.showMinimized();QTest.qWait(150)
assert visual.process is None,'minimized window retains worker'
window.showNormal();QTest.qWait(100)
assert visual.process is not None
window.hide();QTest.qWait(150)
assert visual.process is None,'hidden window retains worker'
window.show();QTest.qWait(100)
assert visual.process is not None
visual.shutdown()
assert visual.process is None
print('PASS frames, state, hide, minimize, resume, shutdown release worker')
probe=visualizer.Visualizer('isolated-statistics')
class Snapshot:
    def readAllStandardOutput(self):
        data=json.dumps(self.state).encode()
        return b'J'+struct.pack('!I',len(data))+data
snapshot=Snapshot();probe.process=snapshot
changes=[];statistics=[]
probe.changed.connect(lambda:changes.append(True))
probe.statisticsChanged.connect(lambda:statistics.append(True))
snapshot.state={**probe.state,'actualFps':60,'renderWidth':640,'renderHeight':360}
probe.read_output(snapshot)
snapshot.state['actualFps']=59
probe.read_output(snapshot)
assert len(statistics)==2 and not changes,'statistics refreshed all controls'
snapshot.state['paused']=True
probe.read_output(snapshot)
assert len(changes)==1
probe.process=None
print('PASS statistics do not invalidate unchanged controls')
# Destroy QML before its context objects.
for obj in reversed(keep):
    if isinstance(obj,QQmlApplicationEngine): obj.deleteLater()
QTest.qWait(10)

# The complete root/chrome uses scratch state and a no-audio mpv stand-in.
# Constructor-time AutoScanner work is explicitly removed from this fixture.
import subprocess
import tempfile
with tempfile.TemporaryDirectory(prefix='visualizer-root-') as tmp:
    root=Path(tmp);env=os.environ.copy()
    for name in ('DATA','STATE','CONFIG','CACHE','RUNTIME'):
        path=root/name;path.mkdir(mode=0o700)
        env['XDG_'+name+'_HOME' if name!='RUNTIME' else 'XDG_RUNTIME_DIR']=str(path)
    stub=root/'stub';stub.mkdir()
    (stub/'mpv.py').write_text('''class MPV:
    def __init__(self,**kw):
        self.volume=100; self.pause=True; self.playlist_count=0; self.playlist_pos=0
    def property_observer(self,name): return lambda fn: fn
    def command(self,*args): pass
    def __setitem__(self,key,value): pass
''')
    env.update(PYTHONPATH=str(stub),PLAYER_LIBRARY_ROOT=str(root/'music'),
               QT_QUICK_CONTROLS_STYLE='Basic',QT_STYLE_OVERRIDE='Fusion',
               QT_QPA_PLATFORMTHEME='',PIPEWIRE_REMOTE='/dev/null',PULSE_SERVER='unix:'+str(root/'no-pulse'),
               DBUS_SESSION_BUS_ADDRESS='unix:path='+str(root/'no-bus'),PLAYER_VIEW='visualizer',
               PLAYER_MENUS='1',PLAYER_SKIP_NATIVE_CHROME='',LASTFM_CONFIG=str(root/'no-lastfm'))
    for key in ('DISPLAY','WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE'):env.pop(key,None)
    code=f"import sys;sys.path.insert(0,{str(HERE.parent)!r});import main;main.AutoScanner=lambda *args:None;main.main()"
    for session in ('hypr','plasma'):
        env['DESK_SESSION']=session
        result=subprocess.run([sys.executable,'-c',code,'--selftest'],env=env,capture_output=True,text=True,timeout=40)
        assert result.returncode==0,result.stdout+result.stderr
        assert '0 QML warning(s)' in result.stdout
        if session=='plasma':
            assert '[x] V&isualizer' in result.stdout
            assert 'Show Visualizer Controls  Tab' in result.stdout
            assert 'Pause or Resume Changes  Shift+Space' in result.stdout
            assert 'Play  Space' in result.stdout
        print('PASS full Player view and keyboard ownership',session)


# Titlebar ownership uses only a fresh Player lease, in either visualizer view.
import runpy
import time
cava=runpy.run_path(str(HERE.parents[2]/'home/prog/plasma-player-visualizer-files/cava-state.py'))
with tempfile.TemporaryDirectory(prefix='visualizer-lease-') as tmp:
    lease=Path(tmp)/'player-view.json'
    for view,age,expected in [('now',0,True),('visualizer',0,True),
                              ('albums',0,False),('visualizer',5,False)]:
        lease.write_text(json.dumps({'view':view,'updated':time.time()-age}))
        assert cava['player_owns_visualizer'](tmp)==expected
    lease.write_text('{')
    assert not cava['player_owns_visualizer'](tmp)
print('PASS titlebar Cava suppression and expired lease fallback')

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
from PySide6.QtCore import QObject, QUrl, Qt, qInstallMessageHandler
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
        assert queue.x()==info.x()+info.width()+7
        assert queue.y()==info.y()==0
        assert queue.height()==info.height()
        assert info.width()+7+queue.width()==page.width()
        assert queue.height()>0
        for name,cursor in (('visualizerInfoDivider',Qt.SplitHCursor),
                            ('visualizerTopDivider',Qt.SplitVCursor)):
            divider=page.findChild(QObject,name)
            assert divider.property('cursorShape')==cursor
            assert divider.property('hoverEnabled') and divider.height()>=7
        assert info.parentItem().y()>=surface.height()+7
        assert page.findChild(QObject,'visualizerInfoPane') is None
        assert page.findChild(QObject,'visualizerInformationScroll') is None
        art=page.findChild(QObject,'visualizerArt')
        album=page.findChild(QObject,'visualizerAlbumYear')
        rating=page.findChild(QObject,'visualizerRating')
        assert art.width()==art.height() and 0<art.height()<=info.height()
        assert art.height()==min(info.height(),info.width()-max(120,rating.width())-16)
        assert rating.y()>=album.y()+album.height()
        assert rating.parentItem().y()+rating.y()+rating.height()<=info.height(), (rating.parentItem().y(),rating.y(),rating.height(),info.height())
        assert rating.width()<=rating.parentItem().width()
        stars=page.findChild(QObject,'visualizerStars')
        heart=page.findChild(QObject,'visualizerFavorite')
        assert abs(stars.y()+stars.height()/2-heart.y()-heart.height()/2)<.5
        assert stars.x()+stars.width() <= heart.x()
        before=surface.width();page.setProperty('sidebar',False);QTest.qWait(10)
        assert surface.width()>before
        page.setProperty('sidebar',True)
        page.setProperty('topFrac',1)
        QTest.qWait(20)
        assert info.height()==queue.height()==100, 'lower section cannot shrink to half its old floor'
        assert art.width()==art.height() and 0<art.height()<=100
        if width>=960:
            assert art.height()==100, 'cover did not scale down with the pane'
        assert rating.parentItem().y()+rating.y()+rating.height()<=info.height(), (rating.parentItem().y(),rating.y(),rating.height(),info.height())
        page.setProperty('topFrac',.5)
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
    code=f"""
import sys
sys.path.insert(0,{str(HERE.parent)!r})
import main
from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtTest import QTest
main.AutoScanner=lambda *args:None
original=main._selftest
def check_layout(app,shell,win,*args):
    root=shell.root if shell is not None else win.property('contentItem').childItems()[0]
    root.setProperty('view','visualizer')
    root.setProperty('visualAlbumFrac',.5)
    QTest.qWait(100)
    root.findChild(QObject,'visualizerSurface').parentItem().parentItem().setProperty('bottomCollapsed',False)
    QTest.qWait(20)
    grid=root.findChild(QObject,'albumGrid')
    surface=root.findChild(QObject,'visualizerSurface')
    assert grid and grid.isVisible() and surface
    gallery=grid.parentItem()
    right=surface.parentItem().parentItem().parentItem()
    assert abs(gallery.width()-right.width())<=1
    divider=root.findChild(QObject,'visualizerAlbumDivider')
    assert divider.isVisible() and divider.width()>=9
    assert divider.property('cursorShape')==Qt.SplitHCursor
    assert divider.property('hoverEnabled')
    assert gallery.x()==0 and right.x()==gallery.width()+divider.width()
    assert divider.x()==gallery.width()
    target=shell.view if shell is not None else win
    target.show()
    QTest.qWait(50)
    for name, owner, prop, delta in (
        ('visualizerAlbumDivider',root,'visualAlbumFrac',QPoint(30,0)),
        ('visualizerTopDivider',surface.parentItem().parentItem(),'topFrac',QPoint(0,-20)),
        ('visualizerInfoDivider',surface.parentItem().parentItem(),'infoFrac',QPoint(20,0))):
        handle=root.findChild(QObject,name)
        point=handle.mapToScene(QPointF(handle.width()/2,handle.height()/2)).toPoint()
        before=owner.property(prop)
        QTest.mouseMove(target,point)
        QTest.mousePress(target,Qt.LeftButton,Qt.NoModifier,point)
        QTest.mouseMove(target,point+delta,20)
        QTest.mouseRelease(target,Qt.LeftButton,Qt.NoModifier,point+delta)
        QTest.qWait(20)
        assert abs(owner.property(prop)-before)>.001, name+' did not drag'
    page=surface.parentItem().parentItem()
    handle=root.findChild(QObject,'visualizerTopDivider')
    queue=root.findChild(QObject,'visualizerQueue')
    for collapse in (True,False,True):
        point=handle.mapToScene(QPointF(handle.width()/2,handle.height()/2)).toPoint()
        end=page.mapToScene(QPointF(page.width()/2,page.height()-(2 if collapse else 150))).toPoint()
        QTest.mousePress(target,Qt.LeftButton,Qt.NoModifier,point)
        QTest.mouseMove(target,end,20)
        QTest.mouseRelease(target,Qt.LeftButton,Qt.NoModifier,end)
        QTest.qWait(20)
        assert page.property('bottomCollapsed')==collapse
        assert queue.isVisible()!=collapse
        assert handle.y()+handle.height()<=page.height()
        if collapse:
            assert queue.height()==0 and handle.y()+handle.height()==page.height()
            assert surface.height()==page.height()-handle.height()
        else:
            assert queue.height()>=100
    root.setProperty('visualAlbumFrac',.65)
    QTest.qWait(50)
    assert gallery.width()>right.width()
    assert right.x()==gallery.width()+divider.width()
    assert gallery.width()+divider.width()+right.width()==gallery.parentItem().width()
    assert gallery.height()==right.height()
    root.openAlbum(0)
    assert root.property('view')=='visualizer'
    root.setProperty('view','albums')
    QTest.qWait(50)
    assert grid.width()==gallery.parentItem().width()
    root.setProperty('view','visualizer')
    QTest.qWait(50)
    assert root.findChild(QObject,'albumGrid')==grid
    assert root.findChild(QObject,'visualizerSurface').parentItem().parentItem().property('bottomCollapsed')
    assert not root.findChild(QObject,'visualizerQueue').isVisible()
    assert abs(grid.width()-(gallery.parentItem().width()-divider.width())*.65)<=1
    return original(app,shell,win,*args)
main._selftest=check_layout
main.main()
"""
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

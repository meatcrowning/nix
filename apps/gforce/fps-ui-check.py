"""Offscreen panel/persistence check with a stand-in renderer; no GL or audio."""
import ast
import os
from pathlib import Path
import tempfile

assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
assert not os.environ.get('QT_QPA_PLATFORMTHEME')
from PySide6.QtWidgets import QApplication, QWidget
app=QApplication([])
assert app.platformName()=='offscreen'

class Renderer:
    def __init__(self):
        self.settings={'particles':1}
        self.selections={k:'first' for k in 'WDCP'}
    def gf_set(self,name,value): self.settings[name.decode()]=value; return 1
    def gf_set_interval(self,*args): pass
    def gf_get(self,name): return self.settings.get(name.decode(),0)
    def gf_close(self): pass
    def gf_preset_capture(self): return b""
    def gf_preset_clear_particles(self): pass
    def gf_choices(self,kind): return b'first\nsecond\n'
    def gf_selection(self,kind): return self.selections[chr(kind)].encode()
    def gf_select(self,kind,name): self.selections[chr(kind)]=name.decode(); return 1


root=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='gforce-ui-') as tmp:
    os.environ['GF_SHARED_DIALS_DIR']=str(Path(tmp)/'shared')
    ns={'__file__':str(root/'main.py'),'app':app,'lib':Renderer()}
    tree=ast.parse((root/'main.py').read_text())
    allowed={'ROOT','LOOK_DIALS','FPS','PARTICLE_RATE','INTERVAL','RATE'}
    body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.ClassDef)) or
          isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in allowed for t in n.targets)]
    # QWidget substitutes for unsupported offscreen QOpenGLWidget; no show/initGL.
    imports=[n for n in body if isinstance(n,(ast.Import,ast.ImportFrom))]
    exec(compile(ast.Module(imports,type_ignores=[]),str(root/'main.py'),'exec'),ns)
    ns.update(QOpenGLWidget=QWidget,STATE=Path(tmp),DIALS=Path(tmp)/'dials.json',PRESETS=Path(tmp)/'presets.json')
    exec(compile(ast.Module([n for n in body if n not in imports],type_ignores=[]),str(root/'main.py'),'exec'),ns)
    window=ns['Window']()
    assert next(iter(window.dials))=='fps', 'FPS must be first in panel'
    for fps in (15,30,60,120):
        window.apply({'fps':fps})
        assert window.view.timer.interval()==ns['math'].ceil(1000/fps)
        window.save()
        assert window.read()['fps']==fps
    window.actual_fps.setText('47.5 fps actual')
    assert window.actual_fps.text()=='47.5 fps actual'
    window.view.ready=True
    window.body.setEnabled(True)
    # The stand-in widget needs no GL context for settings or cleanup.
    window.view.makeCurrent=lambda:None
    window.view.doneCurrent=lambda:None
    window.sync_components()
    for kind,combo in window.components.items():
        assert combo.count()==2 and combo.currentData()=='first'
        combo.setCurrentIndex(1)
        combo.activated.emit(1)
        assert ns['lib'].selections[kind]=='second'
    ns['lib'].selections['W']='first'
    window.sync_components()
    assert window.components['W'].currentData()=='first','automatic/hotkey changes must update dropdowns'
    window.set_particles(False)
    assert ns['lib'].settings['particles']==0 and not window.particles.isChecked()
    assert window.particle_visibility.currentIndex()==0 and not window.particles_action.isChecked()
    window.particle_visibility.setCurrentIndex(1)
    window.particle_visibility.activated.emit(1)
    assert ns['lib'].settings['particles']==1 and window.particles.isChecked()
    window.set_paused_ui(True)
    assert window.particles_box.isEnabled() and not window.dials['rate'].slider.isEnabled()
    assert not window.intervals['P'][0].slider.isEnabled()
    for name,value in [('waveResponse',80),('trailFill',4),('trailSharpness',.37),('masterSpeed',.5),('waveSpeed',2),('particleSpeed',3),('colourSpeed',1.5),
                       ('flowSpeed',0),('waveScale',.5),('particleScale',.75),('distortionScale',1.5),('waveSmoothing',8),('resolution',1.5),('hitHold',100)]:
        window.dials[name].set(value,notify=True)
    window.save()
    saved=window.read()
    window.apply(saved)
    for name in ('waveResponse','trailFill','trailSharpness','masterSpeed','waveSpeed','particleSpeed','colourSpeed','flowSpeed','waveScale','particleScale','distortionScale','waveSmoothing','resolution'):
        assert abs(ns['lib'].settings[name]-saved[name])<1e-4,(name,ns['lib'].settings,saved)
    assert window.view.hit_hold==100
    assert saved['waveResponse']==80
    assert 'waveResponse' in ns['LOOK_DIALS']
    assert saved['trailFill']==4
    assert 'trailFill' in ns['LOOK_DIALS']
    assert saved['trailSharpness']==.37
    assert 'trailSharpness' in ns['LOOK_DIALS']
    window.apply({})
    assert window.dials['waveResponse'].get()==0.
    assert window.dials['trailFill'].get()==1.
    assert window.dials['trailSharpness'].get()==1.,'old settings keep the sharper default'
    menu_text=' '.join(a.text() for a in window.findChildren(ns['QAction']))
    for key in ('W','C','X','N','P','R','Space','S','Tab','F11','Esc'):
        assert '\t'+key in menu_text,('missing menu action',key)
    window.apply({'sceneScale':.5})
    assert all(window.dials[k].get()==.5 for k in ('waveScale','particleScale','distortionScale'))
    window.apply({'sceneScale':.5,'particleScale':2})
    assert window.dials['particleScale'].get()==2
    assert window.dials['waveScale'].get()==.5
    window.save()
    assert 'sceneScale' not in window.read()
    migrated=window.migrate_scales({'sceneScale':1.5,'waveScale':2})
    assert migrated=={'waveScale':2,'particleScale':1.5,'distortionScale':1.5}
    assert window.dials['grid'].hi==2048
    assert not window.dials['distortionScale'].live
    window.force_connect.setChecked(True)
    window.save()
    assert window.read()['forceConnect'] is True
    window.force_connect.setChecked(False)
    window.apply(window.read())
    assert window.force_connect.isChecked() and ns['lib'].settings['forceConnect']==1
    window.save_preset()
    assert window.presets[-1]['dials']['forceConnect'] is True
    window.view.sync_state=lambda:None
    window.ease_look=lambda _:None
    window.force_connect.setChecked(False)
    window.recall_preset(len(window.presets)-1)
    assert window.force_connect.isChecked()
    del window.presets[-1]['dials']['forceConnect']
    window.recall_preset(len(window.presets)-1)
    assert not window.force_connect.isChecked(),'old presets retain normal connections'
    print('PASS: connection override persists in settings and saved looks')
    window.force_points.setChecked(True)
    window.save()
    assert window.read()['forcePoints'] is True
    window.force_points.setChecked(False)
    window.apply(window.read())
    assert window.force_points.isChecked() and ns['lib'].settings['forcePoints']==1
    window.save_preset()
    assert window.presets[-1]['dials']['forcePoints'] is True
    window.force_points.setChecked(False)
    window.recall_preset(len(window.presets)-1)
    assert window.force_points.isChecked()
    del window.presets[-1]['dials']['forcePoints']
    window.recall_preset(len(window.presets)-1)
    assert not window.force_points.isChecked()
    print('PASS: point override persists in settings and looks; old looks default off')
    window.shared.directory.mkdir()
    window.shared.host='top'
    window.dials['grid'].set(2048,notify=True)
    window.save()
    peer=ns['SharedDials'](window.DEFAULTS,Path(tmp)/'air',window.shared.directory,'air')
    assert peer.read({'grid':640,'panel':False})['grid']==2048
    peer.save({'trailFill':8})
    window.apply(window.read())
    assert window.dials['trailFill'].get()==8
    edited=window.values();edited['trailFill']=2
    ns['DIALS'].write_text(ns['json'].dumps(edited))
    window.reload()
    assert peer.read({})['trailFill']==2,'local hand edits must update shared dials'
    assert 'panel' not in window.shared.records('top')
    print('PASS: shared tuning propagates through panel save/load and local hand edits')
    window.view.cleanup()
    window.deleteLater()
print('PASS: FPS controls, selector activation/sync, particle toggles while paused, new settings persistence, every advertised hotkey in menus')

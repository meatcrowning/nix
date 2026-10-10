#!/usr/bin/env python3
"""Only run inside unity-test.sh's private namespaces and scratch home."""
import json
import os
from pathlib import Path
import subprocess
import sys
assert os.environ['HOME'] == '/home/test'
assert os.environ['QT_QPA_PLATFORM'] == 'offscreen'
sys.path.insert(0, '/source/apps/oracle')
os.environ.update(DESK_SESSION='hypr', QT_QUICK_CONTROLS_STYLE='Basic', QT_QPA_PLATFORMTHEME='',
                  OLLAMA_HOST='http://127.0.0.1:9')
for name in ('CONFIG', 'SESSIONS', 'MEMORY', 'JOBS', 'TOOLS', 'SKILLS', 'AGENTS', 'IMAGES', 'AUDIO'):
    os.environ['ORACLE_' + name] = '/home/test/' + name.lower()
sys.argv.append('--selftest')
import main as M
import unity_engine as E
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from unityipc import Server

base = dict(XDG_CURRENT_DESKTOP='Unity', UNITY_QUANTAL_SESSION_DIR='/session')
yes = lambda _: '/runtime'
assert E.selected(base, [], yes)
for desktop in ('KDE', 'Hyprland', 'labwc', '', 'Unity7'):
    assert not E.selected(dict(base, XDG_CURRENT_DESKTOP=desktop), [], yes)
assert not E.selected(dict(XDG_CURRENT_DESKTOP='Unity'), [], yes)
assert not E.selected(base, ['--selftest'], yes)
assert not E.selected(base, ['--face=plasma'], yes)
assert not E.selected(base, [], lambda _: None)
# All live backend/notification seams are inert, even within this private net.
M.Ollama.refreshModels = lambda *_: None
M.Ollama.refreshModelInfo = lambda *_: None
M.Ollama.refreshMemories = lambda *_: None
M.Backend.pollStatus = lambda *_: None
M.Jobs.refresh = lambda *_: None
M.Jobs.notify = lambda *_: None
M.Ollama._choice_notify = lambda *_: None
app = QGuiApplication([])
app.setQuitOnLastWindowClosed(False)
assert app.platformName() == 'offscreen'
engine = E.Engine(M, app)
o = engine.ollama
o._models = ['fixture:latest']
o.modelsChanged.emit()
assert engine.snapshot()['model'] == 'fixture:latest'
submissions = []
def send(model, prompt, history, attachments, sid):
    submissions.append((model, prompt, json.loads(history), json.loads(attachments), sid))
    o._busy = True
    o.busyChanged.emit()
    QTimer.singleShot(30, lambda: o.replyThinking.emit('A little reasoning'))
    QTimer.singleShot(60, lambda: o.replyChunk.emit('Hello from the shared engine.'))
    def finish():
        o._busy = False
        o.busyChanged.emit()
        o.replyDone.emit()
    QTimer.singleShot(150, finish)
o.send = send
path = Path('/run/user/1000/chatter-test.sock')
server = Server(path, engine, app)
child = subprocess.Popen([os.environ['PACKAGE'] + '/bin/unity-quantal-runtime', '/usr/bin/python',
                          '/home/test/nix/apps/oracle/tools/unity-gtk-test.py', str(path)])
timer = QTimer()
timer.timeout.connect(lambda: app.quit() if child.poll() is not None else None)
timer.start(100)
QTimer.singleShot(25000, app.quit)
app.exec()
if child.poll() is None:
    child.terminate()
    child.wait(timeout=5)
    raise AssertionError('GTK fixture timed out')
assert child.returncode == 0, child.returncode
engine.close()
assert len(submissions) == 1, submissions
assert submissions[0][1] == 'A test message'
assert submissions[0][3][0]['name'] == 'attachment.txt'
unexpected = [w for w in engine.warnings if 'DeskMotion.qml: No such file' not in w]
assert not unexpected, unexpected
# A stopped stream retains its partial answer and refuses stale deletion.
engine.call('appendReplyRow', 2)
o._busy = True
o.busyChanged.emit()
o.replyChunk.emit('Partial reply')
engine.dispatch({'op': 'stop'})
assert not o.busy
assert engine.snapshot()['rows'][-1]['body'] == 'Partial reply'
assert not engine.snapshot()['rows'][-1]['streaming']
try:
    engine.dispatch({'op': 'delete', 'id': 'stale-id'})
    raise AssertionError('stale confirmation accepted')
except ValueError:
    pass
engine.close()
saved = list(Path('/home/test/sessions').glob('*.json'))
assert saved, 'conversation was not persisted'
print('PASS: Quantal-only gate, GTK socket actions, streaming, attachments, save/load, menu export')

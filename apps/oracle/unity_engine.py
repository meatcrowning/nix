"""Chatter's Quantal adapter; the existing QML state machine stays offscreen.

The GTK process only presents JSON and sends explicit actions. Model transport,
continuation, tools, attachments and session persistence have their usual owners.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile


def selected(env, argv, which=shutil.which):
    desktops = env.get('XDG_CURRENT_DESKTOP', '').lower().split(':')
    return ('unity' in desktops and bool(env.get('UNITY_QUANTAL_SESSION_DIR'))
            and which('unity-quantal-runtime') is not None
            and '--selftest' not in argv
            and not any(arg.startswith('--face=') for arg in argv))


class Engine:
    def __init__(self, module, app):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
        self.m, self.app = module, app
        self.ollama = module.Ollama()
        self.jobs = module.Jobs()
        self.ollama._jobs = self.jobs
        self.backend = module.Backend()
        self.backend.psSnapshot.connect(self.ollama.notePs)
        self.sessions = module.Sessions()
        self.qml = QQmlApplicationEngine()
        self.objects = dict(WalPalette=module.Palette(module.theme_source(module.PANEL_THEME)),
                            DeskStyle=module.DeskStyle(), Titlebar=module.Titlebar(enabled=False),
                            Ollama=self.ollama, Jobs=self.jobs, Backend=self.backend,
                            Sessions=self.sessions, Clip=module.Clip(), Md=module.MdFormat())
        context = self.qml.rootContext()
        for name, obj in self.objects.items():
            context.setContextProperty(name, obj)
        for name, value in dict(ollamaHost=module.OLLAMA, faceName='unity', oxygenFace=False).items():
            context.setContextProperty(name, value)
        self.warnings = []
        self.qml.warnings.connect(lambda errors: self.warnings.extend(e.toString() for e in errors))
        component = QQmlComponent(self.qml, QUrl.fromLocalFile(str(module.QML / 'theme/Theme.qml')))
        self.theme = component.create()
        if self.theme is None:
            raise RuntimeError(component.errorString())
        context.setContextProperty('Theme', self.theme)
        self.qml.load(QUrl.fromLocalFile(str(module.QML / 'Root.qml')))
        if not self.qml.rootObjects():
            raise RuntimeError('\n'.join(self.warnings))
        self.root = self.qml.rootObjects()[0]
        self.root.setProperty('visible', False)

    def call(self, method, *args):
        value = getattr(self.root, method)(*args)
        return value.toVariant() if hasattr(value, 'toVariant') else value

    def snapshot(self):
        state = json.loads(self.call('unitySnapshot'))
        o = self.ollama
        state.update(models=o.models, busy=o.busy, awaitingChoice=o.awaitingChoice,
                     assistantName=o.assistantName, showModelName=o.showModelName,
                     sessions=self.sessions.sessions, serverUp=self.backend.serverUp,
                     jobs=self.jobs.rows, prompts=o.promptPresets,
                     promptChoice=o.promptChoice, customPrompt=o.customPrompt,
                     contextUsed=o.contextUsed, contextMax=o.contextMax)
        return state

    def dispatch(self, request):
        op = request['op']
        if op == 'poll':
            pass
        elif op == 'send':
            text = request['text']
            if not isinstance(text, str):
                raise ValueError('Invalid message')
            if self.ollama.busy and not self.ollama.awaitingChoice:
                raise ValueError('Wait for the reply or press Stop.')
            if not self.root.property('model'):
                raise ValueError('Select a model first.')
            self.call('unitySend', text)
        elif op == 'model':
            if self.ollama.busy or request['value'] not in self.ollama.models:
                raise ValueError('Model unavailable while replying.')
            self.root.setProperty('model', request['value'])
            self.ollama.rememberModel(request['value'])
        elif op == 'session':
            self.sessions.open(request['id'])
        elif op == 'new':
            self.call('newSession')
        elif op == 'stop':
            self.call('stopReply')
        elif op == 'continue':
            self.call('continueReply', True)
        elif op == 'delete':
            # Guard a confirmation that became stale while its dialog was open.
            if request['id'] != self.root.property('sessionId'):
                raise ValueError('The selected conversation changed.')
            self.call('deleteCurrentSession')
        elif op == 'attach':
            from PySide6.QtCore import QUrl
            self.call('addAttachmentUrl', QUrl.fromLocalFile(request['path']).toString())
        elif op == 'detach':
            self.call('removeAttachment', int(request['index']))
        elif op == 'choice':
            self.ollama.answerChoice(request['id'], int(request['index']))
        elif op == 'stop-job':
            self.jobs.stop(request['id'])
        elif op == 'assistant-name':
            result = self.ollama._set_assistant_name(request['value'])
            if 'error' in result:
                raise ValueError(result['error'])
        elif op == 'show-model-name':
            self.ollama.setShowModelName(bool(request['value']))
        elif op == 'prompt':
            if request['value'] == 'custom':
                self.ollama.setCustomPrompt(request['text'])
            self.ollama.setPromptChoice(request['value'])
        elif op == 'refresh':
            self.ollama.refreshModels()
            self.sessions.refresh()
            self.backend.pollStatus()
        elif op in ('start-server', 'stop-server', 'unload'):
            {'start-server': self.backend.startServer, 'stop-server': self.backend.stopServer,
             'unload': self.backend.unloadModels}[op]()
        elif op == 'save':
            self.call('saveCurrent')
        else:
            raise ValueError('Unknown action: ' + str(op))
        return self.snapshot()

    def close(self):
        self.call('stopReply')
        self.call('saveCurrent')
        # Session saves are async QProcesses. Finish their callbacks before
        # destroying the engine; closing a window must retain partial replies.
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: loop.quit() if not self.sessions._procs else None)
        timer.start(20)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        if self.sessions._procs:
            raise RuntimeError('Conversation save did not finish before exit')


def run(module):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from unityipc import Server
    child_env = os.environ.copy()
    os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='',
                      QT_STYLE_OVERRIDE='', QT_QUICK_CONTROLS_STYLE='Basic', DESK_SESSION='hypr')
    os.environ.pop('DISPLAY', None)
    os.environ.pop('WAYLAND_DISPLAY', None)
    app = QGuiApplication(['chatter-engine'])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('oracle')
    engine = Engine(module, app)
    lease = module.BackendClientLease(engine.ollama._warden, 'ollama', app)
    with tempfile.TemporaryDirectory(prefix='chatter-', dir=child_env['XDG_RUNTIME_DIR']) as directory:
        path = Path(directory) / 'engine.sock'
        server = Server(path, engine, app)
        child = subprocess.Popen(['unity-quantal-runtime', '/usr/bin/python',
                                  str(Path(__file__).with_name('unity_frontend.py')), str(path)], env=child_env)
        lease.start(lambda ok, _why: None if ok else engine.backend.startServer())
        engine.dispatch({'op': 'refresh'})
        engine.ollama.refreshMemories()
        timer = QTimer(app)
        timer.timeout.connect(lambda: app.quit() if child.poll() is not None else None)
        timer.start(250)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: app.quit())
        try:
            code = app.exec()
        finally:
            lease.close()
            server.server.close()
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            engine.close()
        return child.returncode or code

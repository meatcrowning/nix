"""An isolated context for the same ParamsPane used by the current generation."""
import copy
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtQml import QQmlComponent, QQmlContext, qmlContext
from parameter_compare import snapshot


class ScratchPrefs(QObject):
    changed = Signal(str)

    def __init__(self, source, parent):
        super().__init__(parent)
        self.source, self.values = source, {}

    @Slot(str, result='QVariant')
    def get(self, key):
        return self.values.get(key, self.source.get(key))

    @Slot(str, 'QVariant')
    def set(self, key, value):
        self.values[key] = value.toVariant() if hasattr(value, 'toVariant') else value
        self.changed.emit(key)


def frozen(key, kind='QVariant'):
    return Property(kind, lambda self: self.values[key], constant=True)


class SnapshotApp(QObject):
    modelChanged = Signal()
    modeChanged = Signal()
    optionsChanged = Signal()
    editStateChanged = Signal()
    inputImageChanged = Signal()
    lastImageChanged = Signal()
    promptWritten = Signal(str, 'QVariant')
    layoutEdited = Signal(str, 'QVariantMap')
    for key in ('layoutSupport', 'isVideo', 'isEdit', 'supportsPatches', 'supportsLoras',
                'encoderControls', 'referenceImages', 'optionalEditImage', 'fixedSampling',
                'tagCompletion', 'editSampling', 'editPatches', 'editSharedImageSize',
                'editMultipleImages', 'separatePairing'):
        locals()[key] = frozen(key, bool)
    for key in ('selectedName', 'mode', 'nativeScheduler', 'familyLabel', 'inputImage',
                'lastImage', 'inputImageUrl', 'lastImageUrl', 'encoderName', 'vaeName'):
        locals()[key] = frozen(key, str)
    for key in ('samplers', 'schedulers', 'curves', 'outsideWindows', 'wildcardNames',
                'editExtraImages', 'encoderNames', 'vaeNames'):
        locals()[key] = frozen(key, 'QStringList')
    selectedIndex = frozen('selectedIndex', int)
    lastSeed = frozen('lastSeed')
    wildcardTooltips = frozen('wildcardTooltips', 'QVariantMap')
    layoutEditor = Property(QObject, lambda self: self.bridge, constant=True)
    generation = Property('QVariantMap', lambda self: self.state['settings'], constant=True)

    def __init__(self, state, parent):
        super().__init__(parent)
        from layout_qt import Bridge
        self.state = state
        self.values = dict(state, **state['flags'])
        self.values.update(selectedName=state['model'], wildcardNames=state['wildcards'],
                           inputImage=state['input'], lastImage=state['last'],
                           inputImageUrl=self.fileUrl(state['input']), lastImageUrl=self.fileUrl(state['last']),
                           editExtraImages=state['references'], separatePairing=state['separatePairing'],
                           encoderName=state['encoder'], vaeName=state['vae'],
                           encoderNames=[state['encoder']], vaeNames=[state['vae']])
        self.bridge = Bridge(self)
        self.bridge.edited.connect(self.layoutEdited)
        self.bridge.toolkit.generate_tags = lambda request, callback: callback(dict(error='Use the current settings panel to write.'))

    @Slot(result='QVariantList')
    def modes(self): return self.state['modes']

    @Slot(str, float, int, result='QVariantMap')
    def dims(self, aspect, megapixels, multiple):
        from registry import calc_dims
        w, h = calc_dims(aspect, megapixels, multiple)
        return dict(width=w, height=h)

    @Slot(result='QStringList')
    def familyIds(self): return []

    @Slot(str, result=str)
    def fileUrl(self, path): return QUrl.fromLocalFile(path).toString() if path else ''

    @Slot(float, result=int)
    def videoFrames(self, duration): return round(duration * self.state['settings']['fps'])

    @Slot(result='QVariant')
    def freshSeed(self): return self.lastSeed

    @Slot(str, 'QVariant')
    def writePrompt(self, identity, request):
        self.promptWritten.emit(identity, dict(error='Use the current settings panel to write.'))

    # The source identity/assets are fixed; never route these to the live app.
    @Slot(int)
    def selectModel(self, index): pass
    @Slot(str)
    def setMode(self, mode): pass
    @Slot(int, str)
    def assignFamily(self, index, family): pass
    @Slot(int, str)
    def overrideEncoder(self, index, name): pass
    @Slot(int, str)
    def overrideVae(self, index, name): pass
    @Slot(str)
    def setInputImage(self, path): pass
    @Slot(str)
    def setLastImage(self, path): pass
    @Slot(str)
    def addEditImage(self, path): pass
    @Slot(int, str)
    def setEditImage(self, index, path): pass
    @Slot(int)
    def removeEditImage(self, index): pass
    @Slot()
    def clearInputImage(self): pass
    @Slot()
    def clearLastImage(self): pass
    @Slot()
    def clearEditImages(self): pass


class Comparison(QObject):
    def __init__(self, ctl, host, params):
        super().__init__(host)
        self.item = None
        state = snapshot(params, ctl)
        if not state:
            return
        outer = qmlContext(host)
        self.context = QQmlContext(outer, self)
        self.app = SnapshotApp(state, self)
        self.prefs = ScratchPrefs(outer.contextProperty('Prefs'), self)
        self.models = type(ctl.models)(self)
        self.models.set_rows(state['models'])
        self.loras = type(ctl.loras)(self)
        self.loras._rows = [dict(dict(enabled=True, patches_clip=False, strength=1), **r) for r in state['loras']]
        self.choices = type(ctl.choices)(self)
        self.choices._rows = copy.deepcopy(state['choices'])
        for name, obj in [('App', self.app), ('Prefs', self.prefs), ('Models', self.models),
                          ('Loras', self.loras), ('LoraChoices', self.choices)]:
            self.context.setContextProperty(name, obj)
        self.component = QQmlComponent(outer.engine(), QUrl.fromLocalFile(str(Path(__file__).parent / 'qml/SnapshotParams.qml')), self)
        self.item = self.component.create(self.context)
        if self.item is None:
            raise RuntimeError('\n'.join(e.toString() for e in self.component.errors()))
        self.item.setParent(self)
        self.item.setParentItem(host)
        self.item.setWidth(host.width())
        self.item.setHeight(host.height())
        host.widthChanged.connect(self.resize)
        host.heightChanged.connect(self.resize)

    @Slot()
    def resize(self):
        self.item.setWidth(self.parent().width())
        self.item.setHeight(self.parent().height())

    def close(self):
        if self.item:
            self.parent().widthChanged.disconnect(self.resize)
            self.parent().heightChanged.disconnect(self.resize)
            self.item.setParentItem(None)
        self.setParent(None)
        self.deleteLater()

"""Qt Quick adapter for the shared inline layout editor; no secondary window."""
import base64
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QBuffer, QIODevice, QByteArray, QUrl
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtQml import qmlRegisterType
from PySide6.QtSvg import QSvgRenderer
import moss_layout as M
from layout_ui import LayoutUI


class Node(QObject):
    changed = Signal()

    def __init__(self, kind, title='', parent=None, options=None, callback=None, expand=False):
        super().__init__(parent)
        self._kind, self._title = kind, title
        self._options, self.callback = options or [], callback
        self._nodes, self._value = [], ''
        self._visible, self._enabled, self._expand = True, True, expand
        self._rows, self._selected = [], []
        if isinstance(parent, Node): parent._nodes.append(self)

    kind = Property(str, lambda s: s._kind, constant=True)
    title = Property(str, lambda s: s._title, notify=changed)
    options = Property('QVariantList', lambda s: s._options, constant=True)
    nodes = Property('QVariantList', lambda s: s._nodes, constant=True)
    value = Property('QVariant', lambda s: s._value, notify=changed)
    shown = Property(bool, lambda s: s._visible, notify=changed)
    enabled = Property(bool, lambda s: s._enabled, notify=changed)
    expand = Property(bool, lambda s: s._expand, constant=True)
    rows = Property('QVariantList', lambda s: s._rows, notify=changed)
    selected = Property('QStringList', lambda s: s._selected, notify=changed)
    swatches = Property('QStringList', lambda s: [v.strip() for v in str(s._value).split(',') if QColor(v.strip()).isValid()], notify=changed)

    @Slot('QVariant')
    def edit(self, value):
        self._value = value
        if self.callback: self.callback()
        self.changed.emit()

    @Slot()
    def activate(self):
        if self.callback: self.callback()

    @Slot(str, bool)
    def pick(self, identity, toggle):
        selected = list(self._selected) if toggle else []
        if identity in selected: selected.remove(identity)
        else: selected.append(identity)
        if self.callback: self.callback(selected)

    @Slot(str, str)
    def colour(self, value, replace):
        values = [v.strip() for v in str(self._value).split(',') if v.strip()]
        if replace: values = [value if v == replace else v for v in values]
        elif self._title == 'Text colour': values = [value]
        else: values.append(value)
        self.edit(', '.join(values))


class Toolkit(QObject):
    repaint = Signal()
    referenceRequested = Signal()
    cursorChanged = Signal()
    drawing = Property(bool, lambda s: s._drawing, notify=cursorChanged)

    def __init__(self):
        super().__init__()
        self.root = Node('column', parent=self)
        self._drawing = False

    def enable_widget(self, node, enabled):
        if node._enabled != enabled:
            node._enabled = enabled
            node.changed.emit()

    def show_widget(self, node, visible):
        node._visible = visible
        node.changed.emit()

    def drawing_cursor(self, _canvas, drawing):
        self._drawing = drawing
        self.cursorChanged.emit()

    def row(self, parent, expand=False): return Node('row', parent=parent, expand=expand)
    def toolbar(self, parent): return Node('toolbar', parent=parent)
    def spacer(self, parent): return Node('spacer', parent=parent, expand=True)
    def button_checked(self, button, checked): self.set(button, checked)
    def column(self, parent): return Node('inspector', parent=parent)
    def label(self, parent, text): return Node('label', text, parent)
    def set_label(self, node, text):
        if node._title != text:
            node._title = text
            node.changed.emit()
    def button(self, parent, title, callback): return Node('button', title, parent, callback=callback)
    def menu(self, parent, title): return Node('menu', title, parent)
    def menu_item(self, menu, title, callback): return Node('button', title, menu, callback=callback)
    def tabs(self, parent): return Node('tabs', parent=parent, expand=True)
    def tab(self, tabs, title): return Node('page', title, tabs)
    def field(self, parent, title, kind, options, callback):
        return Node(kind, title, parent, options=options, callback=callback)
    def get(self, field): return field._value
    def set(self, field, value):
        if field._value != value:
            field._value = value
            field.changed.emit()
    def sensitive(self, field, enabled): self.enable_widget(field, enabled)
    def visible(self, field, visible):
        if field._visible != visible: self.show_widget(field, visible)
    def region_list(self, parent, changed): return Node('list', parent=parent, callback=changed)
    def set_list(self, view, rows, selected):
        view._rows = [dict(identity=i, title=t) for i,t in rows]
        view._selected = list(selected)
        view._visible = bool(rows)
        view.changed.emit()
    def canvas(self, parent, editor): return Node('canvas', parent=parent, expand=True)
    def redraw(self, canvas): self.repaint.emit()
    def reference(self, path):
        image = QImage(path)
        if image.isNull(): raise ValueError('Cannot read image')
        image = image.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, 'PNG')
        return base64.b64encode(bytes(data)).decode('ascii')
    def choose_file(self):
        self.referenceRequested.emit()
        return ''
    def copy(self, text): QGuiApplication.clipboard().setText(text)
    def paste(self): return QGuiApplication.clipboard().text()


class Bridge(QObject):
    edited = Signal(str, 'QVariantMap')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_name = ''
        self.toolkit = Toolkit()
        self.editor = LayoutUI(self.toolkit, M.fresh(), self.publish)

    root = Property(QObject, lambda s: s.toolkit.root, constant=True)
    toolkitObject = Property(QObject, lambda s: s.toolkit, constant=True)

    def publish(self, doc):
        if self.model_name: self.edited.emit(self.model_name, doc)

    @Slot(str, 'QVariantMap', int, int, str)
    def load(self, model, document, width, height, caption):
        doc = M.resize(document, width, height) if document else M.fresh(width, height)
        doc['summary']['caption'] = caption
        self.model_name = model
        self.editor.load(doc)

    @Slot(str)
    def reference(self, url):
        path = QUrl(url).toLocalFile()
        if path: self.editor.command(lambda: self.editor.set_reference(path))

    @Slot(str, bool, bool, result=bool)
    def key(self, name, control, shift): return self.editor.key(name, control, shift)


class LayoutCanvas(QQuickPaintedItem):
    bridgeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge = None
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setAntialiasing(True)

    def set_bridge(self, bridge):
        if self._bridge is bridge: return
        if self._bridge:
            self._bridge.toolkit.repaint.disconnect(self.update)
        self._bridge = bridge
        if bridge: bridge.toolkit.repaint.connect(self.update)
        self.bridgeChanged.emit()
        self.update()

    bridge = Property(QObject, lambda s: s._bridge, set_bridge, notify=bridgeChanged)

    def paint(self, painter):
        if self._bridge:
            QSvgRenderer(self._bridge.editor.render(int(self.width()), int(self.height()))).render(painter)

    def mousePressEvent(self, event):
        self.forceActiveFocus()
        self._bridge.editor.pointer('press', event.position().x(), event.position().y(), bool(event.modifiers() & Qt.ShiftModifier))
        event.accept()

    def mouseMoveEvent(self, event):
        self._bridge.editor.pointer('move', event.position().x(), event.position().y())
        event.accept()

    def mouseReleaseEvent(self, event):
        self._bridge.editor.pointer('release', event.position().x(), event.position().y())
        event.accept()

    def keyPressEvent(self, event):
        from PySide6.QtGui import QKeySequence
        name = QKeySequence(event.key()).toString()
        name = {'Del': 'Delete', 'Backspace': 'BackSpace'}.get(name, name)
        if self._bridge.editor.key(name, bool(event.modifiers() & Qt.ControlModifier), bool(event.modifiers() & Qt.ShiftModifier)):
            event.accept()
        else: event.ignore()


qmlRegisterType(LayoutCanvas, 'PainterLayout', 1, 0, 'LayoutCanvas')

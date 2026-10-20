"""Qt Quick adapter for the shared inline layout editor; no secondary window."""
import base64
import math
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QBuffer, QIODevice, QByteArray, QUrl, QRectF, QPointF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QFont, QFontInfo, QFontMetricsF, QPainter, QPainterPath
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtQml import qmlRegisterType
from PySide6.QtSvg import QSvgRenderer
import moss_layout as M
from layout_ui import LayoutUI
from layout_cache import LayerCache


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
    # Hide the layout slot as well as the label; an empty child Label alone
    # still leaves its Loader's preferred height and inter-row spacing.
    shown = Property(bool, lambda s: s._visible and (s._kind != 'label' or bool(s._title)), notify=changed)
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
        self.model_name = ''
        self.tagger = None

    def tag_context(self): return self.model_name

    def generate_tags(self, request, callback):
        from tagger import Tagger
        if self.tagger is None:
            self.tagger = Tagger(self)
        self.tagger.start(request, callback)

    def enable_widget(self, node, enabled):
        if node._enabled != enabled:
            node._enabled = enabled
            node.changed.emit()

    def show_widget(self, node, visible):
        node._visible = visible
        node.changed.emit()

    def preview_colour(self, value):
        colour = QColor(value)
        return colour.name() if colour.isValid() else None

    def drawing_cursor(self, _canvas, drawing):
        self._drawing = drawing
        self.cursorChanged.emit()

    def row(self, parent, expand=False): return Node('row', parent=parent, expand=expand)
    def toolbar(self, parent): return Node('toolbar', parent=parent)
    def compact_fields(self, parent): return Node('compact', parent=parent)
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
    def tabs(self, parent):
        tabs = Node('tabs', parent=parent)
        tabs._value = 0
        tabs.callback = lambda: [self.show_widget(page, n == tabs._value) for n, page in enumerate(tabs._nodes)]
        return tabs
    def tab_body(self, tabs, parent): tabs.body = parent
    def tab(self, tabs, title):
        page = Node('page', title, tabs.body)
        page._visible = not tabs._nodes
        tabs._nodes.append(page)
        return page
    def field(self, parent, title, kind, options, callback):
        return Node(kind, title, parent, options=options, callback=callback, expand=kind.startswith("inline_"))
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
        self.toolkit.model_name = model
        self.editor.load(doc)

    @Slot(str)
    def reference(self, url):
        path = QUrl(url).toLocalFile()
        if path: self.editor.command(lambda: self.editor.set_reference(path))

    @Slot(str, bool, bool, result=bool)
    def key(self, name, control, shift): return self.editor.key(name, control, shift)


class LayoutCanvas(QQuickPaintedItem):
    bridgeChanged = Signal()
    previewFontChanged = Signal()
    inactiveColorChanged = Signal()
    selectedColorChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge = None
        self._layer_scale = 1
        def raster(svg, w, h):
            image = QImage(math.ceil(w * self._layer_scale), math.ceil(h * self._layer_scale), QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(self._layer_scale)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            QSvgRenderer(svg).render(painter, QRectF(0, 0, w, h))
            painter.end()
            return image
        self._layers = LayerCache(raster)
        self._preview_font = QFont()
        self._inactive_color = QColor('#bbbbbb')
        self._selected_color = QColor()
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.MiddleButton)
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

    def set_preview_font(self, font):
        if self._preview_font == font: return
        self._preview_font = QFont(font)
        self.previewFontChanged.emit()
        self.update()

    previewFont = Property(QFont, lambda s: s._preview_font, set_preview_font, notify=previewFontChanged)

    def set_inactive_color(self, colour):
        if colour != self._inactive_color:
            self._inactive_color = QColor(colour)
            self.inactiveColorChanged.emit()
            self.update()

    inactiveColor = Property(QColor, lambda s: s._inactive_color, set_inactive_color, notify=inactiveColorChanged)

    def set_selected_color(self, colour):
        if colour != self._selected_color:
            self._selected_color = QColor(colour)
            self.selectedColorChanged.emit()
            self.update()

    selectedColor = Property(QColor, lambda s: s._selected_color, set_selected_color, notify=selectedColorChanged)

    def paint(self, painter):
        if self._bridge:
            f = self._preview_font
            font = dict(inactive=self._inactive_color.name(), family=f.family(), size=QFontInfo(f).pixelSize(), weight=int(f.weight()),
                        style='italic' if f.italic() else 'normal', height=QFontMetricsF(f).height())
            if self._selected_color.isValid():
                font['selected'] = self._selected_color.name()
            editor = self._bridge.editor
            scale = painter.device().devicePixelRatioF()
            if scale != self._layer_scale:
                self._layer_scale = scale
                self._layers = LayerCache(self._layers.render, scale=scale)
            for svg, w, h, x, y, clip in editor.render(int(self.width()), int(self.height()), font, layers=True):
                painter.save()
                if clip:
                    painter.setClipRect(QRectF(*editor.rect))
                    if isinstance(clip, dict):
                        for hole in clip['holes']:
                            path = QPainterPath()
                            path.setFillRule(Qt.OddEvenFill)
                            path.addRect(QRectF(*editor.rect))
                            path.addRect(QRectF(*hole))
                            painter.setClipPath(path, Qt.IntersectClip)
                painter.drawImage(QPointF(x, y), self._layers.get(svg, w, h))
                painter.restore()

    def mousePressEvent(self, event):
        self.forceActiveFocus()
        if event.button() == Qt.MiddleButton:
            self._bridge.editor.pan_pointer('press', event.position().x(), event.position().y())
            event.accept()
            return
        self._bridge.editor.pointer('press', event.position().x(), event.position().y(), bool(event.modifiers() & Qt.ShiftModifier))
        event.accept()

    def mouseMoveEvent(self, event):
        if self._bridge.editor.panning:
            self._bridge.editor.pan_pointer('move', event.position().x(), event.position().y())
            event.accept()
            return
        self._bridge.editor.pointer('move', event.position().x(), event.position().y())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._bridge.editor.pan_pointer('release', event.position().x(), event.position().y())
            event.accept()
            return
        self._bridge.editor.pointer('release', event.position().x(), event.position().y())
        event.accept()

    def wheelEvent(self, event):
        from kinetic import DETENT, ANGLE_PER_PIXEL, is_wheel_detent
        px, angle = event.pixelDelta(), event.angleDelta()
        steps = angle.y() / DETENT if is_wheel_detent(px, angle) else (px.y() if not px.isNull() else angle.y() / ANGLE_PER_PIXEL) / 40
        self._bridge.editor.zoom_at(event.position().x(), event.position().y(), steps)
        event.accept()

    def keyPressEvent(self, event):
        from PySide6.QtGui import QKeySequence
        name = QKeySequence(event.key()).toString()
        name = {'Del': 'Delete', 'Backspace': 'BackSpace'}.get(name, name)
        if self._bridge.editor.key(name, bool(event.modifiers() & Qt.ControlModifier), bool(event.modifiers() & Qt.ShiftModifier)):
            event.accept()
        else: event.ignore()


qmlRegisterType(LayoutCanvas, 'PainterLayout', 1, 0, 'LayoutCanvas')

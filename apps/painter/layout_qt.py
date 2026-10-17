"""Native Qt Widgets adapter; standalone to work with Painter's QGuiApplication."""
import base64
import json
import sys
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from PySide6.QtSvg import QSvgRenderer
from layout_ui import LayoutUI


class Toolkit:
    def __init__(self):
        self.window = W.QDialog()
        self.window.setWindowTitle('MOSS Layout — Painter')
        self.window.setWindowIcon(G.QIcon.fromTheme('painter'))
        self.window.resize(1100, 800)
        self.root = W.QVBoxLayout(self.window)

    def enable_widget(self, widget, enabled): widget.setEnabled(enabled)
    def close(self): self.window.close()

    def row(self, parent, expand=False):
        row = W.QHBoxLayout()
        parent.addLayout(row, 1 if expand else 0)
        return row

    def column(self, parent):
        box = W.QWidget()
        box.setFixedWidth(380)
        parent.addWidget(box)
        return W.QVBoxLayout(box)

    def label(self, parent, text):
        label = W.QLabel(text)
        label.setWordWrap(True)
        parent.addWidget(label)
        return label

    def set_label(self, label, text): label.setText(text)

    def button(self, parent, title, callback):
        button = W.QPushButton(title)
        button.setAutoDefault(False)
        button.clicked.connect(lambda: callback())
        parent.addWidget(button)
        return button

    def tabs(self, parent):
        tabs = W.QTabWidget()
        parent.addWidget(tabs, 1)
        return tabs

    def tab(self, tabs, title):
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAlwaysOff)
        box = W.QWidget()
        layout = W.QVBoxLayout(box)
        layout.setAlignment(C.Qt.AlignTop)
        scroll.setWidget(box)
        tabs.addTab(scroll, title)
        return layout

    def field(self, parent, title, kind, options, callback):
        box = W.QWidget()
        layout = W.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        parent.addWidget(box)
        if kind != 'check': self.label(layout, title)
        swatches = None
        if kind == 'combo':
            control = W.QComboBox()
            for value in options: control.addItem(value or 'Unspecified', value)
            control.currentIndexChanged.connect(lambda: callback())
        elif kind == 'check':
            control = W.QCheckBox(title)
            control.toggled.connect(lambda: callback())
        elif kind == 'number':
            control = W.QDoubleSpinBox()
            control.setRange(options[0], options[1])
            control.setSingleStep(options[2])
            control.setDecimals(2 if options[2] < 1 else 0)
            control.valueChanged.connect(lambda: callback())
        elif kind == 'text':
            control = W.QPlainTextEdit()
            control.setFixedHeight(95)
            control.textChanged.connect(callback)
        else:
            control = W.QLineEdit()
            control.textChanged.connect(lambda: callback())
        layout.addWidget(control)
        if kind == 'palette':
            swatches = self.row(layout)
            def picked():
                colour = W.QColorDialog.getColor(parent=self.window)
                if colour.isValid():
                    old = control.text().strip()
                    control.setText(colour.name() if title == 'Text colour' or not old else old + ', ' + colour.name())
            self.button(layout, 'Choose colour…', picked)
        field = kind, control, box, swatches
        if kind == 'palette': control.textChanged.connect(lambda: self.swatches(field))
        return field

    def swatches(self, field):
        layout = field[3]
        while layout.count():
            child = layout.takeAt(0).widget()
            child.deleteLater()
        for value in field[1].text().split(',')[:12]:
            colour = G.QColor(value.strip())
            if not colour.isValid(): continue
            button = W.QPushButton()
            pixmap = G.QPixmap(20, 20)
            pixmap.fill(colour)
            button.setIcon(G.QIcon(pixmap))
            button.setToolTip(value.strip())
            button.setFixedSize(30, 28)
            def replace(old=value.strip(), current=colour):
                c = W.QColorDialog.getColor(current, self.window)
                if c.isValid(): field[1].setText(', '.join(c.name() if v.strip() == old else v.strip() for v in field[1].text().split(',')))
            button.clicked.connect(lambda _checked=False, fn=replace: fn())
            layout.addWidget(button)

    def get(self, field):
        kind, control = field[:2]
        if kind == 'check': return control.isChecked()
        if kind == 'number': return control.value()
        if kind == 'combo': return control.currentData() or ''
        if kind == 'text': return control.toPlainText()
        return control.text()

    def set(self, field, value):
        kind, control = field[:2]
        if kind == 'check': control.setChecked(bool(value))
        elif kind == 'number': control.setValue(float(value or 0))
        elif kind == 'combo': control.setCurrentIndex(control.findData(value))
        elif kind == 'text': control.setPlainText(value or '')
        else: control.setText(value or '')

    def sensitive(self, field, enabled): field[2].setEnabled(enabled)
    def visible(self, field, visible): field[2].setVisible(visible)

    def region_list(self, parent, changed):
        view = W.QListWidget()
        view.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        view.setFixedHeight(140)
        view.itemSelectionChanged.connect(lambda: changed([i.data(C.Qt.UserRole) for i in view.selectedItems()]))
        parent.addWidget(view)
        return view

    def set_list(self, view, rows, selected):
        view.clear()
        for identity, title in rows:
            item = W.QListWidgetItem(title, view)
            item.setData(C.Qt.UserRole, identity)
            item.setSelected(identity in selected)

    def canvas(self, parent, editor):
        class Canvas(W.QWidget):
            def keyPressEvent(self, e):
                name = G.QKeySequence(e.key()).toString()
                name = {'Del': 'Delete', 'Backspace': 'BackSpace'}.get(name, name)
                if len(name) == 1: name = name.lower()
                if not editor.key(name, bool(e.modifiers() & C.Qt.ControlModifier), bool(e.modifiers() & C.Qt.ShiftModifier)):
                    super().keyPressEvent(e)
            def paintEvent(self, _event):
                painter = G.QPainter(self)
                QSvgRenderer(editor.render(self.width(), self.height())).render(painter)
                painter.end()
            def mousePressEvent(self, e):
                self.setFocus()
                if e.button() == C.Qt.LeftButton: editor.pointer('press', e.position().x(), e.position().y(), bool(e.modifiers() & C.Qt.ShiftModifier))
            def mouseMoveEvent(self, e):
                if e.buttons() & C.Qt.LeftButton: editor.pointer('move', e.position().x(), e.position().y())
            def mouseReleaseEvent(self, e):
                if e.button() == C.Qt.LeftButton: editor.pointer('release', e.position().x(), e.position().y())
        canvas = Canvas()
        canvas.setFocusPolicy(C.Qt.StrongFocus)
        canvas.setMinimumSize(400, 400)
        parent.addWidget(canvas, 1)
        return canvas

    def redraw(self, canvas): canvas.update()

    def reference(self, path):
        image = G.QImage(path)
        if image.isNull(): raise ValueError('Cannot read image')
        image = image.scaled(1600, 1600, C.Qt.KeepAspectRatio, C.Qt.SmoothTransformation)
        data = C.QByteArray()
        buffer = C.QBuffer(data)
        buffer.open(C.QIODevice.WriteOnly)
        image.save(buffer, 'PNG')
        return base64.b64encode(bytes(data)).decode('ascii')

    def choose_file(self): return W.QFileDialog.getOpenFileName(self.window, 'Reference underlay', '', 'Images (*.png *.jpg *.jpeg *.webp *.bmp)')[0]
    def copy(self, text): W.QApplication.clipboard().setText(text)
    def paste(self): return W.QApplication.clipboard().text()


def run():
    app = W.QApplication(sys.argv)
    app.setApplicationName('painter')
    toolkit = Toolkit()
    doc = json.loads(sys.stdin.readline())
    def accepted(result):
        print(json.dumps(result, ensure_ascii=False), flush=True)
    editor = LayoutUI(toolkit, doc, accepted)
    toolkit.window.show()
    editor.region_visibility()
    return app.exec()


if __name__ == '__main__':
    sys.exit(run())

#!/usr/bin/env python3
"""Export the active KDE widget style's horizontal splitter without a window."""
import base64
import json
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.pop('DISPLAY', None)
os.environ.pop('WAYLAND_DISPLAY', None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyleFactory, QStyleOption
from browsersurface import browser_png
from kdetheme import kde_widget_style
from oxygenstyle import read_oxygen

app = QApplication([])
assert app.platformName() == 'offscreen'
style = QStyleFactory.create(kde_widget_style())
if style is None:
    raise SystemExit('KDE widget style is unavailable')
app.setStyle(style)
height = style.pixelMetric(QStyle.PM_SplitterWidth)
hit_height = height
if style.objectName().lower() == 'oxygen':
    oxygen = read_oxygen()
    if oxygen['SplitterProxyEnabled']:
        hit_height = max(height, oxygen['SplitterProxyWidth'])
result = {'height': height, 'hitHeight': hit_height}
for name, hover in [('normal', False), ('hover', True)]:
    image = QImage(220, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    option = QStyleOption()
    option.rect = QRect(0, 0, image.width(), height)
    option.palette = app.palette()
    option.state = QStyle.State_Enabled | QStyle.State_Active
    if hover:
        option.state |= QStyle.State_MouseOver
    painter = QPainter(image)
    style.drawControl(QStyle.CE_Splitter, option, painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    result[name] = 'data:image/png;base64,' + base64.b64encode(browser_png(bytes(buffer.data()))).decode()
print(json.dumps(result))

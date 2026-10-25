"""Labeled 2×2 exports using the same thermal masks as the viewer."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QRect, QSaveFile, QIODevice
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics


def save_grid(source, data, tokens, folder):
    from moss_inspect import token_mask
    original = QImage(source)
    if original.isNull():
        raise ValueError('Cannot read the original output')
    if not folder:
        raise ValueError('Pictures folder is unavailable')
    width, height = original.width(), original.height()
    font = QFont('sans-serif')
    font.setPixelSize(max(16, min(48, width // 35)))
    metrics = QFontMetrics(font)
    padding = max(12, width // 80)
    header = metrics.height() + padding * 2
    gap = padding
    canvas = QImage(width * 2 + gap * 3, (height + header) * 2 + gap * 3, QImage.Format_RGB32)
    if canvas.isNull():
        raise ValueError('Not enough memory for the comparison')
    canvas.fill(QColor('#15191f'))
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setFont(font)
        painter.setPen(QColor('#f4f5f7'))
        labels = ['Original', 'All tokens · relative association'] + ['Token ' + t['label'] for t in tokens]
        indices = [None, -1] + [t['index'] for t in tokens]
        for i, (label, token) in enumerate(zip(labels, indices)):
            x = gap + (i % 2) * (width + gap)
            y = gap + (i // 2) * (height + header + gap)
            painter.drawText(QRect(x + padding, y, width - padding * 2, header),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             metrics.elidedText(label, Qt.ElideRight, width - padding * 2))
            rect = QRect(x, y + header, width, height)
            painter.drawImage(rect, original)
            if token is not None:
                painter.drawImage(rect, token_mask(*data, token))
    finally:
        painter.end()
    # Retain complete labels even if a very long token is elided in the header.
    canvas.setText('Description', '\n'.join(labels))
    destination = Path(folder)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ('painter-heatmap-%s-%s.png' % (datetime.now().strftime('%Y%m%d-%H%M%S'), uuid4().hex[:8]))
    output = QSaveFile(str(path))
    if not output.open(QIODevice.WriteOnly) or not canvas.save(output, 'PNG') or not output.commit():
        raise OSError(output.errorString())
    return path

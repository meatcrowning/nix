"""Prompt-word peak connectors for exported association maps."""
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen, QPainterPath, QPainter
from PySide6.QtCore import Qt, QPointF, QRectF
import moss_data
import moss_rank
COLORS = ('#ffcc44', '#42dbff', '#ff70ce', '#b1f573', '#ff9860', '#c6a0ff')

def draw(p, rect, words):
    wd, wp = words
    prompt = wd.get('prompt', '')
    try:
        lo, hi = moss_data.json_value_span(prompt, ('summary', 'caption'))
        lo, hi = (lo + 1, hi - 1)
    except (ValueError, IndexError):
        lo, hi = (0, len(prompt))
    items = [t for t in wd['tokens'] if t['start'] < hi and t['end'] > lo and moss_rank.WORD.search(t['text'])]
    if not items:
        return []
    w, h = (rect.width(), rect.height())
    p.save()
    p.setClipRect(rect)
    p.translate(rect.x(), rect.y())
    margin = 13
    spacing = (h - 2 * margin) / len(items)
    font = QFont('sans-serif')
    font.setPixelSize(max(1, min(17, int(spacing * 0.77))))
    font.setBold(True)
    fm = QFontMetrics(font)
    # Keep individual backings separated even for a long scene caption.
    while fm.height() > spacing - 2 and font.pixelSize() > 1:
        font.setPixelSize(font.pixelSize() - 1)
        fm = QFontMetrics(font)
    label_height = min(fm.height() + 4, max(1, spacing - 2))
    entries = []
    mw, mh = (wd['width'], wd['height'])
    area = mw * mh
    rx, ry = moss_rank.neighborhood(mw, mh, 1)
    for row, token in enumerate(items):
        plane = wp[token['index'] * area:(token['index'] + 1) * area]
        peak = max(plane)
        candidates = [i for i, v in enumerate(plane) if v == peak]
        table = moss_rank.summed_area(plane, mw, mh)

        def score(i):
            xx, yy = (i % mw, i // mw)
            a, b = (max(0, xx - rx), max(0, yy - ry))
            c, d = (min(mw, xx + rx + 1), min(mh, yy + ry + 1))
            return moss_rank.area_sum(table, mw, a, b, c, d) / ((c - a) * (d - b))
        best = max(map(score, candidates))
        candidates = [i for i in candidates if abs(score(i) - best) < 1e-09]
        cx = sum((i % mw for i in candidates)) / len(candidates)
        cy = sum((i // mw for i in candidates)) / len(candidates)
        chosen = min(candidates, key=lambda i: ((i % mw - cx) ** 2 + (i // mw - cy) ** 2, i))
        point = QPointF((chosen % mw + 0.5) * w / mw, (chosen // mw + 0.5) * h / mh)
        y = margin + row * spacing + spacing / 2
        entries.append(dict(token=token, text=token['text'], y=y, width=fm.horizontalAdvance(token['text']), point=point))
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(font)
    for i, e in enumerate(entries):
        color = QColor(COLORS[i % 6])
        color.setAlpha(150)
        a = QPointF(margin + e['width'] + 7, e['y'])
        b = e['point']
        p.setPen(QPen(QColor(0, 0, 0, 65), 2.3))
        p.drawLine(a, b)
        p.setPen(QPen(color, 1.1))
        p.drawLine(a, b)
        color.setAlpha(235)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(b, 3.2, 3.2)
    for i, e in enumerate(entries):
        p.fillRect(QRectF(margin - 4, e['y'] - label_height / 2,
                          e['width'] + 8, label_height), QColor('#e615191f'))
        path = QPainterPath()
        path.addText(QPointF(margin, e['y'] + (fm.ascent() - fm.descent()) / 2), font, e['text'])
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS[i % 6]))
        p.drawPath(path)
    p.restore()
    return [dict(text=e['text'], source_indices=e['token']['source_indices'], point=[e['point'].x() / w, e['point'].y() / h]) for e in entries]

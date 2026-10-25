"""Labeled 3×2 exports using the same thermal masks as the viewer."""
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QSaveFile, QIODevice
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPen
import moss_data
import moss_rank


COLORS = ('#ffcc44', '#42dbff', '#ff70ce', '#b1f573')


def ranked_masks(data, ranking):
    from moss_inspect import token_mask
    doc, pixels = data
    w, h = doc['width'], doc['height']
    eligible = dict(doc, tokens=moss_rank.content_tokens(doc))
    eligible['_aggregate'] = moss_data.aggregate(eligible, pixels)
    hot = token_mask(eligible, pixels, -1)
    for y in range(h):
        for x in range(w):
            edge = max((max(0, min(1, (a['side']/2 + 1.5 - max(abs(x-a['x']), abs(y-a['y']))) / 2))
                        for a in ranking['areas']), default=0)
            color = hot.pixelColor(x, y)
            color.setAlpha(round(color.alpha() * edge))
            hot.setPixelColor(x, y, color)
    focused = dict(doc, tokens=[t['token'] for t in ranking['focused']])
    focused['_aggregate'] = moss_data.aggregate(focused, pixels)
    focus = token_mask(focused, pixels, -1) if focused['tokens'] else QImage()
    return hot, focus


def annotations(painter, rect, ranking, doc, font, padding, focused=False):
    """Token labels only; ranking methodology stays in PNG metadata."""
    painter.save()
    painter.setClipRect(rect)
    small = QFont(font)
    small.setPixelSize(max(12, round(font.pixelSize() * .8)))
    painter.setFont(small)
    metrics = QFontMetrics(small)
    for i, item in enumerate(ranking):
        color = QColor(COLORS[i])
        cx = rect.x() + (item['x'] + .5) * rect.width() / doc['width']
        cy = rect.y() + (item['y'] + .5) * rect.height() / doc['height']
        label = item['token'].get('display', item['token']['text'].strip().replace('\n', '↵'))
        label_width = min(rect.width() - 2*padding, metrics.horizontalAdvance(label) + padding*2)
        label_height = metrics.height() + padding
        painter.setPen(QPen(color, max(2, rect.width()/450)))
        painter.setBrush(Qt.NoBrush)
        if focused:
            box = QRect(rect.x()+padding, rect.y()+padding+i*(label_height+padding//2), label_width, label_height)
            painter.drawLine(QPointF(box.right(), box.center().y()), QPointF(cx, cy))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy), 4, 4)
        else:
            bw = item['side'] * rect.width() / doc['width']
            bh = item['side'] * rect.height() / doc['height']
            outline = QRectF(cx-bw/2, cy-bh/2, bw, bh)
            painter.drawRoundedRect(outline, padding/2, padding/2)
            bx = max(rect.x(), min(rect.right()-label_width, round(outline.x())))
            by = max(rect.y(), round(outline.y())-label_height)
            box = QRect(bx, by, label_width, label_height)
        painter.fillRect(box, QColor('#e615191f'))
        painter.setPen(color)
        painter.drawText(box.adjusted(padding//2, 0, -padding//2, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         metrics.elidedText(label, Qt.ElideRight, max(0, label_width-padding)))
    painter.restore()


def add_title(image, model):
    """Prepend a single title row, preserving every existing comparison pixel."""
    title = '%s — token association heatmaps' % (Path(model).stem if model else 'Unknown model')
    font = QFont('sans-serif')
    font.setPixelSize(max(16, min(72, image.width() // 65)))
    font.setBold(True)
    padding = max(12, image.width() // 150)
    metrics = QFontMetrics(font)
    while metrics.horizontalAdvance(title) > image.width()-padding*2 and font.pixelSize() > 8:
        font.setPixelSize(font.pixelSize()-1)
        metrics = QFontMetrics(font)
    height = metrics.height() + padding*2
    result = QImage(image.width(), image.height()+height, QImage.Format_RGB32)
    if result.isNull():
        raise ValueError('Not enough memory for the comparison title')
    result.fill(QColor('#15191f'))
    painter = QPainter(result)
    painter.drawImage(0, height, image)
    painter.setFont(font)
    painter.setPen(QColor('#f4f5f7'))
    painter.drawText(QRect(padding, 0, image.width()-padding*2, height), Qt.AlignVCenter | Qt.AlignLeft, title)
    painter.end()
    for key in image.textKeys():
        result.setText(key, image.text(key))
    result.setText('Title', title)
    result.setText('PainterTitleHeight', str(height))
    return result


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
    words, lookup = moss_rank.word_maps(*data)
    selected = [lookup[token['index']] for token in tokens]
    ranking = moss_rank.rank(*words)
    hot, focus = ranked_masks(words, ranking)
    canvas = QImage(width * 3 + gap * 4, (height + header) * 2 + gap * 3, QImage.Format_RGB32)
    if canvas.isNull():
        raise ValueError('Not enough memory for the comparison')
    canvas.fill(QColor('#15191f'))
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(font)
        painter.setPen(QColor('#f4f5f7'))
        labels = ['Original', 'All tokens · relative association', 'Hottest areas',
                  moss_rank.word_label(selected[0]), moss_rank.word_label(selected[1]), 'Most focused tokens']
        masks = [QImage(), token_mask(*data, -1), hot,
                 token_mask(*words, selected[0]['index']), token_mask(*words, selected[1]['index']), focus]
        for i, (label, mask) in enumerate(zip(labels, masks)):
            x = gap + (i % 3) * (width + gap)
            y = gap + (i // 3) * (height + header + gap)
            painter.drawText(QRect(x + padding, y, width - padding * 2, header),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             metrics.elidedText(label, Qt.ElideRight, max(0, width - padding * 2)))
            rect = QRect(x, y + header, width, height)
            painter.drawImage(rect, original)
            if not mask.isNull():
                painter.drawImage(rect, mask)
            if i in (2, 5):
                items = ranking['areas' if i == 2 else 'focused']
                annotations(painter, rect, items, data[0], font, padding, focused=i == 5)
                if not items:
                    painter.drawText(rect.adjusted(padding, padding, -padding, -padding),
                                     Qt.AlignTop | Qt.AlignLeft, 'No eligible token maps')
    finally:
        painter.end()
    # Keep full labels, token identities, scores and methods off the artwork.
    canvas.setText('Description', '\n'.join(labels))
    canvas.setText('PainterWordGrouping', json.dumps(dict(source=str(source), selected=selected,
        words=words[0]['tokens'], method='Mean of saved normalized token planes per word occurrence; '
        'original all-token reference retained. No additional per-word contrast stretch.'), ensure_ascii=False))
    ranking['method'] = ('Saved normalized associations, not absolute activity. English function words and punctuation excluded; '
                         'layout rankings use descriptive string values only, excluding structural fields and coordinates; '
                         'token pieces averaged per word occurrence before ranking; '
                         'up to 7x7 neighborhood means, centers separated by up to 12 cells; '
                         'area labels maximize eligible-token mean in that neighborhood; '
                         'repeated words, subpieces, plurals and close spelling variants deduplicated per panel; '
                         'focus minimizes RMS radius weighted by max(score-.70,0)^2. Up to four per panel.')
    canvas.setText('PainterRanking', json.dumps(ranking, ensure_ascii=False))
    import pngmeta
    try:
        metadata = json.loads(pngmeta.read_text_path(source).get('painter', '{}'))
        model = metadata.get('model', '')
    except (ValueError, TypeError, AttributeError):
        model = ''
    canvas = add_title(canvas, model)
    destination = Path(folder)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ('painter-heatmap-%s-%s.png' % (datetime.now().strftime('%Y%m%d-%H%M%S'), uuid4().hex[:8]))
    output = QSaveFile(str(path))
    if not output.open(QIODevice.WriteOnly) or not canvas.save(output, 'PNG') or not output.commit():
        raise OSError(output.errorString())
    return path

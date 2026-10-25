"""Labeled 3×2 exports using the same thermal masks as the viewer."""
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QSaveFile, QIODevice
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPen, QTextLayout, QTextOption
import moss_data
import moss_rank


COLORS = ('#ffcc44', '#42dbff', '#ff70ce', '#b1f573')


def scene_prompt(document):
    prompt = document.get('prompt', '')
    try:
        layout = json.loads(prompt)
        if isinstance(layout, dict) and isinstance(layout.get('summary'), dict):
            return str(layout['summary'].get('caption', ''))
    except ValueError:
        pass
    return prompt


def original_header(painter, rect, prompt, font, padding):
    title = 'Original output'
    metrics = QFontMetrics(font)
    title_width = metrics.horizontalAdvance(title)
    painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, metrics.elidedText(title, Qt.ElideRight, max(0, rect.width())))
    remaining = rect.adjusted(title_width+padding, 0, 0, 0)
    if remaining.width() < 20:
        return
    small = QFont(font)
    small.setPixelSize(max(10, round(font.pixelSize()*.55)))
    small_metrics = QFontMetrics(small)
    prompt = ' '.join(prompt.split())
    layout = QTextLayout(prompt, small)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    if line.isValid():
        line.setLineWidth(remaining.width())
        split = len(prompt.encode('utf-16-le')[:line.textLength()*2].decode('utf-16-le'))
    else:
        split = 0
    layout.endLayout()
    lines = [prompt[:split].rstrip(), small_metrics.elidedText(prompt[split:].lstrip(), Qt.ElideRight, remaining.width())]
    painter.save()
    painter.setFont(small)
    y = remaining.y() + (remaining.height()-2*small_metrics.height())//2
    for text in lines:
        painter.drawText(QRect(remaining.x(), y, remaining.width(), small_metrics.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        y += small_metrics.height()
    painter.restore()


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


def ranked_header(painter, rect, label, entries, font, padding):
    """Fit complete scored words in two small lines beside the panel title."""
    metrics = QFontMetrics(font)
    painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft,
                     metrics.elidedText(label, Qt.ElideRight, max(0, rect.width())))
    remaining = rect.adjusted(metrics.horizontalAdvance(label)+padding, 0, 0, 0)
    small = QFont(font)
    small.setPixelSize(max(10, round(font.pixelSize()*.55)))
    metrics = QFontMetrics(small)
    lines, shown, line = ['', ''], [], 0
    for entry in entries:
        text = '%s %.1f%%' % (entry['token']['text'], entry['percentage'])
        proposed = (lines[line]+' · ' if lines[line] else '')+text
        if metrics.horizontalAdvance(proposed) > remaining.width():
            line += 1
            if line >= 2:
                break
            proposed = text
        if metrics.horizontalAdvance(proposed) > remaining.width():
            break
        lines[line] = proposed
        shown.append(entry)
    painter.save()
    painter.setFont(small)
    y = remaining.y()+(remaining.height()-2*metrics.height())//2
    for text in lines:
        painter.drawText(QRect(remaining.x(), y, max(0, remaining.width()), metrics.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, text)
        y += metrics.height()
    painter.restore()
    return dict(title=label, lines=lines, entries=shown)


def annotations(painter, rect, ranking, doc, font, padding, focused=False):
    """Word labels with half-size percentages; methods stay in PNG metadata."""
    painter.save()
    painter.setClipRect(rect)
    small = QFont(font)
    small.setPixelSize(max(12, round(font.pixelSize() * .8)))
    painter.setFont(small)
    metrics = QFontMetrics(small)
    percent_font = QFont(small)
    percent_font.setPixelSize(max(1, round(small.pixelSize()*.5)))
    percent_metrics = QFontMetrics(percent_font)
    for i, item in enumerate(ranking):
        color = QColor(COLORS[i])
        cx = rect.x() + (item['x'] + .5) * rect.width() / doc['width']
        cy = rect.y() + (item['y'] + .5) * rect.height() / doc['height']
        label = item['token'].get('display', item['token']['text'].strip().replace('\n', '↵'))
        percent = ('%.1f%% radius' if focused else '%.1f%% assoc.') % item['percentage']
        percent_width = percent_metrics.horizontalAdvance(percent)
        space = metrics.horizontalAdvance(' ')
        label_width = min(rect.width() - 2*padding, metrics.horizontalAdvance(label) + space + percent_width + padding*2)
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
        label = metrics.elidedText(label, Qt.ElideRight, max(0, label_width-padding-space-percent_width))
        baseline = box.y()+(box.height()-metrics.height())/2+metrics.ascent()
        painter.setFont(small)
        painter.drawText(QPointF(box.x()+padding//2, baseline), label)
        painter.setFont(percent_font)
        painter.drawText(QPointF(box.x()+padding//2+metrics.horizontalAdvance(label)+space, baseline), percent)
    painter.restore()


def add_title(image, model):
    """Prepend a single title row, preserving every existing comparison pixel."""
    title = '%s — token association heatmaps v2' % (Path(model).stem if model else 'Unknown model')
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
    data = (dict(data[0], _aggregate=moss_data.descriptive_aggregate(*data)), data[1])
    words, lookup = moss_rank.word_maps(*data)
    selected = [lookup[token['index']] for token in tokens]
    full_ranking = moss_rank.rank(*words, limit=None, image_size=(width, height))
    ranking = {key: items[:4] for key, items in full_ranking.items()}
    all_tokens, related = moss_rank.association_lists(*words, selected, data[0]['_aggregate'])
    lists = {1: all_tokens, 2: moss_rank.unique_entries(full_ranking['areas'], ranking['areas']),
             3: related[0], 4: related[1],
             5: moss_rank.unique_entries(full_ranking['focused'], ranking['focused'])}
    expanded = {}
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
        labels = ['Original output', 'All tokens · relative association', 'Hottest areas',
                  moss_rank.word_label(selected[0]), moss_rank.word_label(selected[1]), 'Most focused tokens']
        masks = [QImage(), token_mask(*data, -1), hot,
                 token_mask(*words, selected[0]['index']), token_mask(*words, selected[1]['index']), focus]
        for i, (label, mask) in enumerate(zip(labels, masks)):
            x = gap + (i % 3) * (width + gap)
            y = gap + (i // 3) * (height + header + gap)
            heading = QRect(x + padding, y, width - padding * 2, header)
            if i == 0:
                original_header(painter, heading, scene_prompt(data[0]), font, padding)
            else:
                expanded[str(i)] = ranked_header(painter, heading, label, lists[i], font, padding)
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
    canvas.setText('PainterComparisonPrompt', scene_prompt(data[0]))
    expanded['method'] = ('Eligible whole words; duplicate and close variants omitted. Ranked headers exclude words '
        'annotated on their panel. Area percentages: local mean saved normalized association. Focus percentages: '
        'weighted RMS radius in image pixels divided by image diagonal; lower is more focused. Related percentages: positive Pearson '
        'spatial correlation, not semantic or causal relatedness. All-token percentages: word-map mean weighted '
        'by displayed all-token map intensity. Not confidence or absolute activity. Two lines of complete entries.')
    canvas.setText('PainterExpandedLists', json.dumps(expanded, ensure_ascii=False))
    canvas.setText('PainterWordGrouping', json.dumps(dict(source=str(source), selected=selected,
        words=words[0]['tokens'], method='Mean of saved normalized token planes per word occurrence; '
        'All-token reference excludes layout structure and includes descriptive prompt tokens. No additional per-word contrast stretch.'), ensure_ascii=False))
    ranking['method'] = ('Saved normalized associations, not absolute activity. English function words and punctuation excluded; '
                         'layout rankings use descriptive string values only, excluding structural fields and coordinates; '
                         'token pieces averaged per word occurrence before ranking; '
                         'up to 7x7 neighborhood means, centers separated by up to 12 cells; '
                         'area labels maximize eligible-token mean in that neighborhood; '
                         'repeated words, subpieces, plurals and close spelling variants deduplicated per panel; '
                         'focus minimizes image-pixel RMS radius weighted by max(score-.70,0)^2. Up to four per panel.')
    canvas.setText('PainterHeatmapMethod', json.dumps(dict(
        version=2, capture=data[0].get('capture', {'version': 1, 'timing': 'legacy forward-count capture'}),
        aggregate='Mean of visible descriptive token maps; per-token 5–99% normalization already applied; aggregate stretched 5–95%',
        focus_image_size=[width, height],
        limitation='Relative feature associations, not probabilities, raw activity or causal attribution'), ensure_ascii=False))
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

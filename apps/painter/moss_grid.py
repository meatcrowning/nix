"""Five-panel exports: an enlarged original beside (square/portrait) or above
(landscape) four thermal maps."""
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QSaveFile, QIODevice
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPen, QTextLayout, QTextOption
import moss_data
import moss_rank


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


def area_mask(data, ranking):
    from moss_inspect import token_mask
    doc, pixels = data
    w, h = doc['width'], doc['height']
    eligible = dict(doc, tokens=moss_rank.content_tokens(doc))
    eligible['_aggregate'] = moss_data.aggregate(eligible, pixels)
    hot = token_mask(eligible, pixels, -1)
    for y in range(h):
        for x in range(w):
            edge = max((max(0, min(1, (min(a['side']/2 + 1.5 - abs(x-a['x']), a.get('side_y', a['side'])/2 + 1.5 - abs(y-a['y']))) / 2))
                        for a in ranking['areas']), default=0)
            color = hot.pixelColor(x, y)
            color.setAlpha(round(color.alpha() * edge))
            hot.setPixelColor(x, y, color)
    return hot


def ranked_header(painter, rect, label, entries, font, padding):
    """Fit scored words in two lines, with a bold related-word lead-in."""
    metrics = QFontMetrics(font)
    title_width = metrics.horizontalAdvance(label)
    painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft,
                     metrics.elidedText(label, Qt.ElideRight, max(0, rect.width())))
    remaining = rect.adjusted(title_width + padding, 0, 0, 0)
    small = QFont(font)
    small.setPixelSize(max(10, round(font.pixelSize() * 0.55)))
    bold = QFont(small)
    bold.setBold(True)
    prefix = 'is most closely associated with ' if ' - token' in label else ''
    strong = prefix.startswith('is most')
    runs = [[], []]
    widths = [0, 0]
    line = 0
    shown = []
    if prefix:
        runs[0].append((prefix, strong))
        widths[0] = QFontMetrics(bold if strong else small).horizontalAdvance(prefix)
    for entry in entries:
        text = '%s %.1f%%' % (' '.join(entry['token']['text'].split()), entry['percentage'])
        sep = ' · ' if runs[line] and (not prefix or len(runs[line]) > 1 or line > 0) else ''
        advance = QFontMetrics(small).horizontalAdvance(sep + text)
        if widths[line] + advance > remaining.width():
            line += 1
            if line == 2:
                break
            sep = ''
            advance = QFontMetrics(small).horizontalAdvance(text)
        if advance > remaining.width():
            continue
        runs[line].append((sep + text, False))
        widths[line] += advance
        shown.append(entry)
    painter.save()
    painter.setClipRect(remaining)
    metrics = QFontMetrics(small)
    y = remaining.y() + (remaining.height() - 2 * metrics.height()) / 2 + metrics.ascent()
    for row in runs:
        x = remaining.x()
        for text, strong in row:
            f = bold if strong else small
            painter.setFont(f)
            painter.drawText(QPointF(x, y), text)
            x += QFontMetrics(f).horizontalAdvance(text)
        y += metrics.height()
    painter.restore()
    return dict(title=label, lines=[''.join((t for t, b in row)).strip() for row in runs], entries=shown)


def annotations(painter, rect, ranking, doc, font, padding):
    """Label hot and cold neighborhoods with compact ranked captions."""
    painter.save()
    painter.setClipRect(rect)
    small = QFont(font)
    small.setPixelSize(max(12, round(font.pixelSize() * 0.8)))
    placed = []
    captions = []
    counts = {'hot': 0, 'cold': 0}
    for item in ranking:
        kind = item['extreme']
        metrics = QFontMetrics(small)
        pf = QFont(small)
        pf.setPixelSize(round(small.pixelSize() * .5))
        pm = QFontMetrics(pf)
        lh = metrics.height() + 4
        counts[kind] = counts.get(kind, 0) + 1
        color = QColor('#ff5555' if kind == 'hot' else '#55baff')
        label = ' '.join(item['token'].get('display', item['token']['text']).split())
        label = '%d. %s' % (counts[kind], label)
        percent = ('%.1f%% mean' if kind == 'cold' else '%.1f%% assoc.') % item['percentage']
        lw = metrics.horizontalAdvance(label) + 4 + pm.horizontalAdvance(percent) + 8
        cx = rect.x() + (item['x'] + 0.5) * rect.width() / doc['width']
        cy = rect.y() + (item['y'] + 0.5) * rect.height() / doc['height']
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.NoBrush)
        side, side_y = item['side'], item.get('side_y', item['side'])
        bw = side * rect.width() / doc['width']
        bh = side_y * rect.height() / doc['height']
        outline = QRectF(cx - bw / 2, cy - bh / 2, bw, bh)
        painter.drawRoundedRect(outline, 6, 6)
        bx = max(rect.x(), min(rect.right() - lw, outline.x()))
        by = max(rect.y(), outline.y() - lh)
        box = QRectF(bx, by, lw, lh)
        # Nearby centroids can coincide; keep their individual captions readable.
        for shift in range(len(placed) + 1):
            candidates = [by - shift*(lh+5), by + shift*(lh+5)]
            found = False
            for candidate_y in candidates:
                trial = QRectF(bx, candidate_y, lw, lh)
                if rect.contains(trial.toAlignedRect()) and not any(trial.intersects(other) for other in placed):
                    box, found = trial, True
                    break
            if found:
                break
        placed.append(box.adjusted(-2, -2, 2, 2))
        captions.append((box, color, label, percent, QFont(small), QFont(pf)))
    # Draw captions last so a later neighborhood outline cannot cross their text.
    for box, color, label, percent, small, pf in captions:
        metrics = QFontMetrics(small)
        painter.fillRect(box, QColor('#e615191f'))
        painter.setPen(color)
        baseline = box.y() + 2 + metrics.ascent()
        painter.setFont(small)
        painter.drawText(QPointF(box.x() + 4, baseline), label)
        painter.setFont(pf)
        painter.drawText(QPointF(box.x() + 8 + metrics.horizontalAdvance(label), baseline), percent)
    painter.restore()


def add_title(image, model, method=''):
    """Fit the title and column headings with matching small gaps above/below."""
    kind = 'attention' if method == 'image-to-text attention weights' else 'association'
    title = '%s — token %s heatmaps' % (Path(model).stem if model else 'Unknown model', kind)
    font = QFont('sans-serif')
    font.setPixelSize(max(16, min(72, image.width() // 65)))
    font.setBold(True)
    padding = max(12, image.width() // 150)
    metrics = QFontMetrics(font)
    while metrics.horizontalAdvance(title) > image.width()-padding*2 and font.pixelSize() > 8:
        font.setPixelSize(font.pixelSize()-1)
        metrics = QFontMetrics(font)
    bounds = metrics.tightBoundingRect(title)
    vertical_padding = max(3, round(font.pixelSize() / 10))
    height = bounds.height() + 2 * vertical_padding
    # The first panel headers already contain top padding. Remove only blank
    # scanlines so the title's lower gap meets their first actual text pixels.
    pixels = image.constBits()
    stride = image.bytesPerLine()
    background = bytes(pixels[:4]) * image.width()
    trim = 0
    while trim < image.height() and bytes(pixels[trim*stride:trim*stride + image.width()*4]) == background:
        trim += 1
    result = QImage(image.width(), image.height()-trim+height, QImage.Format_RGB32)
    if result.isNull():
        raise ValueError('Not enough memory for the comparison title')
    result.fill(QColor('#15191f'))
    painter = QPainter(result)
    painter.drawImage(0, height, image.copy(0, trim, image.width(), image.height()-trim))
    painter.setFont(font)
    painter.setPen(QColor('#f4f5f7'))
    painter.drawText(QPointF(padding, vertical_padding-bounds.top()), title)
    painter.end()
    for key in image.textKeys():
        result.setText(key, image.text(key))
    result.setText('Title', title)
    result.setText('PainterTitleHeight', str(height))
    result.setText('PainterComparisonTopTrim', str(trim))
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
    if '_aggregate' not in data[0]:
        data[0]['_aggregate'] = moss_data.descriptive_aggregate(*data)
    words, lookup = moss_rank.word_maps(*data)
    selected = [lookup[token['index']] for token in tokens]
    full_ranking = moss_rank.rank(*words, limit=None, image_size=(width, height), extremes=True)
    ranking = dict(areas=full_ranking['areas'])
    all_tokens, related = moss_rank.association_lists(*words, selected, data[0]['_aggregate'])
    lists = {1: all_tokens, 2: full_ranking['area_headers'],
             3: related[0], 4: related[1]}
    expanded = {}
    prompt_links = []
    hot = area_mask(words, ranking)
    stacked = width > height
    if stacked:
        original_width = 2 * width + gap
        original_height = round(original_width * height / width)
        grid_left, grid_top = gap, gap + header + original_height + gap
        canvas_size = original_width + gap * 2, grid_top + (height + header) * 2 + gap * 2
    else:
        original_height = 2 * height + header + gap
        original_width = round(original_height * width / height)
        grid_left, grid_top = original_width + 2 * gap, gap
        canvas_size = grid_left + width * 2 + gap * 2, (height + header) * 2 + gap * 3
    canvas = QImage(*canvas_size, QImage.Format_RGB32)
    if canvas.isNull():
        raise ValueError('Not enough memory for the comparison')
    canvas.fill(QColor('#15191f'))
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(font)
        painter.setPen(QColor('#f4f5f7'))
        labels = ['Original output', 'All tokens · relative association', 'Hottest & coldest areas',
                  moss_rank.word_label(selected[0]), moss_rank.word_label(selected[1])]
        masks = [QImage(), token_mask(*data, -1), hot,
                 token_mask(*words, selected[0]['index']), token_mask(*words, selected[1]['index'])]
        for i, (label, mask) in enumerate(zip(labels, masks)):
            if i == 0:
                x, y = gap, gap
                panel_width, panel_height = original_width, original_height
            else:
                x = grid_left + ((i - 1) % 2) * (width + gap)
                y = grid_top + ((i - 1) // 2) * (height + header + gap)
                panel_width, panel_height = width, height
            heading = QRect(x + padding, y, panel_width - padding * 2, header)
            if i == 0:
                original_header(painter, heading, scene_prompt(data[0]), font, padding)
            else:
                expanded[str(i)] = ranked_header(painter, heading, label, lists[i], font, padding)
            rect = QRect(x, y + header, panel_width, panel_height)
            painter.drawImage(rect, original)
            if not mask.isNull():
                painter.drawImage(rect, mask)
            if i == 1:
                import moss_links
                prompt_links = moss_links.draw(painter, rect, words)
            if i == 2:
                items = ranking['areas']
                annotations(painter, rect, items, data[0], font, padding)
                if not items:
                    painter.drawText(rect.adjusted(padding, padding, -padding, -padding),
                                     Qt.AlignTop | Qt.AlignLeft, 'No eligible token maps')
    finally:
        painter.end()
    # Keep full labels, token identities, scores and methods off the artwork.
    canvas.setText('PainterPromptLinks', json.dumps(dict(words=prompt_links, method='Saved whole-word maxima; ties resolved by local mean, then nearest tied point to centroid. Circular endpoints.')))
    canvas.setText('Description', '\n'.join(labels))
    canvas.setText('PainterComparisonPrompt', scene_prompt(data[0]))
    expanded['method'] = ('Eligible whole words; duplicate and close variants omitted. Ranked headers exclude words '
        'annotated on their panel. Hot percentages: local winning word association; cold percentages: regional mean across eligible word maps. Related percentages: positive Pearson '
        'spatial correlation, not semantic or causal relatedness. All-token percentages: word-map mean weighted '
        'by displayed all-token map intensity. Not confidence or absolute activity. Two lines of complete entries.')
    canvas.setText('PainterExpandedLists', json.dumps(expanded, ensure_ascii=False))
    canvas.setText('PainterWordGrouping', json.dumps(dict(source=str(source), selected=selected,
        words=words[0]['tokens'], method=(data[0].get('capture', {}).get('word_reduction', 'Mean raw token-piece scores before smoothing and per-word normalization') + '; ' if data[0].get('words') else 'Legacy mean of saved normalized token planes per word occurrence; ')+
        'All-token reference excludes layout structure and includes descriptive prompt tokens.'), ensure_ascii=False))
    ranking['method'] = ('Saved normalized associations, not absolute activity. English function words and punctuation excluded; '
                         'layout rankings use descriptive string values only, excluding structural fields and coordinates; '
                         'word maps use the grouping method in PainterWordGrouping; '
                         'neighborhood radii scale as 3/64 of each axis; center separation at least 12/64 in normalized image coordinates; '
                         'area labels maximize eligible-token mean in that neighborhood; '
                         'repeated words, subpieces, plurals and close spelling variants deduplicated per panel; '
                         'Up to four hot and two cold areas. Cold percentages are regional means across eligible words; cold labels are local winning words.')
    canvas.setText('PainterHeatmapMethod', json.dumps(dict(
        version=3, method=data[0].get('method', 'attention output similarity'), consistency=data[0].get('consistency'), consistency_method=data[0].get('consistency_method'), capture=data[0].get('capture', {'version': 1, 'timing': 'legacy forward-count capture'}),
        aggregate='Mean of visible descriptive token maps; per-token 5–99% normalization already applied; aggregate stretched 5–95%',
        limitation='Relative normalized associations, not probabilities, raw activity or causal attribution'), ensure_ascii=False))
    canvas.setText('PainterRanking', json.dumps(ranking, ensure_ascii=False))
    import pngmeta
    try:
        metadata = json.loads(pngmeta.read_text_path(source).get('painter', '{}'))
        model = metadata.get('model', '')
    except (ValueError, TypeError, AttributeError):
        model = ''
    canvas = add_title(canvas, model, data[0].get('method', ''))
    destination = Path(folder)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ('painter-heatmap-%s-%s.png' % (datetime.now().strftime('%Y%m%d-%H%M%S'), uuid4().hex[:8]))
    output = QSaveFile(str(path))
    if not output.open(QIODevice.WriteOnly) or not canvas.save(output, 'PNG') or not output.commit():
        raise OSError(output.errorString())
    return path

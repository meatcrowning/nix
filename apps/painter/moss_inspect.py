"""Asynchronous prompt inspection and selected-output heatmap presentation."""
import json
import base64
import math
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QCoreApplication, QBuffer, QIODevice
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtCore import QSize
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtQml import qmlRegisterType
from PySide6.QtNetwork import QNetworkReply
import moss_data


class MossInspect(QObject):
    tokenized = Signal(str, str, 'QVariantMap')
    changed = Signal()
    _loaded = Signal(int, object)
    _exported = Signal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._closed = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='moss-inspect')
        self._generation = 0
        self._data = None
        self._path = self._overlay = self._error = ''
        self._tokens = []
        self._selected = -2
        self._chosen = -1
        self._hover_owner = ''
        self._nearby = []
        self._image_cell = None
        self._image_held = False
        self._exploring = False
        self._positions = OrderedDict()
        self._viewing = False
        self._picks = None
        self._exporting = False
        self._grid_status = ''
        self._future = None
        self._masks = OrderedDict()
        self.mask = QImage()
        self._packet = None
        self._loaded.connect(self._accept)
        self._exported.connect(self._export_done)
        QCoreApplication.instance().aboutToQuit.connect(self.close)

    def close(self):
        self._closed = True
        self._pool.shutdown(wait=True, cancel_futures=True)
        self._masks.clear()

    @Slot(str, str, str, result='QVariantMap')
    def tokenStyle(self, text, background, selection):
        from token_style import colours
        return colours(*(QColor(value).getRgb()[:3] for value in (text, background, selection)))

    @Slot(str, str)
    def tokenize(self, identity, text):
        if "PainterMossSampler" not in (self.client.object_info or {}):
            self.tokenized.emit(identity, text, {"error": "Token counts require a connected MOSS inspection backend"})
            return
        def done(reply):
            try:
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    result = {'error': 'Token counts require a connected MOSS inspection backend'}
                else:
                    result = json.loads(bytes(reply.readAll()))
                self.tokenized.emit(identity, text, result)
            except (ValueError, TypeError):
                self.tokenized.emit(identity, text, {'error': 'Invalid tokenizer reply'})
            finally:
                reply.deleteLater()
        reply = self.client._post('/painter/moss/tokenize', {'text': text}, done)
        reply.setProperty('moss_request', identity)
        # Bounded requests; stale replies are rejected by each editor.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(5000, reply, reply.abort)

    @Property(bool, notify=changed)
    def available(self):
        return self._data is not None and bool(self._tokens)

    @Property('QVariantList', notify=changed)
    def tokens(self):
        return self._tokens

    @Property('QVariantList', notify=changed)
    def choices(self):
        return [dict(label='Nearby tokens' if self._exploring else 'All tokens')] + self._tokens

    @Property(int, notify=changed)
    def selected(self):
        return self._selected

    @Slot(bool)
    def setViewing(self, viewing):
        self._viewing = viewing
        if not viewing:
            self._picks = None
            self._image_held = False
            self.leaveImage()
            self.changed.emit()
        if viewing and self.available:
            self.select(-1)

    @Property(bool, notify=changed)
    def exploring(self):
        return self._exploring

    @Property('QVariantList', notify=changed)
    def nearby(self):
        return self._nearby

    @Property(bool, notify=changed)
    def imageHeld(self):
        return self._image_held

    @Slot(float, float)
    def holdImage(self, x, y):
        if not self._viewing or not self.available or not (0 <= x < 1 and 0 <= y < 1):
            return
        self._image_held = False
        self._image_cell = None
        self.hoverImage(x, y)
        self._image_held = bool(self._nearby)
        self.changed.emit()

    @Slot(float, float)
    def hoverImage(self, x, y):
        if self._image_held or not self._viewing or not self.available or not math.isfinite(x + y):
            return
        if not (0 <= x < 1 and 0 <= y < 1):
            self.leaveImage()
            return
        doc, pixels = self._data
        w, h = doc['width'], doc['height']
        cell = (min(w-1, int(x*w)), min(h-1, int(y*h)))
        if cell == self._image_cell:
            return
        self._image_cell = cell
        cx, cy = cell
        cells = [j*w+i for j in range(max(0,cy-1), min(h,cy+2))
                 for i in range(max(0,cx-1), min(w,cx+2))]
        scores = []
        for token in doc.get('_content_tokens', []):
            start = token['index'] * w * h
            score = sum(pixels[start+i] for i in cells) / (255*len(cells))
            if score > 0:
                scores.append((score, token))
        scores.sort(key=lambda item: (-item[0], item[1]['index']))
        visible = {token['index']: i for i, token in enumerate(self._tokens)}
        self._nearby = [dict(token, choice=visible[token['index']], score=score,
                             label=token.get('display', token['text'].strip())) for score, token in scores[:4]]
        if not self._nearby:
            self._show(self._chosen)
            self.changed.emit()
            return
        key = tuple(sorted(t['index'] for t in self._nearby))
        mask = self._masks.pop(key, None)
        if mask is None:
            combined = dict(doc, tokens=self._nearby)
            combined['_aggregate'] = moss_data.aggregate(combined, pixels)
            mask = token_mask(combined, pixels, -1)
        self._masks[key] = mask
        while len(self._masks) > 64:
            self._masks.popitem(last=False)
        self._exploring = True
        self._hover_owner = 'image'
        self._selected = -1
        overlay = '%d:near:%s' % (self._generation, ','.join(map(str,key)))
        if overlay != self._overlay:
            self.mask = mask
            self._packet = None
            self._overlay = overlay
        self.changed.emit()

    @Slot()
    def releaseImage(self):
        self._image_held = False
        self.leaveImage()

    @Slot()
    def leaveImage(self):
        if self._image_held:
            return
        had_nearby = bool(self._nearby)
        self._nearby = []
        self._image_cell = None
        if self._hover_owner == 'image':
            self._hover_owner = ''
            self._show(self._chosen)
        if had_nearby:
            self.changed.emit()

    @Slot(int)
    def chooseNearby(self, index):
        if self.picking and not self._image_held:
            return
        if any(t['choice'] == index for t in self._nearby):
            self._image_held = False
            self.select(index)
            self._nearby = []
            self._image_cell = None
            if self.picking:
                self._record_pick(index)
            self.changed.emit()

    @Slot(str, str, result='QVariantList')
    def highlightedRanges(self, text, identity):
        if not self._nearby or not self._data:
            return []
        doc = self._data[0]
        region = None
        if identity:
            for i, item in enumerate(doc.get('_regions', [])):
                if item.get('id') == identity and item.get('caption', '').strip() == text.strip():
                    region = i
                    break
            if region is None:
                return []
        key = (text, identity)
        positions = self._positions.pop(key, None)
        if positions is None:
            positions = []
            offset = 0
            for i, character in enumerate(text):
                end = offset + len(character.encode('utf-16-le'))//2
                position = moss_data.prompt_position(doc.get('prompt',''), text, i, region)
                if position is not None:
                    positions.append((offset, end, position))
                offset = end
        self._positions[key] = positions
        while len(self._positions) > 8:
            self._positions.popitem(last=False)
        result = []
        for start, end, position in positions:
            if any(t.get('start', -1) <= position < t.get('end', -1) for t in self._nearby):
                if result and result[-1]['end'] == start:
                    result[-1]['end'] = end
                else:
                    result.append(dict(start=start, end=end))
        return result

    @Property(bool, notify=changed)
    def picking(self):
        return self._picks is not None

    @Property(bool, notify=changed)
    def exporting(self):
        return self._exporting

    @Property(str, notify=changed)
    def gridLabel(self):
        if self._exporting:
            return 'Saving grid…'
        if self.picking:
            return 'Pick token %d/2 · Cancel' % (len(self._picks) + 1)
        if self._grid_status.startswith('Saved '):
            return 'Grid saved'
        if self._grid_status:
            return 'Retry grid comparison'
        return 'Grid comparison'

    @Property(str, notify=changed)
    def gridStatus(self):
        return self._grid_status or 'Choose two prompt tokens, or click the image to hold an area and choose a token from its list.'

    @Slot()
    def toggleGrid(self):
        if self._exporting or not self._viewing or not self.available:
            return
        self._image_held = False
        self.leaveImage()
        self._picks = None if self.picking else []
        self._grid_status = ''
        self.changed.emit()

    @Slot(str, int, str)
    def pickToken(self, text, position, identity):
        if not self.picking or not self._viewing:
            return
        held, owner = self._image_held, self._hover_owner
        self._image_held = False
        self._hover_owner = ''
        if identity:
            self.hoverRegion(text, position, identity)
        else:
            self.hoverPrompt(text, position)
        # Resolve this click against the saved prompt, never a stale hover.
        if not self._hover_owner:
            self._image_held, self._hover_owner = held, owner
            return
        self._record_pick(self._selected)

    def _record_pick(self, index):
        self._picks.append(index)
        if len(self._picks) == 2:
            from PySide6.QtCore import QStandardPaths
            from moss_grid import save_grid
            folder = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
            path, data = self._path, self._data
            tokens = [dict(self._tokens[i]) for i in self._picks]
            self._picks = None
            self._exporting = True
            def export():
                try:
                    result = 'Saved ' + str(save_grid(path, data, tokens, folder))
                except Exception as exc:
                    result = 'Grid export failed: ' + str(exc)
                self._exported.emit(result)
            self._pool.submit(export)
        self.changed.emit()

    def _export_done(self, result):
        self._exporting = False
        self._grid_status = result
        self.changed.emit()

    @Slot()
    @Slot(str)
    def endHover(self, owner=''):
        if self._viewing and (not owner or owner == self._hover_owner):
            self._hover_owner = ''
            self._show(self._chosen)

    @Slot(str, int)
    def hoverPrompt(self, text, position):
        # QML offsets are UTF-16. GTK converts its character offsets before
        # sending them. Never apply current draft positions to another prompt.
        if not self._viewing or not self._data:
            return
        saved = self._data[0].get('prompt', '')
        position = len(text.encode('utf-16-le')[:position * 2].decode('utf-16-le', errors='ignore'))
        position = moss_data.prompt_position(saved, text, position)
        self._select_position(position, 'prompt')

    @Slot(str, int, str)
    def hoverRegion(self, text, position, identity):
        if not self._viewing or not self._data or not identity:
            return
        doc = self._data[0]
        regions = doc.get('_regions', [])
        for index, region in enumerate(regions):
            if region.get('id') == identity and region.get('caption', '').strip() == text.strip():
                position = len(text.encode('utf-16-le')[:position * 2].decode('utf-16-le', errors='ignore'))
                self._select_position(moss_data.prompt_position(doc.get('prompt', ''), text, position, index), 'region:' + identity)
                break

    def _select_position(self, position, owner):
        if self._image_held or position is None:
            return
        for index, token in enumerate(self._tokens):
            if token.get('start', -1) <= position < token.get('end', -1):
                had_nearby = bool(self._nearby)
                self._nearby = []
                self._image_cell = None
                self._hover_owner = owner
                self._show(index)
                if had_nearby: self.changed.emit()
                break

    def bind_toolbar(self, shell, root):
        from PySide6.QtWidgets import QComboBox, QPushButton
        combo = QComboBox(shell.window)
        combo.setObjectName('heatmapTokens')
        combo.setAccessibleName('Prompt token heatmap')
        combo.setMinimumContentsLength(12)
        combo.setMaximumWidth(260)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.activated.connect(lambda index: self.select(index - 1))
        combo.setToolTip('All tokens: mean saved association scores, with relative thermal contrast. Blue is low; red is high.')
        grid = QPushButton('Grid comparison', shell.window)
        grid.setObjectName('heatmapGrid')
        grid.setCheckable(True)
        grid.clicked.connect(self.toggleGrid)
        labels = []
        def refresh():
            current = [token['label'] for token in self.choices]
            combo.blockSignals(True)
            if current != labels:
                combo.clear()
                combo.addItems(current)
                labels[:] = current
            combo.setCurrentIndex(self.selected + 1)
            combo.blockSignals(False)
            combo.setVisible(bool(root.property('showHeatmap')))
            combo.setEnabled(self.available)
            grid.setVisible(bool(root.property('showHeatmap')))
            grid.setEnabled(self.available and not self.exporting)
            grid.setChecked(self.picking)
            grid.setText(self.gridLabel)
            grid.setToolTip(self.gridStatus)
        shell.toolbar_widget('main', combo)
        shell.toolbar_widget('main', grid)
        self.changed.connect(refresh)
        root.showHeatmapChanged.connect(refresh)
        refresh()
        return combo

    @Property(str, notify=changed)
    def overlay(self):
        return self._overlay

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Slot(str)
    def load(self, path):
        if self._closed:
            return
        path = QUrl(path).toLocalFile() if path.startswith('file:') else path
        self._picks = None
        self._nearby = []
        self._positions.clear()
        self._image_cell = None
        self._image_held = False
        self._exploring = False
        self._generation += 1
        serial = self._generation
        self._masks.clear()
        self.mask = QImage()
        self._packet = None
        self._path, self._data, self._tokens, self._overlay, self._error = path, None, [], '', ''
        self._selected = -2
        self._chosen = -1
        self._hover_owner = ''
        self.changed.emit()
        if self._future:
            self._future.cancel()
        if not path or not path.lower().endswith('.png'):
            return
        def read():
            try:
                value = moss_data.read(path)
                if value:
                    value[0]['_aggregate'] = moss_data.aggregate(*value)
                    import moss_rank
                    value[0]['_content_tokens'] = moss_rank.content_tokens(value[0])
                    import pngmeta
                    try:
                        params = json.loads(pngmeta.read_text_path(path).get('painter', '{}'))
                        value[0]['_regions'] = [r for r in params.get('moss_layout', {}).get('items', [])
                                                if r.get('enabled', True)]
                    except (ValueError, TypeError, AttributeError):
                        value[0]['_regions'] = []
            except (OSError, ValueError, KeyError, TypeError) as exc:
                value = str(exc)
            self._loaded.emit(serial, value)
        self._future = self._pool.submit(read)

    def _accept(self, serial, value):
        if serial != self._generation:
            return
        if isinstance(value, str):
            self._error = value
        elif value:
            self._data = value
            visible = [t for t in value[0]['tokens'] if t['visible']]
            self._tokens = [dict(t, label='%d · %s' % (i + 1, t['text'].replace('\n', '↵')))
                            for i, t in enumerate(visible)]
        self.changed.emit()
        if self._viewing and self.available:
            self.select(-1)

    @Slot(int)
    def select(self, index):
        if -1 <= index < len(self._tokens):
            self._image_held = False
            self._hover_owner = ''
            self._chosen = index
            self._show(index)

    def _show(self, index):
        if self._closed:
            return
        if not self._data or not (-1 <= index < len(self._tokens)):
            return
        if index == self._selected and not self._exploring:
            return
        self._exploring = False
        self._selected = index
        doc, pixels = self._data
        token = self._tokens[index]['index'] if index >= 0 else -1
        mask = self._masks.pop(token, None)
        if mask is None:
            mask = token_mask(doc, pixels, token)
        self._masks[token] = mask
        # At most 1 MiB for 64x64 maps; no full-resolution image copies.
        while len(self._masks) > 64:
            self._masks.popitem(last=False)
        self.mask = mask
        self._packet = None
        self._overlay = '%d:%d' % (self._generation, token)
        self.changed.emit()

    def mask_packet(self):
        """Small in-memory PNG for the historical GTK process's socket."""
        if self._packet is None:
            self._packet = ''
            if not self.mask.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                self.mask.save(buffer, 'PNG')
                self._packet = base64.b64encode(bytes(buffer.data())).decode('ascii')
        return self._packet


def _thermal(value, all_tokens=False):
    stops = ((25, 45, 150), (0, 125, 255), (0, 205, 190),
             (150, 225, 45), (255, 195, 0), (245, 45, 20))
    level = value / 255
    offset = level * (len(stops) - 1)
    index = min(len(stops) - 2, int(offset))
    fraction = offset - index
    rgb = [round(a + (b - a) * fraction) for a, b in zip(stops[index], stops[index + 1])]
    strength = level * level * (3 - 2 * level)
    return bytes(rgb + [round(65 + 145 * strength if all_tokens else 210 * strength)])


THERMAL = tuple(_thermal(value) for value in range(256))
THERMAL_ALL = tuple(_thermal(value, True) for value in range(256))


def token_mask(doc, pixels, token):
    w, h = doc['width'], doc['height']
    values = pixels[token * w * h:(token + 1) * w * h] if token >= 0 else doc['_aggregate']
    table = THERMAL if token >= 0 else THERMAL_ALL
    rgba = b''.join(table[value] for value in values)
    return QImage(rgba, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


class HeatmapLayer(QQuickPaintedItem):
    serviceChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._service = None
        self._mask_key = None
        self.setTextureSize(QSize(1, 1))
        self.setSmooth(True)

    def set_service(self, service):
        if service is self._service:
            return
        if self._service:
            self._service.changed.disconnect(self.refresh)
        self._service = service
        if service:
            service.changed.connect(self.refresh)
        self.serviceChanged.emit()
        self.refresh()

    def refresh(self):
        key = self._service.mask.cacheKey() if self._service else 0
        if key == self._mask_key:
            return
        self._mask_key = key
        # Keep the texture at map resolution, even when the image is zoomed.
        size = self._service.mask.size() if self._service else QSize(1, 1)
        self.setTextureSize(size if size.isValid() else QSize(1, 1))
        self.update()

    service = Property(QObject, lambda s: s._service, set_service, notify=serviceChanged)

    def paint(self, painter):
        if self._service and not self._service.mask.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(self.boundingRect(), self._service.mask)


qmlRegisterType(HeatmapLayer, 'PainterHeatmap', 1, 0, 'HeatmapLayer')

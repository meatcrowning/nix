#!/usr/bin/env python3
"""Isolated token debounce, editable decorations and portable heatmap checks."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import zlib

spec = importlib.util.spec_from_file_location('ui', Path(__file__).with_name('ui-test.py'))
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
from PySide6.QtCore import QObject, Signal, Slot, Qt, QMetaObject
from PySide6.QtGui import QImage, QColor
import moss_data
import pngmeta


class Tokens(QObject):
    tokenized = Signal(str, str, 'QVariantMap')
    def __init__(self):
        super().__init__()
        self.calls = []
    @Slot(str, str)
    def tokenize(self, identity, text):
        self.calls.append((identity, text))


with tempfile.TemporaryDirectory(prefix='painter-inspection-test-') as tmp:
    for key, name in [('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'),
                      ('PAINTER_OUT', 'out'), ('PAINTER_PEER_OUT', 'peer')]:
        os.environ[key] = str(Path(tmp) / name)
    os.environ['KDESHELL_STATE'] = str(Path(tmp) / 'shell.ini')
    os.environ['PAINTER_MODELS'] = u.fake_models(str(Path(tmp) / 'models'))
    app, engine, win, ctl, keep = u.build(tmp)
    root = u.APP
    combo = ctl.inspection.bind_toolbar(keep[-1], root) if os.environ.get('PAINTER_UI_NATIVE') == '1' else None
    probe = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'positiveTokenProbe')
    service = Tokens()
    probe.setProperty('service', service)
    probe.setProperty('active', True)
    root.set('positive', 'red')
    u.spin(100)
    root.set('positive', 'red cube')
    u.spin(100)
    assert not service.calls, service.calls
    u.spin(350)
    assert len(service.calls) == 1 and service.calls[0][1] == 'red cube'
    old = service.calls[-1]
    root.set('positive', 'red sphere')
    service.tokenized.emit(*old, dict(count=99, utf16_boundaries=[3]))
    assert probe.property('count') == -1
    u.spin(400)
    service.tokenized.emit(*service.calls[-1], dict(count=12, template_tokens=10, utf16_boundaries=[3]))
    u.spin(30)
    assert probe.property('count') == 2
    service.tokenized.emit(*service.calls[-1], dict(count=10, template_tokens=10))
    assert probe.property('count') == 0
    service.tokenized.emit(*service.calls[-1], dict(count=12, template_tokens=10, utf16_boundaries=[3]))
    box = u.find(win.contentItem(), 'PromptBox', lambda o: o.property('placeholder') == 'Positive')
    editor = u.find(box, 'QQuickTextEdit')
    assert editor.property('text') == 'red sphere'
    assert any(o.objectName() == 'tokenBoundary' and o.width() == 1 for o in u.walk(box))
    bands = next(o for o in u.walk(box) if o.objectName() == 'tokenBands')
    style = u.prop(box, 'tokenStyle')
    assert style['separator'] not in style['bands']
    assert style['separator'] not in [editor.property('color').name(), box.property('color').name(), editor.property('selectionColor').name()]
    u.spin(100)
    capture = bands.grabToImage()
    for _ in range(50):
        u.spin(10)
        if not capture.image().isNull(): break
    raster = capture.image()
    painted = {raster.pixelColor(x, y).name() for y in range(raster.height()) for x in range(raster.width())
               if raster.pixelColor(x, y).alpha() > 0}
    assert set(style['bands']) <= painted, (style, painted)
    editor.forceActiveFocus()
    QMetaObject.invokeMethod(editor, 'selectAll')
    u.spin(50)
    selection = bands.grabToImage()
    for _ in range(50):
        u.spin(10)
        if not selection.image().isNull(): break
    selected_image = selection.image()
    assert all(selected_image.pixelColor(x, y).alpha() == 0
               for y in range(selected_image.height()) for x in range(selected_image.width()))
    QMetaObject.invokeMethod(editor, 'deselect')
    editor.setProperty('cursorPosition', 10)
    u.key(win, Qt.Key_X, Qt.NoModifier, 'x')
    assert editor.property('text') == 'red spherex'
    u.key(win, Qt.Key_Z, Qt.ControlModifier, 'z')
    assert editor.property('text') == 'red sphere'
    assert probe.property('count') == -1
    print('PASS debounce, stale replies, editable token lines and native undo')

    doc = dict(version=1, width=2, height=2, prompt='red sphere',
               tokens=[dict(index=0, text='red', visible=True, start=0, end=3),
                       dict(index=1, text=' sphere', visible=True, start=3, end=10)])
    packet = moss_data.encode(doc, bytes([0, 255, 0, 255, 255, 0, 255, 0]))
    assert moss_data.decode(packet) == (doc, bytes([0, 255, 0, 255, 255, 0, 255, 0]))
    for broken in [b'x', zlib.compress(b'x'), moss_data.encode(dict(doc, tokens=[dict(index=99,text='x',visible=True)]), bytes(4))]:
        try: moss_data.decode(broken)
        except ValueError: pass
        else: raise AssertionError('accepted malformed maps')
    output = Path(tmp) / 'output.png'
    original = QImage(32, 32, QImage.Format_RGB32)
    original.fill(QColor('blue'))
    original.save(str(output))
    plain = output.read_bytes()
    chunk = struct.pack('>I', len(packet)) + moss_data.CHUNK + packet + struct.pack('>I', zlib.crc32(moss_data.CHUNK + packet))
    saved = pngmeta.upsert_text(plain[:-12] + chunk + plain[-12:], {'parameters': json.dumps({'positive': 'red'})})
    output.write_bytes(saved)
    assert moss_data.read(output)[0] == doc
    assert QImage(str(output)) == original
    gallery = u.find(win.contentItem(), 'GalleryView')
    gallery.setProperty('selection', [str(output)])
    root.setProperty('inView', True)
    for _ in range(100):
        u.spin(10)
        if ctl.inspection.available: break
    assert ctl.inspection.available
    root.setProperty('showHeatmap', True)
    for _ in range(100):
        u.spin(10)
        if ctl.inspection.overlay: break
    assert ctl.inspection.overlay
    assert gallery.isVisible()
    assert u.find(win.contentItem(), 'HeatmapPane').width() < u.find(win.contentItem(), 'ResultsPane').width()
    if combo:
        assert combo.isVisible() and combo.count() == 2
    ctl.inspection.hoverPrompt('red sphere', 5)
    assert ctl.inspection.selected == 1
    if combo: assert combo.currentIndex() == 1
    ctl.inspection.hoverPrompt('different draft', 0)
    assert ctl.inspection.selected == 1
    ctl.inspection.hoverPrompt('red sphere', 0)
    assert ctl.inspection.selected == 0
    assert ctl.inspection.mask.size().width() == 2
    assert ctl.inspection.mask.pixelColor(0, 0).alpha() == 0
    assert ctl.inspection.mask.pixelColor(1, 0).alpha() == 204
    first_mask = ctl.inspection.mask.cacheKey()
    ctl.inspection.select(1)
    ctl.inspection.select(0)
    assert ctl.inspection.mask.cacheKey() == first_mask, 'revisited token did not reuse its mask'
    layer = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'outputHeatmapLayer')
    assert layer.textureSize() == ctl.inspection.mask.size()
    base_image = layer.parentItem()
    image_source = base_image.property('source')
    # While the first map is pending, a transparent layer must leave the
    # already decoded source visible. No opaque loading pane or image reload.
    ctl.inspection.mask = QImage()
    ctl.inspection.changed.emit()
    u.spin(50)
    capture = base_image.grabToImage()
    for _ in range(50):
        u.spin(10)
        if not capture.image().isNull(): break
    raster = capture.image()
    assert raster.pixelColor(raster.width() // 2, raster.height() // 2) == QColor('blue')
    ctl.inspection.select(1)
    u.spin(50)
    assert base_image.property('source') == image_source
    capture = base_image.grabToImage()
    for _ in range(50):
        u.spin(10)
        if not capture.image().isNull(): break
    raster = capture.image()
    assert any(raster.pixelColor(x, y).red() > 100 for y in range(raster.height()) for x in range(raster.width()))
    print('PASS persistent base image during map loading, composited overlay and cached switching')
    # Layout outputs store the prompt box inside JSON, including escape bytes.
    caption = 'red "\U0001f30a"\\boat\nsphere'
    for ascii_only in (False, True):
        compiled = json.dumps(dict(summary=dict(caption=caption), items=[dict(caption=caption)]),
                              ensure_ascii=ascii_only, separators=(',', ':'))
        start = compiled.index(':"') + 2
        for position in range(len(caption)):
            expected = start + len(json.dumps(caption[:position], ensure_ascii=ascii_only)[1:-1])
            assert moss_data.prompt_position(compiled, caption, position) == expected
            assert moss_data.prompt_position(compiled, '  ' + caption + ' ', position + 2) == expected
        assert moss_data.prompt_position(compiled, 'different draft', 0) is None
    assert moss_data.prompt_position('a red sphere', 'red sphere', 1) is None
    split = moss_data.prompt_position(compiled, caption, caption.index('sphere'))
    layout_doc = dict(doc, prompt=compiled, tokens=[
        dict(index=0, text='red', visible=True, start=start, end=split),
        dict(index=1, text='sphere', visible=True, start=split, end=split + 6)])
    layout_packet = moss_data.encode(layout_doc, bytes([0, 255, 0, 255, 255, 0, 255, 0]))
    layout_chunk = (struct.pack('>I', len(layout_packet)) + moss_data.CHUNK + layout_packet
                    + struct.pack('>I', zlib.crc32(moss_data.CHUNK + layout_packet)))
    layout_output = Path(tmp) / 'layout.png'
    layout_output.write_bytes(plain[:-12] + layout_chunk + plain[-12:])
    gallery.setProperty('selection', [str(layout_output)])
    for _ in range(100):
        u.spin(10)
        if ctl.inspection.available and ctl.inspection.overlay: break
    assert ctl.inspection.selected == 0
    position = len(caption[:caption.index('sphere')].encode('utf-16-le')) // 2
    ctl.inspection.hoverPrompt(caption, position)
    assert ctl.inspection.selected == 1
    if combo: assert combo.currentIndex() == 1
    print('PASS layout caption hover, JSON escapes, Unicode and mismatched drafts')
    old_output = Path(tmp) / 'old.png'
    old_output.write_bytes(plain)
    gallery.setProperty('selection', [str(old_output)])
    u.spin(50)
    assert root.property('showHeatmap') and not ctl.inspection.available
    root.setProperty('showHeatmap', False)
    spec = importlib.util.spec_from_file_location('moss_checks', Path(__file__).with_name('moss-test.py'))
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    checks.models(Path(os.environ['PAINTER_MODELS']))
    ctl.setMode('')
    ctl.rescan()
    u.spin(150)
    ctl.selectModelByName('moss-base-int8.safetensors')
    u.spin(150)
    layout = ctl.layoutEditor.editor
    region = layout.model.add()
    region['caption'] = 'red sphere'
    layout.refresh()
    region_probe = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'regionTokenProbe')
    region_probe.setProperty('service', service)
    u.spin(400)
    assert region_probe.property('active') and service.calls[-1][1] == 'red sphere'
    service.tokenized.emit(*service.calls[-1], dict(count=12, template_tokens=10, utf16_boundaries=[3]))
    u.spin(50)
    region_count = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'regionTokenCount')
    region_field = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'layoutField_Prompt')
    assert region_count.property('text') == '2 tok'
    assert region_field.property('tokenReady')
    band = next(o for o in u.walk(region_field) if o.objectName() == 'tokenBands')
    assert band.property('marked')
    region_field.forceActiveFocus()
    region_field.setProperty('cursorPosition', 10)
    u.key(win, Qt.Key_X, Qt.NoModifier, 'x')
    u.key(win, Qt.Key_Z, Qt.ControlModifier)
    assert region_field.property('text') == 'red sphere'
    # Duplicate captions must select by saved identity, including disabled rows.
    compiled = json.dumps(dict(summary=dict(caption='scene'), items=[dict(caption='red sphere'), dict(caption='red sphere')]), separators=(',', ':'))
    spans = [moss_data.json_value_span(compiled, ('items', i, 'caption')) for i in range(2)]
    region_doc = dict(doc, prompt=compiled, tokens=[dict(index=i, text='red sphere', visible=True, start=a+1, end=b-1) for i,(a,b) in enumerate(spans)])
    packet = moss_data.encode(region_doc, bytes([0,255,0,255,255,0,255,0]))
    chunk = struct.pack('>I',len(packet))+moss_data.CHUNK+packet+struct.pack('>I',zlib.crc32(moss_data.CHUNK+packet))
    regions = [dict(id='disabled', caption='unused', enabled=False), dict(id='first', caption='red sphere'), dict(id=region['id'], caption='red sphere')]
    region_output = Path(tmp)/'regions.png'
    region_output.write_bytes(pngmeta.upsert_text(plain[:-12]+chunk+plain[-12:], {'painter':json.dumps(dict(moss_layout=dict(items=regions)))}))
    gallery.setProperty('selection',[str(region_output)])
    root.setProperty('showHeatmap',True)
    for _ in range(100):
        u.spin(10)
        if ctl.inspection.available and ctl.inspection.overlay: break
    ctl.inspection.hoverRegion('red sphere', 5, region['id'])
    assert ctl.inspection.selected == 1
    ctl.inspection.hoverRegion('red sphere', 5, 'first')
    assert ctl.inspection.selected == 0
    ctl.inspection.hoverRegion('edited draft', 5, region['id'])
    ctl.inspection.hoverRegion('red sphere', 5, 'unknown')
    assert ctl.inspection.selected == 0
    print('PASS region count, decorations, native undo and saved region hover identity')
    # Exercise the actual region hover handler, not only the inspection slot.
    from PySide6.QtCore import QPointF, QPoint
    from PySide6.QtTest import QTest
    scroller = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'parameterScroll')
    field_y = region_field.mapToItem(scroller, QPointF()).y() + scroller.property('contentY')
    scroller.setProperty('contentY', max(0, field_y - 50))
    u.spin(50)
    point = region_field.mapToItem(win.contentItem(), QPointF(region_field.property('leftPadding') + 12, region_field.property('topPadding') + 8))
    QTest.mouseMove(getattr(win, 'keyTarget', win), QPoint(round(point.x()), round(point.y())))
    u.spin(100)
    assert ctl.inspection.selected == 1, 'region hover did not reach saved token selection'
    u.spin(400)
    service.tokenized.emit(region_probe.property('request'), 'red sphere', dict(count=12, template_tokens=10, utf16_boundaries=[3]))
    u.spin(50)
    capture = region_field.grabToImage()
    for _ in range(50):
        u.spin(10)
        if not capture.image().isNull(): break
    raster = capture.image()
    painted = {raster.pixelColor(x, y).name() for y in range(raster.height()) for x in range(raster.width())}
    assert set(u.prop(region_field, 'tokenStyle')['bands']) <= painted, 'region bands hidden by native TextArea background'
    assert not u.WARNINGS, u.WARNINGS
    ctl.inspection.close()
    print('PASS PNG persistence, unchanged image pixels, viewer maps and selection invalidation')

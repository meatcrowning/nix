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
from PySide6.QtGui import QImage, QColor, QFont, QFontMetrics
import moss_data
import pngmeta


# Aggregate numeric scores before display mapping, excluding wrapper tokens.
aggregate_doc = dict(width=4, height=1, tokens=[dict(index=i, visible=i < 2) for i in range(3)])
assert moss_data.aggregate(aggregate_doc, bytes([0, 0, 100, 200, 0, 100, 100, 200, 255, 0, 0, 0])) == bytes([0, 128, 255, 255])
assert moss_data.aggregate(aggregate_doc, bytes([0, 100, 200, 0, 200, 100, 0, 200, 255, 0, 0, 0])) == bytes([100]*4)


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
    # Neighborhood ranking uses the saved content maps, with no wrapper/stopwords.
    from moss_inspect import MossInspect
    import moss_rank
    word_doc = dict(width=2, height=1, prompt='ramshackle ramshackle warehouse', tokens=[
        dict(index=i, text=text, start=start, end=end, visible=True)
        for i, (text, start, end) in enumerate([
            ('ram', 0, 3), ('sh', 3, 5), ('ackle', 5, 10),
            (' ramshackle', 10, 21), (' warehouse', 21, 31)])])
    word_data, lookup = moss_rank.word_maps(word_doc, bytes([0,255,120,120,240,0,20,40,50,60]))
    assert word_data[1] == bytes([120,125,20,40,50,60])
    assert lookup[0] == lookup[1] == lookup[2] and lookup[3] != lookup[0]
    assert moss_rank.word_label(lookup[0]) == 'ramshackle - tokens: [ram], [sh], [ackle]'
    assert moss_rank.word_label(lookup[4]) == 'warehouse - token: [warehouse]'
    list_doc = dict(width=4, height=1, prompt='alpha beta gamma flat and', tokens=[
        dict(index=i, text=word, visible=True) for i, word in enumerate(['alpha', 'beta', 'gamma', 'flat', 'and'])])
    list_pixels = bytes([0,64,128,255, 0,32,64,127, 255,191,127,0, 128,128,128,128, 255,255,255,255])
    all_words, related = moss_rank.association_lists(list_doc, list_pixels, [list_doc['tokens'][0]], bytes([0,0,0,255]))
    assert [t['token']['text'] for t in all_words] == ['alpha', 'flat', 'beta', 'gamma']
    assert all_words[0]['percentage'] == 100 and all_words[-1]['percentage'] == 0
    assert [t['token']['text'] for t in related[0]] == ['beta']
    assert 99 < related[0][0]['percentage'] <= 100
    # Numeric prose is meaningful; layout coordinates and JSON vocabulary are not.
    prose = json.dumps(dict(summary=dict(caption='Route 517 café', meta=['cinematic'], palette=['blue']),
                            items=[dict(label='character', caption='A "flipped" visor',
                                        bbox=[-544, 0, 517, 90], tags=['metal'])]), ensure_ascii=False)
    layout_tokens = [dict(index=i, text=m.group(), start=m.start(), end=m.end(), visible=True)
                     for i, m in enumerate(moss_rank.WORD.finditer(prose))]
    layout_maps = dict(width=2, height=1, prompt=prose, tokens=layout_tokens)
    eligible = moss_rank.content_tokens(layout_maps)
    assert [t['text'] for t in eligible] == ['Route', '517', 'café', 'cinematic', 'blue', 'flipped', 'visor', 'metal']
    indices = {t['index'] for t in eligible}
    cold = bytes(v for t in layout_tokens for v in ([255, 0] if t['index'] in indices else [0, 0]))
    hot = bytes(v for t in layout_tokens for v in ([255, 0] if t['index'] in indices else [255, 255]))
    assert moss_rank.rank(layout_maps, cold) == moss_rank.rank(layout_maps, hot)
    assert moss_rank.content_tokens(dict(prompt='544', tokens=[dict(index=0, text='544', start=0, end=3, visible=True)]))
    # Repeated occurrences, split pieces and plurals must not crowd out distinct words.
    rank_words = ['flower', 'FLOWER', 'flowers', 'flower', 'orange', 'oranges', 'blue', 'green']
    rank_prompt = ' '.join(rank_words)
    rank_tokens, rank_pixels, offset = [], [], 0
    for index, word in enumerate(rank_words):
        rank_tokens.append(dict(index=index, text=word if index != 3 else 'ower',
                                start=offset+(2 if index == 3 else 0), end=offset+len(word), visible=True))
        offset += len(word)+1
        cx, cy = 4+(index % 4)*9, 4+(index // 4)*12
        rank_pixels.extend(255 if abs(x-cx) <= 3 and abs(y-cy) <= 3 else 0
                           for y in range(24) for x in range(40))
    ranked = moss_rank.rank(dict(width=40, height=24, prompt=rank_prompt, tokens=rank_tokens), bytes(rank_pixels))
    for group in ('areas', 'focused'):
        assert len(ranked[group]) == 4, ranked
        for i, item in enumerate(ranked[group]):
            assert not moss_rank.duplicate_token(item['token'], ranked[group][:i]), ranked
    assert moss_rank.duplicate_token({'text': 'colour'}, [{'token': {'text': 'color'}}])
    assert not moss_rank.duplicate_token({'text': 'red'}, [{'token': {'text': 'bed'}}])
    scout = MossInspect(None)
    words = ['with', 'red', 'blue', 'green', 'gold', 'silver', 'amber']
    prompt = ' '.join(words)
    offset = 0
    records, planes = [], []
    for index, word in enumerate(words):
        records.append(dict(index=index, text=word, start=offset, end=offset+len(word), visible=True))
        offset += len(word)+1
        planes.extend([(255 if index == 0 else (255-index*30 if x < 4 else index*40)) for y in range(8) for x in range(8)])
    scout_doc = dict(width=8, height=8, prompt=prompt, tokens=records)
    scout_doc['_aggregate'] = moss_data.aggregate(scout_doc, bytes(planes))
    scout_doc['_content_tokens'] = moss_rank.content_tokens(scout_doc)
    scout._viewing = True
    scout._accept(0, (scout_doc, bytes(planes)))
    scout.hoverImage(0, 0)
    assert [t['text'] for t in scout.nearby] == ['red', 'blue', 'green', 'gold', 'silver', 'amber']
    assert abs(scout.nearby[0]['score'] - 225/255) < 1e-6
    left_key = scout.mask.cacheKey()
    scout.hoverImage(.99, .99)
    assert [t['text'] for t in scout.nearby] == ['amber', 'silver', 'gold', 'green', 'blue', 'red']
    scout.hoverImage(0, 0)
    assert scout.mask.cacheKey() == left_key
    scout.holdImage(0, 0)
    assert scout.imageHeld
    held_choices = [t['choice'] for t in scout.nearby]
    scout.hoverImage(.99, .99)
    scout.leaveImage()
    assert scout.imageHeld and [t['choice'] for t in scout.nearby] == held_choices
    scout._picks = []
    list_changes = []
    scout.nearbyChanged.connect(lambda: list_changes.append(True))
    scout.hoverNearby(held_choices[0])
    first_hover = scout.mask.cacheKey()
    assert scout.selected == held_choices[0] and scout.imageHeld and not scout._picks
    scout.hoverNearby(held_choices[1])
    scout.leaveNearby(held_choices[0])  # A late leave must not override the next row.
    assert scout.selected == held_choices[1]
    scout.hoverNearby(held_choices[0])
    assert scout.mask.cacheKey() == first_hover
    scout.leaveNearby(held_choices[0])
    assert scout.mask.cacheKey() == left_key and scout.imageHeld
    assert not list_changes, 'individual previews rebuilt the held list'
    scout.releaseImage()
    assert not scout.imageHeld and not scout.nearby
    scout.hoverImage(1, .5)
    assert not scout.nearby and not scout.exploring
    scout.close()
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
    assert not any(o.objectName() == 'tokenBoundary' for o in u.walk(box))
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
    from unittest.mock import patch
    from threading import Event
    cache_probe = MossInspect(None)
    gate = Event()
    export_work = cache_probe._pool.submit(gate.wait, 5)
    try:
        with patch('moss_data.read', wraps=moss_data.read) as reader:
            for expected_reads in (1, 1, 2):
                if expected_reads == 2:
                    stamp = output.stat()
                    os.utime(output, ns=(stamp.st_atime_ns, stamp.st_mtime_ns+1))
                cache_probe.load(str(output))
                assert cache_probe.status == 'Loading heatmaps…'
                for _ in range(100):
                    u.spin(10)
                    if cache_probe.available: break
                assert cache_probe.available, 'map loading waited for the export worker'
                assert 'Saved maps v1' in cache_probe.status
                assert reader.call_count == expected_reads, 'cache missed or reused a modified file'
        assert not export_work.done()
        missing = Path(tmp)/'no-maps.png'
        missing.write_bytes(pngmeta.upsert_text(plain, {'painter': {'moss_heatmaps': True},
                                                     'painter_moss_status': 'Sampling ended before capture'}))
        cache_probe.load(str(missing))
        for _ in range(100):
            u.spin(10)
            if 'Loading' not in cache_probe.status: break
        assert not cache_probe.available and 'Sampling ended before capture' in cache_probe.status
        missing.write_bytes(plain)
        cache_probe.load(str(missing))
        for _ in range(100):
            u.spin(10)
            if 'Loading' not in cache_probe.status: break
        assert cache_probe.status == 'No heatmaps saved for this output'

    finally:
        gate.set()
        cache_probe.close()
    print('PASS map cache reuse, file invalidation and loading during an export')
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
    assert ctl.inspection.selected == -1
    from PySide6.QtCore import QPointF, QPoint
    from PySide6.QtTest import QTest
    if combo:
        from PySide6.QtWidgets import QPushButton
        grid_button = keep[-1].window.findChild(QPushButton, 'heatmapGrid')
        assert grid_button.isVisible()
        grid_button.click()
    else:
        ctl.inspection.toggleGrid()
    click_point = editor.mapToItem(win.contentItem(), QPointF(12, 8))
    QTest.mouseClick(keep[-1].view if combo else win, Qt.LeftButton, Qt.NoModifier,
                     QPoint(round(click_point.x()), round(click_point.y())))
    assert ctl.inspection._picks == [0], 'main prompt click did not pick token'
    ctl.inspection.toggleGrid()
    ctl.inspection.select(-1)
    aggregate_key = ctl.inspection.mask.cacheKey()
    ctl.inspection.hoverPrompt('red sphere', 5)
    assert ctl.inspection.selected == 1
    ctl.inspection.endHover()
    assert ctl.inspection.selected == -1 and ctl.inspection.mask.cacheKey() == aggregate_key
    ctl.inspection.select(0)
    ctl.inspection.hoverPrompt('red sphere', 5)
    ctl.inspection.endHover('region:unrelated')
    assert ctl.inspection.selected == 1
    ctl.inspection.endHover('prompt')
    assert ctl.inspection.selected == 0  # Restore an explicit dropdown choice.
    ctl.inspection.select(-1)
    assert gallery.isVisible()
    assert u.find(win.contentItem(), 'HeatmapPane').width() < u.find(win.contentItem(), 'ResultsPane').width()
    if combo:
        assert combo.isVisible() and combo.count() == 3
    ctl.inspection.hoverPrompt('red sphere', 5)
    assert ctl.inspection.selected == 1
    if combo: assert combo.currentIndex() == 2
    ctl.inspection.hoverPrompt('different draft', 0)
    assert ctl.inspection.selected == 1
    ctl.inspection.hoverPrompt('red sphere', 0)
    assert ctl.inspection.selected == 0
    assert ctl.inspection.mask.size().width() == 2
    assert ctl.inspection.mask.pixelColor(0, 0).alpha() == 0
    assert ctl.inspection.mask.pixelColor(1, 0).alpha() == 210
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
    ctl.inspection.select(-1)
    point_image = layer.mapToItem(win.contentItem(), QPointF(layer.width()*.25, layer.height()*.75))
    QTest.mouseMove(keep[-1].view if combo else win, QPoint(round(point_image.x()), round(point_image.y())))
    u.spin(100)
    assert len(ctl.inspection.nearby) == 2, 'image hover did not reach saved maps'
    assert ctl.inspection._exploring and ':near:' in ctl.inspection.overlay
    assert ctl.inspection.highlightedRanges('red sphere', '') == [dict(start=0, end=10)]
    assert ctl.inspection.highlightedRanges('different draft', '') == []
    assert bands.property('highlighted'), 'nearby tokens were not highlighted in the prompt'
    near_mask = ctl.inspection.mask.cacheKey()
    ctl.inspection.hoverImage(.26, .76)
    assert ctl.inspection.mask.cacheKey() == near_mask
    ctl.inspection.holdImage(.26, .76)
    u.spin(50)
    buttons = [o for o in u.walk(win.contentItem()) if o.objectName() == 'nearbyTokenChoice' and o.isVisible()]
    assert buttons, 'nearby tooltip is not visible'
    button = buttons[-1]
    choice = button.property('modelData')['choice']
    bp = button.mapToItem(win.contentItem(), QPointF(button.width()/2, button.height()/2))
    QTest.mouseMove(keep[-1].view if combo else win, QPoint(round(bp.x()), round(bp.y())))
    u.spin(250)  # The interactive tooltip survives crossing out of the image.
    assert ctl.inspection.nearby
    assert ctl.inspection.selected == choice and ctl.inspection.imageHeld, 'held row hover did not preview its token'
    assert button in list(u.walk(win.contentItem())), 'preview recreated its own hovered button'
    QTest.mouseClick(keep[-1].view if combo else win, Qt.LeftButton, Qt.NoModifier, QPoint(round(bp.x()), round(bp.y())))
    assert ctl.inspection.selected == choice and not ctl.inspection._exploring
    ctl.inspection.leaveImage()
    assert not ctl.inspection.nearby and ctl.inspection.selected == choice
    ctl.inspection.select(-1)
    ctl.inspection.hoverImage(.25, .75)
    ctl.inspection.hoverImage(-.1, .5)
    assert not ctl.inspection.nearby and ctl.inspection.mask.cacheKey() == aggregate_key
    print('PASS image hover, combined cached map, prompt ranges, clickable tooltip and leave restoration')
    root.setProperty('inView', False)
    preview = u.find(win.contentItem(), 'PreviewPane')
    preview.setProperty('open', True)
    u.spin(100)
    preview.setProperty('zoom', 1.6)
    preview.setProperty('panX', -50)
    preview.setProperty('panY', -30)
    preview_layer = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'previewHeatmapLayer')
    pp = preview_layer.mapToItem(win.contentItem(), QPointF(preview_layer.width()*.35, preview_layer.height()*.45))
    QTest.mouseMove(keep[-1].view if combo else win, QPoint(round(pp.x()), round(pp.y())))
    u.spin(100)
    assert ctl.inspection.nearby and ctl.inspection._image_cell == (0, 0), 'zoomed/panned preview hover coordinates are wrong'
    QTest.mouseClick(keep[-1].view if combo else win, Qt.LeftButton, Qt.NoModifier, QPoint(round(pp.x()), round(pp.y())))
    assert ctl.inspection.imageHeld, 'preview click did not hold the area'
    ctl.inspection.hoverImage(.9, .9)
    assert ctl.inspection._image_cell == (0, 0)
    ctl.inspection.releaseImage()
    ctl.inspection.leaveImage()
    preview.setProperty('zoom', 1)
    preview.setProperty('panX', 0)
    preview.setProperty('panY', 0)
    root.setProperty('inView', True)
    u.spin(50)


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
    assert ctl.inspection.selected == -1
    position = len(caption[:caption.index('sphere')].encode('utf-16-le')) // 2
    ctl.inspection.hoverPrompt(caption, position)
    assert ctl.inspection.selected == 1
    if combo: assert combo.currentIndex() == 2
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
    region_output.write_bytes(pngmeta.upsert_text(plain[:-12]+chunk+plain[-12:], {'painter':json.dumps(dict(model='saved-moss.safetensors', moss_layout=dict(items=regions)))}))
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
    ctl.inspection.hoverImage(.5, .5)
    assert ctl.inspection.highlightedRanges('red sphere', region['id']) == [dict(start=0, end=10)]
    assert ctl.inspection.highlightedRanges('red sphere', 'unknown') == []
    assert ctl.inspection.highlightedRanges('edited draft', region['id']) == []
    ctl.inspection.leaveImage()
    print('PASS region count, decorations, native undo and saved region hover identity')
    # Exercise the actual region hover handler, not only the inspection slot.
    from PySide6.QtCore import QPointF, QPoint
    from PySide6.QtTest import QTest
    scroller = next(o for o in u.walk(win.contentItem()) if o.objectName() == 'parameterScroll')
    field_y = region_field.mapToItem(scroller, QPointF()).y() + scroller.property('contentY')
    scroller.setProperty('contentY', max(0, field_y - 50))
    u.spin(50)
    point = region_field.mapToItem(win.contentItem(), QPointF(region_field.property('leftPadding') + 12, region_field.property('topPadding') + 8))
    QTest.mouseMove(keep[-1].view if combo else win, QPoint(round(point.x()), round(point.y())))
    u.spin(100)
    assert ctl.inspection.selected == 1, 'region hover did not reach saved token selection'
    QTest.mouseMove(keep[-1].view if combo else win, QPoint(round(point.x()), round(point.y()) - 40))
    u.spin(50)
    assert ctl.inspection.selected == -1, 'leaving region did not restore all tokens'
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
    # Export only after two valid clicks; use a scratch Pictures destination.
    from unittest.mock import patch
    from PySide6.QtCore import QStandardPaths
    pictures = Path(tmp) / 'pictures'
    with patch.object(QStandardPaths, 'writableLocation', return_value=str(pictures)):
        ctl.inspection.toggleGrid()
        assert ctl.inspection.picking and '1/2' in ctl.inspection.gridLabel
        ctl.inspection.pickToken('edited draft', 2, region['id'])
        assert ctl.inspection._picks == []
        QTest.mouseClick(keep[-1].view if combo else win, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(point.x()), round(point.y())))
        u.spin(50)
        assert len(ctl.inspection._picks) == 1 and '2/2' in ctl.inspection.gridLabel
        assert not pictures.exists()
        ctl.inspection.hoverImage(.5, .5)
        ctl.inspection.chooseNearby(0)
        assert len(ctl.inspection._picks) == 1  # An unheld list cannot fill a grid slot.
        ctl.inspection.holdImage(.5, .5)
        ctl.inspection.leaveImage()
        assert ctl.inspection.imageHeld
        ctl.inspection.chooseNearby(0)
        assert not ctl.inspection.imageHeld and not ctl.inspection.picking
        for _ in range(200):
            u.spin(10)
            if not ctl.inspection.exporting: break
        assert ctl.inspection.gridStatus.startswith('Saved '), ctl.inspection.gridStatus
        exported = list(pictures.glob('*.png'))
        assert len(exported) == 1
        grid = QImage(str(exported[0]))
        assert not grid.isNull()
        export_font = QFont('sans-serif')
        export_font.setPixelSize(max(16, min(48, original.width() // 35)))
        header = QFontMetrics(export_font).height() + 24
        large_height = 2*original.height() + header + 12
        large_width = round(large_height*original.width()/original.height())
        assert grid.width() == large_width + original.width()*2 + 48  # Square: original beside the maps.
        assert 'focused' not in json.loads(grid.text('PainterRanking'))
        assert grid.text('Description').splitlines() == [
            'Original output', 'All tokens · relative association', 'Hottest & coldest areas',
            'red sphere - token: [red sphere]', 'red sphere - token: [red sphere]']
        assert '5' not in json.loads(grid.text('PainterExpandedLists'))
        assert len(json.loads(grid.text('PainterWordGrouping'))['selected']) == 2
        assert grid.text('PainterComparisonPrompt') == json.loads(compiled)['summary']['caption']
        expanded = json.loads(grid.text('PainterExpandedLists'))
        assert all(len(expanded[str(i)]['lines']) == 2 for i in range(1, 5))
        panel_ranks = json.loads(grid.text('PainterRanking'))
        assert all(t['extreme'] in ('hot', 'cold') for t in panel_ranks['areas'])
        assert len(panel_ranks['areas']) <= 6
        assert 'words' in json.loads(grid.text('PainterPromptLinks'))
        for i, key in ((2, 'areas'),):
            assert all(not moss_rank.duplicate_token(t['token'], panel_ranks[key]) for t in expanded[str(i)]['entries'])
            assert all(0 <= t['percentage'] <= 100 for t in panel_ranks[key])
        # Original panel is unmodified; the thermal panel differs.
        title_height = int(grid.text('PainterTitleHeight'))
        assert grid.text('Title') == 'saved-moss — token association heatmaps'
        image_y = title_height - int(grid.text('PainterComparisonTopTrim')) + 12 + header + 4
        assert grid.pixelColor(16, image_y) == original.pixelColor(4, 4)
        assert grid.pixelColor(large_width + 28, image_y) != original.pixelColor(4, 4)
        ctl.inspection.toggleGrid()
        for choice in (0, 1):
            ctl.inspection.holdImage(.5, .5)
            ctl.inspection.pickToken('edited draft', 2, region['id'])
            assert ctl.inspection.imageHeld  # Invalid draft clicks cannot release a held list.
            ctl.inspection.chooseNearby(choice)
        for _ in range(200):
            u.spin(10)
            if not ctl.inspection.exporting: break
        assert ctl.inspection.gridStatus.startswith('Saved ')
        assert len(list(pictures.glob('*.png'))) == 2
        with patch('moss_grid.save_grid', side_effect=OSError('disk unavailable')):
            ctl.inspection.toggleGrid()
            ctl.inspection.pickToken('red sphere', 2, 'first')
            ctl.inspection.pickToken('red sphere', 2, region['id'])
            for _ in range(200):
                u.spin(10)
                if not ctl.inspection.exporting: break
            assert ctl.inspection.gridStatus == 'Grid export failed: disk unavailable'
            assert ctl.inspection.gridLabel == 'Retry grid comparison'
        ctl.inspection.toggleGrid()
        ctl.inspection.pickToken('red sphere', 2, 'first')
        ctl.inspection.setViewing(False)
        assert not ctl.inspection.picking
        ctl.inspection.setViewing(True)
        ctl.inspection.toggleGrid()
        ctl.inspection.load(str(output))
        assert not ctl.inspection.picking
    print('PASS two-click grid, stale draft rejection, labels, pixels and cancellation')
    assert not u.WARNINGS, u.WARNINGS
    ctl.inspection.close()
    print('PASS PNG persistence, unchanged image pixels, viewer maps and selection invalidation')

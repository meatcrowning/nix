#!/usr/bin/env python3
"""Layout geometry/compiler and native Qt controls, entirely offscreen."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import moss_layout as M


def core():
    order = M.Editor(M.fresh())
    ids = [order.add()['id'] for _ in range(5)]
    order.doc['items'][2]['locked'] = True
    before = copy.deepcopy(order.doc)
    for source, target in ((ids[2], 0), (ids[0], 3), (ids[4], 1), (ids[0], -1), ('missing', 0)):
        assert not order.reorder(source, target)
        assert order.doc == before
    assert order.reorder(ids[0], 1)
    assert [r['id'] for r in order.doc['items']] == [ids[1], ids[0], ids[2], ids[3], ids[4]]
    order.undo()
    assert order.doc == before
    order.undo(True)
    assert order.doc['items'][1]['id'] == ids[0]
    from layout_cache import LayerCache
    cache = LayerCache(lambda *args: object(), limit=1000, scale=2)
    cache.get(b'a' * 500, 5, 5)
    cache.get(b'b' * 500, 5, 5)
    assert len(cache.entries) == 1 and cache.bytes == 900
    cache.get(b'oversized' * 200, 5, 5)
    assert not cache.entries and cache.bytes == 0
    e = M.Editor(M.fresh(1024, 1024, 'A travel poster'))
    a = e.add('text', [.1, .2, .4, .2])
    a.update(caption='A large heading', text='旅へ\nEXPLORE', palette=['#123456'], tags=['title'])
    a['typography'] = dict(family='serif', weight='bold', align='center', color='#123456', outline='white', shadow='soft', surface='paper')
    e.doc['enabled'] = True
    e.doc['summary'].update(meta=['poster'], palette=['#eeeeee'], canvas='multi_panel')
    e.doc['reference'] = '/never/condition/this.png'
    compiled = json.loads(M.compile(e.doc, 2048, 2048))
    assert compiled['items'][0]['bbox'] == [-615, -820, -204, 0]
    assert compiled['items'][0]['text'] == '旅へ\nEXPLORE'
    assert 'Text on surface: paper.' in compiled['items'][0]['caption']
    assert compiled['summary']['palette'] == ['#eeeeee']
    assert 'reference' not in json.dumps(compiled) and 'locked' not in json.dumps(compiled)
    assert M.resize(e.doc, 2048, 2048)['items'][0]['box'] == a['box']
    fit = M.resize(e.doc, 2048, 1024, 'fit')['items'][0]['box']
    assert all(abs(x-y) < 1e-8 for x,y in zip(fit, [.3, .2, .2, .2]))
    stretch = M.resize(e.doc, 2048, 1024, 'stretch')['items'][0]['box']
    assert stretch == a['box']
    keep = M.resize(e.doc, 2048, 512, 'keep sizes')['items'][0]['box']
    assert abs(keep[2] * 2048 - .4 * 1024) < 1e-7
    assert abs(keep[3] * 512 - .2 * 1024) < 1e-7
    e.doc['items'][0]['enabled'] = False
    try: M.compile(e.doc)
    except ValueError: pass
    else: raise AssertionError('empty layout accepted')
    e.doc['items'][0]['enabled'] = True
    e.duplicate()
    assert len(e.doc['items']) == 2 and len(set(r['id'] for r in e.doc['items'])) == 2
    e.undo(); assert len(e.doc['items']) == 1
    e.undo(True); assert len(e.doc['items']) == 2
    e.selected = [r['id'] for r in e.doc['items']]
    e.group()
    e.select(e.selected[0]); assert len(e.selected) == 2
    before = copy.deepcopy(e.doc['items'])
    e.move(.1, .1)
    for old, new in zip(before, e.doc['items']):
        assert abs(new['box'][0] - old['box'][0] - .1) < 1e-8
    e.doc['items'][0]['locked'] = True
    old = list(e.doc['items'][0]['box'])
    e.move(-.1, -.1); assert e.doc['items'][0]['box'] == old
    raw = e.copy()
    other = M.Editor(M.fresh())
    other.paste(raw); assert len(other.doc['items']) == 2
    other.group(True)
    assert not any(r.get('group') for r in other.doc['items'])
    other.doc['items'][0]['locked'] = False
    other.align('left')
    assert other.doc['items'][0]['box'][0] == other.doc['items'][1]['box'][0]
    other.add('object', [.7, .2, .1, .1])
    other.selected = [r['id'] for r in other.doc['items']]
    other.align('distribute horizontal')
    M.valid(other.doc)
    ordered = sorted(other.doc['items'], key=lambda r: r['box'][0])
    gaps = [b['box'][0] - a['box'][0] - a['box'][2] for a,b in zip(ordered, ordered[1:])]
    assert abs(gaps[0] - gaps[1]) < 1e-8
    assert abs(other.snap(.299, 0, .01) - .3) < 1e-8
    other.doc['snap'] = False
    assert other.snap(.299, 0, .01) == .299
    # Clicking near a snap guide, including a resize handle, must not edit.
    clicks = M.Editor(M.fresh())
    clicks.add('object', [.103, .203, .2, .2])
    for start in ((.2, .3), (.103, .203)):
        for jitter in (0, .002):
            before = copy.deepcopy(clicks.doc)
            history = copy.deepcopy((clicks.undo_stack, clicks.redo_stack))
            clicks.press(*start)
            clicks.motion(start[0] + jitter, start[1] + jitter)
            clicks.release()
            assert clicks.doc == before, 'selection click snapped region geometry'
            assert (clicks.undo_stack, clicks.redo_stack) == history
    before = copy.deepcopy(clicks.doc)
    clicks.press(.2, .3)
    clicks.motion(.23, .33)
    clicks.motion(.201, .301)  # Once dragging, returning near the start still moves.
    assert clicks.doc != before
    clicks.release()
    clicks.undo()
    assert clicks.doc == before
    clicks.undo(True)
    assert clicks.doc != before
    selection = M.Editor(M.fresh())
    selection.doc['snap'] = False
    selection.add('object', [.1, .1, .15, .15])
    selection.add('character', [.4, .2, .15, .15])
    selection.selected = []
    selection.press(.01, .01)
    selection.motion(.7, .5)
    assert selection.marquee and len(selection.selected) == 2
    assert b'stroke-dasharray="4 3"' in M.svg(selection, 500, 500)[0]
    selection.release()
    assert selection.marquee is None
    before = copy.deepcopy(selection.doc['items'])
    selection.press(.18, .18)
    selection.motion(.9, .9)
    selection.release()
    offsets = [(b['box'][0] - a['box'][0], b['box'][1] - a['box'][1]) for a, b in zip(before, selection.doc['items'])]
    assert all(abs(a-b) < 1e-8 for a,b in zip(offsets[0], offsets[1]))
    assert max(r['box'][0]+r['box'][2] for r in selection.doc['items']) <= 1
    draw = M.Editor(M.fresh())
    draw.tool = 'character'
    draw.press(.2, .3); draw.motion(.6, .8); draw.release()
    assert all(abs(x-y)<1e-8 for x,y in zip(draw.chosen()[0]['box'], [.2,.3,.4,.5]))
    draw.press(.6, .8); draw.motion(.7, .9); draw.release()
    assert abs(draw.chosen()[0]['box'][2] - .5) < 1e-8
    draw.doc['items'][0]['locked'] = True
    before = copy.deepcopy(draw.doc)
    draw.press(.4, .4); draw.motion(.5, .5); draw.release()
    assert before == draw.doc
    # Draw from/to every outside edge and corner, in both directions.
    for start, end, expected in [
            ((-.2, .2), (.6, .8), [0, .2, .6, .6]),
            ((1.2, .2), (.6, .8), [.6, .2, .4, .6]),
            ((.2, -.2), (.8, .6), [.2, 0, .6, .6]),
            ((.2, 1.2), (.8, .6), [.2, .6, .6, .4]),
            ((-.2, -.3), (1.2, 1.3), [0, 0, 1, 1])]:
        for a, b in [(start, end), (end, start)]:
            outside = M.Editor(M.fresh())
            outside.doc['snap'] = False
            outside.tool = 'object'
            outside.press(*a)
            assert outside.drag[1:3] == a
            outside.motion(*b)
            raw = outside.chosen()[0]['box']
            assert abs(raw[2] - abs(a[0] - b[0])) < 1e-8
            assert b'clip-path="url(#canvas)"' in M.svg(outside, 500, 500)[0]
            outside.release()
            assert all(abs(x-y) < 1e-8 for x,y in zip(outside.chosen()[0]['box'], expected))
            M.valid(outside.doc)
            outside.undo(); assert not outside.doc['items']
            outside.undo(True); M.valid(outside.doc)
    outside = M.Editor(M.fresh())
    outside.tool = 'object'
    outside.press(-.4, .2); outside.motion(-.2, .8); outside.release()
    assert not outside.doc['items'] and not outside.undo_stack
    # Leaving and returning tracks the original anchor, without a stuck edge.
    outside.tool = 'object'
    outside.press(.2, .3); outside.motion(1.4, 1.5); outside.motion(.7, .8); outside.release()
    assert all(abs(x-y) < 1e-8 for x,y in zip(outside.chosen()[0]['box'], [.2,.3,.5,.5]))
    malformed = copy.deepcopy(e.doc); malformed['items'][0]['box'][0] = float('nan')
    try: M.valid(malformed)
    except ValueError: pass
    else: raise AssertionError('nonfinite box accepted')
    # Native graph uses the compiled JSON, with the original editable document in metadata.
    spec = importlib.util.spec_from_file_location('moss_fixture', Path(__file__).with_name('moss-test.py'))
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); fixture.models(root)
        reg = fixture.R.Registry(str(root), fixture.R.Overrides(str(root/'overrides.json')), use_cache=False)
        for entry in reg.base_models():
            built = reg.build(entry, dict(positive='Overall scene', negative='blur', width=1024, height=1024, moss_layout=e.doc))
            node = next(n for n in built['prompt'].values() if n['_meta']['painter_role'] == 'encode_pos')
            assert json.loads(node['inputs']['text'])['summary']['caption'] == 'Overall scene'
            assert built['params']['moss_layout'] == e.doc
            assert built['params']['prompt_boxes']['positive'] == 'Overall scene'
    draft = dict(width=1536, height=1024, bbox_coord_space='abs', bbox_format='xyxy',
                 summary=dict(caption='A campaign', canvas='single', meta=['poster']),
                 items=[dict(label='text', caption='Green title', text='旅へ\nEXPLORE',
                             bbox=[928, 272, 1408, 448], tags=['title'], palette=['green'])])
    raw = json.dumps(draft)
    imported = M.import_prompt(dict(positive=raw, negative='blur', width=1024, height=1024))
    assert imported['positive'] == 'A campaign' and imported['negative'] == 'blur'
    assert imported['width'] == 1536 and imported['height'] == 1024
    doc = imported['moss_layout']
    assert doc['items'][0]['box'] == [928/1536, 272/1024, 480/1536, 176/1024]
    conditioning = M.compile(doc)
    assert json.loads(conditioning)['items'][0]['bbox'] == [-240, 160, -64, 640]
    assert json.loads(M.compile(M.parse_prompt(conditioning, 1536, 1024))) == json.loads(conditioning)
    assert M.parse_prompt('```json\n' + raw + '\n```')['summary']['caption'] == 'A campaign'
    literal = dict(positive=raw, negative='literal negative')
    legacy = dict(positive=conditioning, prompt_boxes=literal, width=1536, height=1024)
    restored = M.import_prompt(legacy)
    assert restored['prompt_boxes']['positive'] == 'A campaign'
    assert legacy['prompt_boxes'] == literal
    stale = M.import_prompt(dict(legacy, moss_layout=M.fresh()))
    assert stale['moss_layout']['items'][0]['box'] == doc['items'][0]['box']
    saved = dict(restored, moss_layout=dict(doc, reference='/keep/me'))
    assert M.import_prompt(saved) == saved
    for bad in ('plain prose', '{"items":', raw.replace('928', '1928'), raw.replace('"xyxy"', '"unknown"')):
        value = dict(positive=bad)
        assert M.import_prompt(value) == value
    with tempfile.TemporaryDirectory() as tmp:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pylib'))
        import outmeta, pngmeta
        path = Path(tmp) / 'legacy.png'
        # Metadata reading needs no pixel decoding.
        png = pngmeta.SIG + pngmeta._chunk(b'IDAT', b'') + pngmeta._chunk(b'IEND', b'')
        path.write_bytes(pngmeta.upsert_text(png, {'painter': json.dumps(legacy)}))
        assert outmeta.params_for(path)['moss_layout']['items'][0]['box'] == doc['items'][0]['box']
        fixture.models(Path(tmp))
        reg = fixture.R.Registry(tmp, fixture.R.Overrides(str(Path(tmp)/'overrides.json')), use_cache=False)
        for entry in reg.base_models():
            built = reg.build(entry, dict(positive=raw))
            assert built['params']['prompt_boxes']['positive'] == 'A campaign'
            assert built['params']['width'] == 1536
            assert json.loads(built['params']['positive']) == json.loads(conditioning)
            legacy_graph = outmeta.params_from_graph(built['prompt'])
            assert legacy_graph['positive'] == 'A campaign'
            assert legacy_graph['moss_layout']['items'][0]['box'] == doc['items'][0]['box']
    preview = M.Editor(M.fresh())
    preview.add('character', [.1, .1, .8, .8])['caption'] = 'Red coat & blue scarf <bright>'
    svg = M.svg(preview, 700, 700)[0].decode('utf-8')
    assert M.REGION_ICONS['character'] + ' Red coat &amp; blue scarf &lt;bright&gt;' in svg
    assert 'clip-path="url(#label0)"' in svg
    preview.chosen()[0]['caption'] = 'long description ' * 100
    import xml.etree.ElementTree as ET
    rendered = ET.fromstring(M.svg(preview, 700, 700)[0])
    ns = {'s': 'http://www.w3.org/2000/svg'}
    labels = rendered.findall('.//s:text', ns)
    assert len(labels) > 1 and all(t.attrib['fill'] == '#ffb454' for t in labels)
    themed = ET.fromstring(M.svg(preview, 700, 700, font=dict(
        family='sans-serif', size=11, height=13, weight=400, style='normal',
        selected='#123abc'))[0])
    assert all(t.attrib['fill'] == '#123abc' for t in themed.findall('.//s:text', ns))
    assert any(r.attrib.get('stroke') == '#123abc' for r in themed.findall('.//s:rect', ns))
    assert '…' not in ''.join(t.text or '' for t in labels)
    assert rendered.find('s:g/s:rect', ns).attrib['fill'] == 'none'
    row = preview.add('text', [.1, .1, .3, .8])
    row['caption'] = 'Title'
    row['text'] = 'A long line of exact wording that should wrap\nA second explicit line'
    row['typography']['color'] = '#ff0000'
    before = copy.deepcopy(preview.doc)
    rendered = ET.fromstring(M.svg(preview, 700, 700)[0])
    wording = [t for t in rendered.findall('.//s:text', ns) if 'text-anchor' in t.attrib]
    assert len(wording) > 2
    assert all(t.attrib['fill'] == '#ffb454' and 'clip-path' in t.attrib for t in wording)
    assert preview.doc == before, 'visual wrapping must not change generation wording or colours'
    rendered = ET.fromstring(M.svg(preview, 700, 700, font=dict(
        family='Ubuntu', size=14, height=18, weight=400, style='normal'))[0])
    assert all(t.attrib['font-family'] == 'Ubuntu' and float(t.attrib['font-size']) == 14
               and t.attrib['font-weight'] == '400' and 'stroke' not in t.attrib
               for t in rendered.findall('.//s:text', ns))
    assert not any('fill-opacity' in r.attrib for r in rendered.findall('.//s:rect', ns))
    preview.selected = []
    rendered = ET.fromstring(M.svg(preview, 700, 700, font=dict(
        family='Ubuntu', size=14, height=18, weight=400, style='normal', inactive='#8a8a8a'))[0])
    assert all(t.attrib['fill'] == '#8a8a8a' for t in rendered.findall('.//s:text', ns))
    print('PASS: layout compiler, rescaling, geometry, locks, groups, undo and both MOSS graphs')


def qt():
    assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
    from PySide6 import QtGui as G
    from layout_qt import Toolkit
    from layout_ui import LayoutUI
    app = G.QGuiApplication([])
    assert app.platformName() == 'offscreen'
    ui = Toolkit()
    accepted = []
    editor = LayoutUI(ui, M.fresh(caption='A poster'), accepted.append)
    before_toggle = copy.deepcopy(editor.model.doc)
    editor.preview_toggle.edit(False)
    assert not editor.canvas.shown
    assert editor.model.doc == before_toggle
    editor.preview_toggle.edit(True)
    assert editor.canvas.shown
    app.processEvents()
    editor.render(700, 500)
    cursor = (233, 177)
    ox, oy, w, h = editor.rect
    location = ((cursor[0] - ox) / w, (cursor[1] - oy) / h)
    for steps in (1, 2, -1, -.5):
        editor.zoom_at(cursor[0], cursor[1], steps)
        ox, oy, w, h = editor.rect
        assert abs((cursor[0] - ox) / w - location[0]) < 1e-8
        assert abs((cursor[1] - oy) / h - location[1]) < 1e-8
    editor.pan_pointer('press', 10, 10)
    before_pan = editor.rect
    editor.pan_pointer('release', 35, 45)
    assert editor.rect[:2] == (before_pan[0] + 25, before_pan[1] + 35)
    editor.zoom, editor.pan = 1, [0, 0]
    editor.render(700, 500)
    ox, oy, w, h = editor.rect
    editor.arm_add()
    editor.pointer('press', ox - 10, oy + h * .2)
    editor.pointer('move', ox + w * 1.2, oy + h * .8)
    assert not accepted, 'unfinished outside geometry must not autosave'
    # Release position matters even when there was no final motion event.
    editor.pointer('release', ox + w * .6, oy + h * .7)
    assert len(accepted) == 1
    assert all(abs(x-y) < 1e-8 for x,y in zip(accepted[-1]['items'][0]['box'], [0,.2,.6,.5]))
    M.valid(accepted[-1])
    editor.model.undo(); editor.refresh()
    editor.model.add('object', [.1,.1,.6,.3]); editor.refresh()
    editor.tool.edit('text')
    assert editor.model.chosen()[0]['label'] == 'text'
    editor.model.undo(); editor.refresh()
    assert editor.model.chosen()[0]['label'] == 'object'
    editor.tool.edit('text')
    assert 'item.label' not in editor.fields
    editor.fields['item.caption'].edit('Large headline')
    editor.fields['item.text'].edit('Hello\n世界')
    editor.fields['type.family'].edit('serif')
    editor.fields['item.palette'].edit('#ff0000, #00ff00')
    editor.fields['enabled'].edit(True)
    assert editor.model.doc['items'][0]['text'] == 'Hello\n世界'
    assert editor.model.doc['items'][0]['palette'] == ['#ff0000','#00ff00']
    pending = []
    ui.generate_tags = lambda request, callback: pending.append((request, callback))
    editor.tag_count.edit(3)
    editor.auto_tags()
    assert pending[-1][0]['count'] == 3 and editor.tag_busy
    assert not editor.tag_auto.enabled
    pending[-1][1](dict(tags=['lettering', 'headline', 'poster'], error=''))
    assert editor.row()['tags'] == ['lettering', 'headline', 'poster']
    editor.model.undo(); editor.refresh()
    assert editor.row()['tags'] == []
    editor.auto_tags()
    editor.fields['item.tags'].edit('hand edited')
    pending[-1][1](dict(tags=['stale'], error=''))
    assert editor.row()['tags'] == ['hand edited'], 'overwrote edits made during inference'
    editor.auto_tags()
    ui.model_name = 'another model'
    pending[-1][1](dict(tags=['wrong model'], error=''))
    assert editor.row()['tags'] == ['hand edited'] and editor.tag_auto.enabled
    editor.prompt_tokens.edit(48)
    before_prompt = editor.row()['caption']
    editor.prompt_auto.activate()
    assert pending[-1][0]['task'] == 'prompt' and pending[-1][0]['tokens'] == 48
    assert pending[-1][0]['palette'] == ['#ff0000', '#00ff00']
    assert not editor.tag_auto.enabled and not editor.prompt_revert.enabled
    pending[-1][1](dict(prompt='A large, ornate headline.', error=''))
    assert editor.row()['caption'] == 'A large, ornate headline.'
    assert editor.prompt_revert.enabled
    editor.fields['item.tags'].edit('keep these tags')
    editor.prompt_revert.activate()
    assert editor.row()['caption'] == before_prompt and editor.row()['tags'] == ['keep these tags']
    assert not editor.prompt_revert.enabled
    editor.prompt_auto.activate()
    editor.fields['item.caption'].edit('New manual prompt')
    pending[-1][1](dict(prompt='Stale generated prompt.', error=''))
    assert editor.row()['caption'] == 'New manual prompt' and not editor.prompt_revert.enabled
    editor.units.edit('pixels')
    editor.fields['box.position'].edit('128, 102.4')
    assert editor.model.doc['items'][0]['box'][0] == .125
    editor.key('Right')
    assert editor.model.doc['items'][0]['box'][0] == .125 + 1/1024
    editor.key('z', True)
    assert editor.model.doc['items'][0]['box'][0] == .125
    editor.key('Z', True, True)
    assert editor.model.doc['items'][0]['box'][0] == .125 + 1/1024
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / 'ref.png')
        image = G.QImage(80,60,G.QImage.Format_RGB32); image.fill(G.QColor('red')); image.save(path)
        editor.set_reference(path); editor.refresh()
        assert editor.reference
        assert b'data:image/png;base64,' in editor.render(700,600)
        app.processEvents()
    restored = copy.deepcopy(editor.model.doc)
    restored['summary']['caption'] = 'Reloaded scene'
    editor.load(restored)
    editor.model.select(editor.model.doc['items'][0]['id'])
    editor.buttons['Lock'].activate()
    assert not editor.model.selected
    editor.model.press(.4, .2); editor.model.release()
    assert not editor.model.selected
    editor.model.press(0, 0); editor.model.motion(1, 1); editor.model.release()
    assert not editor.model.selected
    editor.selection_changed([editor.model.doc['items'][0]['id']])
    assert editor.model.selected
    editor.buttons['Delete'].activate()
    assert not editor.model.doc['items']
    editor.model.undo(); editor.refresh()
    editor.selection_changed([editor.model.doc['items'][0]['id']])
    editor.buttons['Duplicate'].activate()
    assert len(editor.model.doc['items']) == 2
    editor.model.undo(); editor.refresh()
    editor.selection_changed([editor.model.doc['items'][0]['id']])
    # Clipboard methods are replaced: never touch the host clipboard in a test.
    copied = []
    ui.copy = copied.append
    ui.paste = lambda: copied[0]
    editor.copy(); editor.paste()
    assert len(editor.model.doc['items']) == 2
    editor.publish(); assert accepted and accepted[-1]['enabled']
    editor.model.selected = []
    editor.model.doc['items'][0]['locked'] = True
    locked = editor.model.doc['items'][0]
    editor.model.doc['snap'] = False
    editor.selection_changed([locked['id']])
    assert not editor.fields['box.position'].enabled and not editor.fields['box.size'].enabled
    original_box = list(locked['box'])
    undo_count = len(editor.model.undo_stack)
    editor.units.edit('pixels')
    editor.fields['box.position'].edit('100, 100')
    editor.key('Right')
    assert locked['box'] == original_box and len(editor.model.undo_stack) == undo_count
    editor.model.doc['items'] = [editor.row()]
    row = editor.row()
    row['box'] = [.1, .1, .6, .6]
    for x, y, jitter in ((.3, .3, 0), (.3, .3, .002), (.1, .1, .1), (.3, .3, .1)):
        editor.selection_changed([row['id']])
        before_click = copy.deepcopy(editor.model.doc)
        undo_count = len(editor.model.undo_stack)
        editor.model.press(x, y)
        assert not editor.model.selected and editor.model.drag is None
        editor.model.motion(x + jitter, y + jitter)
        editor.model.release()
        editor.refresh()
        assert editor.model.doc == before_click and len(editor.model.undo_stack) == undo_count
        assert not editor.fields['box.position'].enabled
    editor.selection_changed([])
    editor.model.press(.3, .3)
    assert editor.model.drag[0] == 'marquee', 'canvas selected a locked region'
    editor.model.release()

    # The retained Qt canvas must hide locked content
    # under transparent unlocked boxes, including overlapping occluders.
    from layout_qt import Bridge, LayoutCanvas
    b = Bridge()
    e = b.editor.model
    e.doc['guides'] = 'none'
    e.doc['grid'] = False
    e.add('object', [.2, .2, .3, .3]).update(caption='Foreground')
    e.add('object', [.35, .35, .25, .25])
    backdrop = e.add('object', [.1, .1, .8, .8])
    backdrop.update(locked=True, palette=['blue'], caption='Backdrop')
    e.selected = []
    b.editor.refresh()
    canvas = LayoutCanvas()
    canvas.set_bridge(b)
    canvas.setWidth(500); canvas.setHeight(500)
    for scale in (1, 2):
        image = G.QImage(500 * scale, 500 * scale, G.QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(G.QColor('transparent'))
        painter = G.QPainter(image)
        canvas.paint(painter)
        painter.end()
        ox, oy, w, h = b.editor.rect
        for x, y in ((.28, .3), (.42, .43)):
            assert image.pixelColor(int((ox+x*w)*scale), int((oy+y*h)*scale)).alpha() == 0, ('locked region leaked through', scale)
        assert image.pixelColor(int((ox+.7*w)*scale), int((oy+.7*h)*scale)).alpha() > 0
    misses = canvas._layers.misses
    e.doc['items'][0]['box'][0] += .02
    painter = G.QPainter(image)
    canvas.paint(painter)
    painter.end()
    assert canvas._layers.misses == misses, 'occlusion invalidated cached background pixels'
    b.editor.zoom = 16
    for _, pw, ph, _, _, _ in b.editor.render(500, 500, layers=True):
        assert pw <= 500 and ph <= 500, 'zoom allocated oversized layer'
    b.editor.zoom = 1
    svg = b.editor.render(500, 500)
    assert b'#808080' in svg
    assert svg.index(b'Backdrop') < svg.index(b'Foreground'), 'locked region painted over unlocked region'
    before_clear = copy.deepcopy(editor.model.doc)
    editor.paint()
    assert editor.buttons['Clear all']._enabled
    editor.buttons['Clear all'].activate()
    assert not accepted[-1]['items'] and not accepted[-1]['enabled']
    assert accepted[-1]['summary'] == before_clear['summary']
    assert accepted[-1]['reference'] == before_clear['reference']
    assert not editor.buttons['Clear all']._enabled
    editor.key('z', True)
    assert editor.model.doc == before_clear
    editor.key('z', True, True)
    assert not editor.model.doc['items']
    print('PASS: native Qt layout form, palette, multiline text, pixels, underlay and autosave')


if __name__ == '__main__':
    core()
    if '--qt' in sys.argv: qt()

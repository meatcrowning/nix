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
    preview = M.Editor(M.fresh())
    preview.add('character', [.1, .1, .8, .8])['caption'] = 'Red coat & blue scarf <bright>'
    svg = M.svg(preview, 700, 700)[0].decode('utf-8')
    assert '1 character — Red coat &amp; blue scarf &lt;bright&gt;' in svg
    assert 'clip-path="url(#label0)"' in svg
    preview.chosen()[0]['caption'] = 'long description ' * 100
    import xml.etree.ElementTree as ET
    rendered = ET.fromstring(M.svg(preview, 700, 700)[0])
    ns = {'s': 'http://www.w3.org/2000/svg'}
    labels = rendered.findall('.//s:text', ns)
    assert len(labels) > 1 and all(t.attrib['fill'] == '#ffb454' for t in labels)
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

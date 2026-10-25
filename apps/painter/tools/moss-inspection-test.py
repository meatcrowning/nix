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
from PySide6.QtCore import QObject, Signal, Slot, Qt
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
    editor.forceActiveFocus()
    editor.setProperty('cursorPosition', 10)
    u.key(win, Qt.Key_X, Qt.NoModifier, 'x')
    assert editor.property('text') == 'red spherex'
    u.key(win, Qt.Key_Z, Qt.ControlModifier, 'z')
    assert editor.property('text') == 'red sphere'
    assert probe.property('count') == -1
    print('PASS debounce, stale replies, editable token lines and native undo')

    doc = dict(version=1, width=2, height=2, tokens=[dict(index=0, text='red', visible=True)])
    packet = moss_data.encode(doc, bytes([0, 255, 0, 255]))
    assert moss_data.decode(packet) == (doc, bytes([0, 255, 0, 255]))
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
    from PySide6.QtCore import QUrl
    assert QImage(QUrl(ctl.inspection.overlay).toLocalFile()) != original
    old_output = Path(tmp) / 'old.png'
    old_output.write_bytes(plain)
    gallery.setProperty('selection', [str(old_output)])
    u.spin(50)
    assert not root.property('showHeatmap') and not ctl.inspection.available
    assert not u.WARNINGS, u.WARNINGS
    ctl.inspection.close()
    print('PASS PNG persistence, unchanged image pixels, viewer maps and selection invalidation')

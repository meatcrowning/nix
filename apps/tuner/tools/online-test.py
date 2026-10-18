#!/usr/bin/env python3
"""Offline feed and display checks: no GTK, receiver, audio, or network."""
import ast
import io
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import online

class Response(io.BytesIO):
    headers = {}

def feed(raw, source=None, headers=None):
    response = Response(raw)
    response.headers = headers or {}
    with patch.object(online.urllib.request, 'urlopen', return_value=response):
        return online.fetch({'url': 'https://example.test/feed', **(source or {})})

assert feed(b'{"nowPlaying":{"artistName":"A","songTitle":"B"}}') == 'A - B'
assert feed(b'{"nowPlaying":null}') == ''
markup = '<tr data-spin="{&quot;a&quot;:&quot;A &amp; B&quot;,&quot;s&quot;:&quot;Song&quot;}"></tr>'
assert feed(('_spinitron0123(' + json.dumps(markup) + ');').encode(),
            {'kind': 'spinitron'}) == 'Last logged: A & B - Song'
metadata = b"StreamTitle='Artist - Song';".ljust(32, b'\0')
assert feed(b'1234\0' + b'1234\2' + metadata, {'kind': 'icy'}, {'icy-metaint': '4'}) == 'Artist - Song'
assert feed(b'', {'kind': 'icy'}) == ''
for raw in (b'{', b'x' * (online.LIMIT + 1)):
    try: feed(raw)
    except ValueError: pass
    else: raise AssertionError('Invalid/oversized feed accepted')

clock = [100.0]
started, release = threading.Event(), threading.Event()
def delayed(source):
    started.set()
    assert release.wait(2)
    return 'old station song'
client = online.Client({'A': {'url': 'test'}, 'B': {'url': 'test'}}, delayed, lambda: clock[0])
client.poll((1, 'A'), 'A'); assert started.wait(1)
client.poll((2, 'B'), 'B')
release.set()
def wait_idle(c):
    limit = time.monotonic() + 2
    while c.busy and time.monotonic() < limit: time.sleep(.005)
    assert not c.busy
wait_idle(client)
assert client.text == ''  # late A cannot populate B, even before B is fetched
calls = []
client.fetcher = lambda s: calls.append(s) or 'new song'
client.poll((2, 'B'), 'B'); wait_idle(client)
assert client.poll((2, 'B'), 'B')[0] == 'new song' and len(calls) == 1
clock[0] += 31
client.fetcher = lambda s: (_ for _ in ()).throw(OSError('offline'))
client.poll((2, 'B'), 'B'); wait_idle(client)
assert client.poll((2, 'B'), 'B') == ('', 'Online text unavailable')
# Expiration also hides a previously successful response while a refresh stalls.
client.text, client.seen, client.busy = 'expired song', clock[0] - 91, True
assert client.poll((2, 'B'), 'B')[0] == ''
client.close(); assert client.poll((2, 'B'), 'B')[0] == ''

# Exercise the actual display method without importing/starting GTK or hardware.
tree = ast.parse((Path(__file__).resolve().parent.parent / 'main.py').read_text())
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TunerWindow')
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_refresh_rds')
namespace = {'time': time, 'online': online, 'dsp': NS(WFM_MODES=('WFM (stereo)', 'WFM (mono)'))}
exec(compile(ast.Module(body=[method], type_ignores=[]), 'main.py', 'exec'), namespace)
shown = []
class FakeOnline:
    def poll(self, key, name):
        self.key = key
        return 'Artist - Song', 'Online stream may differ from FM'
w = NS(s={'hd': False, 'frequency': 99000000}, rx={'mode': 'WFM (stereo)'},
       radio=NS(running=True, metadata_generation=1), rds_data={}, rds_seen=0,
       online=FakeOnline(), bookmarks=NS(items=[NS(freq=99000000, name='TEST FM', mode='WFM (stereo)')]),
       rds_display=NS(set_message=lambda *args: shown.append(args)))
refresh = lambda: namespace['_refresh_rds'](w)
refresh(); assert 'Online' in shown[-1][0] and shown[-1][1] == 'Artist - Song'
w.rds_data = {'pi': '0x1234', 'ps': 'TEST', 'radiotext': 'Broadcast text'}
w.rds_seen = time.monotonic()
refresh(); assert shown[-1][1] == 'Broadcast text' and w.online.key is None
w.rds_seen -= 11
refresh(); assert shown[-1][1] == 'Artist - Song'
w.s['frequency'] += 100000
refresh(); assert 'Artist' not in shown[-1][1] and w.online.key is None
w.s['frequency'] = 99000000; w.radio.running = False
refresh(); assert shown[-1][1] == 'Receiver stopped'
w.radio.running = True; w.rx['mode'] = 'AM'
refresh(); assert 'Artist' not in shown[-1][1]
w.s['hd'] = True; w._refresh_hd = lambda: shown.append(('HD',))
refresh(); assert shown[-1] == ('HD',) and w.online.key is None
w.bookmarks.items.append(NS(freq=99000000, name='Different', mode='WFM (stereo)'))
assert online.bookmark_name(w.bookmarks.items, 99000000) == ''
print('PASS JSON, ICY, playlist parsing, bounded responses, stale replies, polling, failure clearing, RDS priority, retune, stop, mode and HD isolation')

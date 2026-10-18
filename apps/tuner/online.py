"""Optional station text from local, explicitly associated public feeds.

No audio is played or stored. A single bounded worker polls only the current
station; generation changes discard in-flight replies. Configuration lives
beside settings.json in online.json, keyed by the exact confirmed bookmark name.
"""
from html.parser import HTMLParser
import json
import re
import threading
import time
import urllib.request
from pathlib import Path

LIMIT = 256 * 1024


def clean(value):
    return ' '.join(value.split())[:512] if isinstance(value, str) else ''


def load_sources(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def bookmark_name(items, frequency):
    names = {b.name.strip() for b in items if b.freq == frequency
             and 87500000 <= b.freq <= 108000000
             and b.mode in ('WFM (mono)', 'WFM (stereo)', 'WFM') and b.name.strip()}
    return names.pop() if len(names) == 1 else ''


def fetch(source):
    url = source.get('url', '')
    if not url.startswith('https://'):
        raise ValueError('Online feeds require HTTPS')
    request = urllib.request.Request(url, headers={'User-Agent': 'Tuner/1.0',
                                                  'Icy-MetaData': '1'})
    with urllib.request.urlopen(request, timeout=5) as response:
        kind = source.get('kind', 'json')
        if kind == 'icy':
            interval = int(response.headers.get('icy-metaint', '0'))
            if not 0 < interval <= LIMIT:
                return ''
            # Read at most a few metadata intervals, never the continuous stream.
            deadline = time.monotonic() + 10
            for _ in range(min(8, LIMIT // interval)):
                if time.monotonic() >= deadline:
                    break
                if len(response.read(interval)) != interval:
                    break
                size = response.read(1)
                if not size:
                    break
                raw = response.read(size[0] * 16).decode('utf-8', errors='replace')
                match = re.search(r"StreamTitle='(.*?)';", raw)
                if match:
                    return clean(match[1])
            return ''
        raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Feed exceeds size limit')
    if kind == 'spinitron':
        # Public widget data, not executable JavaScript. Never eval JSONP.
        text = raw.decode('utf-8')
        match = re.fullmatch(r'_spinitron[0-9]+\((.*)\);?\s*', text, re.S)
        if not match:
            raise ValueError('Invalid widget response')
        markup = json.loads(match[1])
        class Spin(HTMLParser):
            track = None
            def handle_starttag(self, tag, attrs):
                value = dict(attrs).get('data-spin')
                if value and self.track is None:
                    self.track = json.loads(value)
        parser = Spin()
        parser.feed(markup)
        track = parser.track
        if not isinstance(track, dict) or not clean(track.get('s')):
            return ''
        return 'Last logged: ' + ' - '.join(filter(None, (
            clean(track.get('a')), clean(track.get('s')))))
    if kind != 'json':
        raise ValueError('Unknown feed type')
    data = json.loads(raw)
    def field(path):
        value = data
        for part in path.split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        return clean(value)
    title = field(source.get('title', 'nowPlaying.songTitle'))
    artist = field(source.get('artist', 'nowPlaying.artistName'))
    return ' - '.join(filter(None, (artist, title))) if title else ''


class Client:
    def __init__(self, sources, fetcher=fetch, clock=time.monotonic):
        self.sources, self.fetcher, self.clock = sources, fetcher, clock
        self.lock = threading.Lock()
        self.key = None
        self.serial = 0
        self.busy = False
        self.closed = False
        self.next_poll = 0
        self.text = ''
        self.seen = 0
        self.status = ''

    def poll(self, key, name):
        with self.lock:
            if key != self.key:
                self.key = key
                self.serial += 1
                self.text, self.seen, self.next_poll = '', 0, 0
                self.status = ''
            source = self.sources.get(name)
            now = self.clock()
            if not isinstance(source, dict) or not source.get('url'):
                return '', 'No online feed configured'
            if self.closed:
                return '', ''
            if not self.busy and now >= self.next_poll:
                self.busy = True
                self.next_poll = now + 30
                self.status = 'Checking online text'
                threading.Thread(target=self._fetch, args=(self.serial, dict(source)),
                                 name='station-text', daemon=True).start()
            return (self.text if now - self.seen < 90 else ''), self.status

    def _fetch(self, serial, source):
        try:
            text = self.fetcher(source)
            status = 'Online stream may differ from FM' if text else 'No online song text'
        except Exception:
            text, status = '', 'Online text unavailable'
        with self.lock:
            self.busy = False
            if serial != self.serial or self.closed:
                return
            self.text, self.seen, self.status = text, self.clock(), status

    def close(self):
        with self.lock:
            self.closed = True
            self.serial += 1
            self.text = ''

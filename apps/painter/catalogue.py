"""Versioned, cacheable discovery over Painter's existing loopback SSH forward.

Network functions belong on workers. UI metadata lookups use only the published
in-memory snapshot. Output paths retain the peer mount for full-resolution opens.
"""
from __future__ import annotations
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import threading
import urllib.parse
import urllib.request

VERSION = 1
MAX_REPLY = 32 * 1024 * 1024
_lock = threading.RLock()
_outputs = {}


def enabled():
    return os.environ.get('PAINTER_CATALOGUE', '') == '1'


def cache_root():
    identity = os.environ.get('PAINTER_CATALOGUE_ID', 'top')
    key = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'painter' / 'catalogue' / key


def safe_relative(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '..' in p.parts or '\\' in value:
        raise ValueError('Invalid catalogue path')
    return p


def atomic_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.catalogue-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(doc, f, separators=(',', ':'))
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _cached(name):
    try:
        doc = json.loads((cache_root() / (name + '.json')).read_text())
        return doc if doc.get('version') == VERSION else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _get(route, query=None, limit=MAX_REPLY):
    base = os.environ.get('PAINTER_COMFY_URL', 'http://127.0.0.1:8188').rstrip('/')
    url = base + '/painter/catalogue/' + route
    if query:
        url += '?' + urllib.parse.urlencode(query)
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            raw = response.read(limit + 1)
    except http.client.HTTPException as exc:
        raise OSError('Incomplete catalogue response') from exc
    if len(raw) > limit:
        raise ValueError('Catalogue response exceeds its byte limit')
    return raw


def _fetch(name, previous):
    doc = json.loads(_get(name, {'since': previous.get('revision', '')}))
    if not isinstance(doc, dict) or doc.get('version') != VERSION:
        raise ValueError('Unsupported Painter catalogue version')
    if doc.get('unchanged'):
        return previous
    return doc


def models(root):
    previous = _cached('models')
    try:
        doc = _fetch('models', previous)
        rows = doc['models']
        for row in rows:
            safe_relative(row['relative'])
        atomic_json(cache_root() / 'models.json', doc)
    except (OSError, ValueError, KeyError, TypeError):
        if not previous:
            raise RuntimeError('Model catalogue unavailable; waiting for the backend. '
                               'For an older backend, set PAINTER_CATALOGUE=0 to use SSHFS.')
        doc = previous
    return [dict(row, path=str(Path(root) / safe_relative(row['relative']))) for row in doc['models']]


def outputs(peer_root):
    previous = _cached('outputs')
    try:
        doc = _fetch('outputs', previous)
        if doc.get('delta'):
            merged = {r['relative']: r for r in previous.get('outputs', [])}
            for name in doc.get('removed', []):
                merged.pop(name, None)
            merged.update({r['relative']: r for r in doc['outputs']})
            doc = dict(version=VERSION, revision=doc['revision'], outputs=list(merged.values()))
        for row in doc['outputs']:
            safe_relative(row['relative'])
        atomic_json(cache_root() / 'outputs.json', doc)
    except (OSError, ValueError, KeyError, TypeError):
        doc = previous
    rows = []
    for row in doc.get('outputs', []):
        path = str(Path(peer_root) / safe_relative(row['relative']))
        rows.append(dict(row, path=path))
    with _lock:
        _outputs.clear()
        _outputs.update({r['path']: r for r in rows})
    return rows


def output(path):
    with _lock:
        return _outputs.get(str(path))


def thumbnail(path, dest):
    row = output(path)
    if row is None:
        return False
    raw = _get('thumbnail', {'path': row['relative'], 'stamp': row['stamp']}, 2 * 1024 * 1024)
    if not raw.startswith(b'\xff\xd8'):
        raise ValueError('Invalid catalogue thumbnail')
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.thumb-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
        os.replace(tmp, dest)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return True


def trim_display_cache(folder, budget=256 * 1024 * 1024):
    """Bound only our disposable display PNGs; never touch source outputs."""
    rows = []
    for path in Path(folder).glob('*.png'):
        try:
            st = path.stat()
            rows.append((st.st_mtime_ns, st.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in rows)
    for _, size, path in sorted(rows):
        if total <= budget:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def display_image(path):
    """Fetch a lossless, metadata-free display copy on a worker, if supported."""
    row = output(path)
    if row is None:
        return path
    key = hashlib.sha256((row['relative'] + ':' + row['stamp']).encode()).hexdigest()
    folder = cache_root() / 'display'
    dest = folder / (key + '.png')
    if dest.is_file():
        dest.touch()
        return str(dest)
    raw = _get('display', {'path': row['relative'], 'stamp': row['stamp']}, 64 * 1024 * 1024)
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Invalid display image')
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.display-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        os.replace(tmp, dest)
        trim_display_cache(folder)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return str(dest)

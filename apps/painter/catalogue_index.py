"""Backend catalogue implementation; no GPU, Qt, or server imports."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from catalogue import VERSION, safe_relative
import fingerprint as fp


def revision(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class CatalogueIndex:
    def __init__(self, models, outputs, cache):
        self.model_root, self.output_root, self.cache = map(Path, (models, outputs, cache))
        self.lock = threading.RLock()
        self.thumb_slots = threading.BoundedSemaphore(2)
        self._models, self._outputs = {}, {}
        self._previous = {}
        self._model_time = self._output_time = -float('inf')
        self._headers = {}

    def models(self, since=''):
        with self.lock:
            if time.monotonic() - self._model_time > 15:
                rows = []
                for res in fp.scan([str(self.model_root)]):
                    p = Path(res['path'])
                    # Preserve symlink names in the public catalogue, not targets.
                    relative = p.relative_to(self.model_root).as_posix()
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    stamp = (st.st_mtime_ns, st.st_size)
                    row = dict(res, relative=relative)
                    row.pop('path', None)
                    if res.get('role') in ('diffusion', 'checkpoint', 'lora'):
                        cached = self._headers.get(relative)
                        if cached and cached[0] == stamp:
                            row.update(cached[1])
                        else:
                            info = dict(targets=[]) if res['role'] == 'lora' else dict(keys=[])
                            try:
                                header = fp.read_header(str(p))
                                if res['role'] == 'lora':
                                    targets, kohya, te, _ = fp.lora_targets(header)
                                    info = dict(targets=sorted(targets), kohya=kohya, patches_clip=te)
                                else:
                                    view = fp.View(header, 'model.diffusion_model.') if res['role'] == 'checkpoint' else fp.best_view(header)
                                    info = dict(keys=sorted(view.keys))
                            except (OSError, ValueError, fp.BadHeader):
                                pass
                            self._headers[relative] = (stamp, info)
                            row.update(info)
                    rows.append(row)
                self._models = dict(version=VERSION, revision=revision(rows), models=rows)
                self._model_time = time.monotonic()
            if since == self._models['revision']:
                return dict(version=VERSION, revision=since, unchanged=True)
            return self._models

    def outputs(self, since=''):
        with self.lock:
            if time.monotonic() - self._output_time > 2:
                old = {r['relative']: r for r in self._outputs.get('outputs', [])}
                rows = []
                paths = list(self.output_root.glob('*.png'))
                for ext in ('.mp4', '.mkv', '.webm'):
                    paths.extend(self.output_root.glob('video/*' + ext))
                for p in paths:
                    if p.stem.endswith('-muted'):
                        continue
                    try:
                        st = p.stat()
                        relative = p.relative_to(self.output_root).as_posix()
                        stamp = '%d-%d' % (st.st_mtime_ns, st.st_size)
                        if relative in old and old[relative]['stamp'] == stamp:
                            rows.append(old[relative])
                            continue
                        import outmeta
                        params = outmeta.params_for(str(p)) or {}
                        rows.append(dict(relative=relative, stamp=stamp, size=st.st_size,
                                         mtime=st.st_mtime, params=params))
                    except (OSError, ValueError):
                        continue
                current = dict(version=VERSION, revision=revision(rows), outputs=rows)
                if current['revision'] != self._outputs.get('revision'):
                    self._previous = self._outputs
                    self._outputs = current
                self._output_time = time.monotonic()
            if since == self._outputs['revision']:
                return dict(version=VERSION, revision=since, unchanged=True)
            if since and since == self._previous.get('revision'):
                old = {r['relative']: r for r in self._previous['outputs']}
                new = {r['relative']: r for r in self._outputs['outputs']}
                return dict(version=VERSION, revision=self._outputs['revision'], delta=True,
                            removed=sorted(old.keys() - new.keys()),
                            outputs=[r for name, r in new.items() if old.get(name) != r])
            return self._outputs

    def thumbnail(self, relative, stamp):
        rel = safe_relative(relative)
        path = self.output_root / rel
        # Refuse symlinks escaping output root as well as traversal.
        if not path.resolve().is_relative_to(self.output_root.resolve()):
            raise ValueError('Output outside catalogue root')
        if path.suffix.lower() not in ('.png', '.mp4', '.mkv', '.webm'):
            raise ValueError('Unsupported output')
        st = path.stat()
        if stamp != '%d-%d' % (st.st_mtime_ns, st.st_size):
            raise ValueError('Output changed; refresh the catalogue')
        dest = self.cache / (hashlib.sha256((relative + ':' + stamp).encode()).hexdigest() + '.jpg')
        with self.thumb_slots:
            if dest.exists():
                return dest
            self.cache.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.cache) as work:
                tmp = Path(work) / 'thumb.jpg'
                if path.suffix.lower() == '.png':
                    from PIL import Image
                    with Image.open(path) as image:
                        image.thumbnail((560, 560))
                        image.convert('RGB').save(tmp, 'JPEG', quality=86)
                else:
                    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
                                    '-frames:v', '1', '-vf', 'scale=560:560:force_original_aspect_ratio=decrease',
                                    '-y', str(tmp)], check=True, timeout=20, capture_output=True)
                tmp.replace(dest)
            return dest

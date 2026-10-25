#!/usr/bin/env python3
"""Install the pinned MOSS SFT correction on the ComfyUI model host."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen


def install(root):
    spec = json.loads((Path(__file__).resolve().parents[1] /
                       'families/moss_image.json').read_text())['destripe']
    dest = root / 'loras' / spec['file']
    if dest.exists():
        if hashlib.sha256(dest.read_bytes()).hexdigest() != spec['sha256']:
            raise RuntimeError('Existing file has a different checksum: ' + str(dest))
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, suffix='.download', delete=False) as out:
        temp = Path(out.name)
        try:
            with urlopen(spec['url'], timeout=60) as response:
                data = response.read(8 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != spec['sha256']:
                raise RuntimeError('Downloaded Destripe checksum mismatch')
            out.write(data)
            out.flush()
            os.chmod(temp, 0o644)
            # Do not replace another install that won the race.
            os.link(temp, dest)
        finally:
            temp.unlink(missing_ok=True)
    return dest


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('PAINTER_MODELS', '/home/lam/models')))
    print(install(parser.parse_args().root))

#!/usr/bin/env python3
"""Inspect the current Comfy environment without importing torch or loading models.

Run with Comfy's own Python. --write saves an atomic, private runtime manifest;
--compare reports drift from a previously saved manifest. It never installs or
updates packages. --check verifies required package/node discovery, not CUDA ABI.
"""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile


def git(root, *args):
    try:
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL,
                                       timeout=10).decode().strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def manifest(root):
    packages = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get('Name')
        if name:
            packages[name.lower().replace('_', '-')] = dist.version
    nodes = {}
    for name in ('painter_partial_stop.py', 'painter_moss.py', 'painter_catalogue.py',
                 'painter_qwen21.py', 'painter_krea.py'):
        path = root / 'custom_nodes' / name
        try:
            nodes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            nodes[name] = None
    custom_revisions = {}
    for path in sorted((root / "custom_nodes").glob("*")):
        if path.is_dir() and (path / ".git").exists():
            custom_revisions[path.name] = dict(revision=git(path, "rev-parse", "HEAD"),
                patch_sha256=hashlib.sha256(git(path, "diff", "HEAD", "--").encode()).hexdigest())
    return dict(version=1, python=platform.python_version(), machine=platform.machine(),
                custom_revisions=custom_revisions,
                backend_revision=git(root, 'rev-parse', 'HEAD'),
                backend_patch_sha256=hashlib.sha256(git(root, 'diff', 'HEAD', '--').encode()).hexdigest(),
                packages=dict(sorted(packages.items())), nodes=nodes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy', required=True, type=Path)
    parser.add_argument('--write', type=Path)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    doc = manifest(args.comfy)
    errors = []
    if args.check:
        for module in ('torch', 'sageattention', 'aiohttp', 'PIL'):
            if importlib.util.find_spec(module) is None:
                errors.append('missing module: ' + module)
        for name, value in doc['nodes'].items():
            if value is None:
                errors.append('missing custom node: ' + name)
    if args.compare:
        previous = json.loads(args.compare.read_text())
        changed = [key for key in doc if previous.get(key) != doc[key]]
        print('manifest drift: ' + (', '.join(changed) if changed else 'none'), file=sys.stderr)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.backend-', dir=args.write.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(doc, f, indent=2, sort_keys=True)
            os.replace(name, args.write)
        finally:
            Path(name).unlink(missing_ok=True)
    else:
        print(json.dumps(doc, indent=2, sort_keys=True))
    if errors:
        print('Painter backend precheck: ' + '; '.join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

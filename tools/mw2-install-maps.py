#!/usr/bin/env python3
"""Install a checksum manifest of MW2 assets without launching the game.

Manifest entries: path (relative to game), url, size, algorithm, hash.
Keep manifests and downloaded game assets in the host-local installation cache.
The IW4x r5149 layout is main/iw4x/x86 and zone/iw4x/x86/dlc.
Custom maps also use usermaps/<map>/<map>.arena for menu and team dependencies.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


def destination(root, entry):
    path = PurePosixPath(entry['path'])
    if path.is_absolute() or '..' in path.parts or path.suffix not in ('.ff', '.iwd', '.arena'):
        raise ValueError(f'Invalid asset path: {path}')
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Asset escapes installation: {path}')
    return target


def verified(path, entry, b3sum):
    if not path.is_file() or path.stat().st_size != entry['size']:
        return False
    if entry['algorithm'] == 'blake3':
        digest = subprocess.check_output([b3sum, str(path)], text=True).split()[0]
    elif entry['algorithm'] == 'sha1':
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha1').hexdigest()
    else:
        raise ValueError('Unsupported checksum algorithm')
    return digest.lower() == entry['hash'].lower()


def fetch(cache, entry, b3sum):
    path = destination(cache, entry)
    if verified(path, entry, b3sum):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never expose a partial or unverified download under its final name.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--retry', '3', '--connect-timeout', '30',
                            '--output', str(temporary), entry['url']], check=True)
            if not verified(temporary, entry, b3sum):
                raise ValueError(f'Checksum mismatch: {entry["path"]}')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    print(f'Verified {entry["path"]}', flush=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--b3sum', default='b3sum')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    entries = json.loads(args.manifest.read_text())
    targets = [destination(args.game, e) for e in entries]
    if len(set(targets)) != len(targets):
        raise ValueError('Manifest contains duplicate destinations')
    if args.check:
        missing = [e['path'] for e, p in zip(entries, targets) if not verified(p, e, args.b3sum)]
        print(f'{len(entries) - len(missing)}/{len(entries)} assets verified')
        if missing:
            raise SystemExit('\n'.join(missing))
        return
    cache = args.manifest.parent / 'downloads'
    needed = [e for e, p in zip(entries, targets) if not verified(p, e, args.b3sum)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda e: fetch(cache, e, args.b3sum), needed))
    # Match the launcher lock and acquire it only for installation. Downloads
    # can finish while a game is running, but its assets must not change.
    with (args.prefix / '.launcher.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if subprocess.run(['pgrep', '-x', 'iw4x.exe'], stdout=subprocess.DEVNULL).returncode == 0:
            raise SystemExit('Quit IW4x before installing; verified downloads are cached.')
        for entry, target in zip(entries, targets):
            if verified(target, entry, args.b3sum):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = destination(args.manifest.parent / 'before-install', entry)
                backup.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    raise FileExistsError(f'Preserve existing backup before retrying: {backup}')
                shutil.copy2(target, backup)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
            try:
                shutil.copyfile(destination(cache, entry), temporary)
                temporary.chmod(0o644)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    print(f'Installed {len(entries)} verified assets')


if __name__ == '__main__':
    main()

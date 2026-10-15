#!/usr/bin/env python3
"""Persist the last run's accepted Java mods and disable broken Rolling Hills.

Use only when asked to remember the user's approvals. Reads ZombieBuddy's
post-approval list, never its pre-approval list or all subscribed mods. Changed
JARs still use ZombieBuddy's normal prompts. Dry-run unless --apply is passed.
Only the default mod list and latest save's mod list are changed; backups are
stored outside the save and Workshop directories. --borderless also changes
the display mode in options.ini; --disable-mod removes additional mod IDs.
Use --skip-approvals when only changing mods or display settings.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def accepted_jars(log):
    result = set()
    active = False
    for line in log.read_text().splitlines():
        if '[ZB] java mod list after processing:' in line:
            active = True
            continue
        if active:
            match = re.search(r'\[ZB\]     \S+\s+(/.*\.jar)\s*$', line)
            if match:
                result.add(Path(match[1]))
            else:
                active = False
    if not result:
        raise ValueError('No post-approval Java mod list in log')
    return sorted(result)


def approvals(log, workshop, current):
    data = json.loads(current) if current else {'formatVersion': 2, 'mods': []}
    if data.get('formatVersion') != 2 or not isinstance(data.get('mods'), list):
        raise ValueError('Unrecognized ZombieBuddy approval format')
    known = {entry['jar_hash']: entry['decision'] for entry in data['mods']}
    added = 0
    for jar in accepted_jars(log):
        relative = jar.resolve().relative_to(workshop.resolve())
        parts = relative.parts
        if len(parts) < 5 or not parts[0].isdigit() or parts[1] != 'mods':
            raise ValueError(f'Unexpected Workshop path: {jar}')
        if jar.stat().st_mtime_ns > log.stat().st_mtime_ns:
            raise ValueError(f'JAR changed after recorded approvals: {jar}')
        root = workshop.joinpath(*parts[:3])
        info = root / parts[3] / 'mod.info'
        if not info.exists():
            info = root / 'common/mod.info'
        mod_id = re.search(r'^id=(.+)$', info.read_text(), re.M)
        if not mod_id:
            raise ValueError(f'Missing mod ID: {info}')
        sha = hashlib.sha256(jar.read_bytes()).hexdigest()
        if sha in known:
            continue  # Preserve explicit denials as well as existing approvals.
        data['mods'].append({'id': mod_id[1].strip(), 'workshop_id': int(parts[0]),
                             'jar_hash': sha, 'decision': True,
                             'time': datetime.now(timezone.utc).isoformat()})
        known[sha] = True
        added += 1
    return (json.dumps(data, indent=2) + '\n').encode(), added


def without_hills(data):
    return re.sub(rb'(?m)^[ \t]*mod = ViewpointRollingHills,[ \t]*\r?\n', b'', data)


def borderless(data):
    for key, value in [(b'fullScreen', b'false'), (b'borderless', b'true')]:
        data, count = re.subn(rb'(?m)^' + key + rb'=(?:true|false)(\r?)$',
                              key + b'=' + value + rb'\1', data)
        if count != 1:
            raise ValueError(f'Expected one {key.decode()} setting')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zomboid', type=Path, default=Path.home() / 'Zomboid')
    parser.add_argument('--workshop', type=Path, default=Path.home() /
                        '.local/share/Steam/steamapps/workshop/content/108600')
    parser.add_argument('--state', type=Path, default=Path.home() / '.zombie_buddy')
    parser.add_argument('--backup', type=Path, default=Path.home() /
                        '.local/state/zomboid-mod-patches/session')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--skip-approvals', action='store_true')
    parser.add_argument('--disable-mod', action='append', default=[])
    parser.add_argument('--borderless', action='store_true')
    args = parser.parse_args()
    approval_path = args.state / 'mod_approvals.json'
    old = approval_path.read_bytes() if approval_path.exists() else None
    new, count = (old, 0) if args.skip_approvals else approvals(args.zomboid / 'console.txt', args.workshop, old)
    changes = [(approval_path, old, new)]
    save, mode = (args.zomboid / 'latestSave.ini').read_text().splitlines()[:2]
    if any(part in ('', '.', '..') or '/' in part or '\\' in part for part in (save, mode)):
        raise ValueError('Invalid latest save path')
    for path in [args.zomboid / 'mods/default.txt', args.zomboid / 'Saves' / mode / save / 'mods.txt']:
        data = path.read_bytes()
        replacement = without_hills(data)
        for mod in args.disable_mod:
            if not mod or any(c in mod for c in '\r\n,'):
                raise ValueError('Invalid mod ID')
            replacement = re.sub(rb'(?m)^[ \t]*mod = ' + re.escape(mod.encode()) + rb',[ \t]*\r?\n',
                                 b'', replacement)
        changes.append((path, data, replacement))
    if args.borderless:
        path = args.zomboid / 'options.ini'
        data = path.read_bytes()
        changes.append((path, data, borderless(data)))
    # All validation precedes writes.
    for path, original, replacement in changes:
        if original == replacement:
            continue
        print(f"{'UPDATE' if args.apply else 'WOULD UPDATE'} {path}")
        if args.apply:
            if original is not None:
                args.backup.mkdir(parents=True, exist_ok=True)
                backup = args.backup / (path.name + '.' + hashlib.sha256(original).hexdigest())
                if backup.exists() and backup.read_bytes() != original:
                    raise ValueError(f'Backup mismatch: {backup}')
                backup.write_bytes(original)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(replacement)
    print(f'{count} previously accepted mod versions added to persistent approvals')


if __name__ == '__main__':
    main()

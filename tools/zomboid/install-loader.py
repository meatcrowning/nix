#!/usr/bin/env python3
"""Install the subscribed ZombieBuddy Java agent into the Linux game launcher.

Dry-run by default; use --apply to install. Re-run after Steam verifies or
updates the launcher. Mod approvals remain under ZombieBuddy's normal prompt
policy. This does not start the game or approve any mod.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def configure(data):
    config = json.loads(data)
    args = config['vmArgs']
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError('Expected a list of JVM arguments')
    agent = '-javaagent:ZombieBuddy.jar'
    existing = [arg for arg in args if arg.startswith('-javaagent:')
                and 'zombiebuddy' in arg.lower()]
    if existing and existing != [agent]:
        raise ValueError('Existing ZombieBuddy agent arguments need review')
    if not existing:
        args.append(agent)
        newline = '\r\n' if b'\r\n' in data else '\n'
        return (json.dumps(config, indent='\t') + '\n').replace('\n', newline).encode()
    return data


def save(path, data, backup):
    if path.exists():
        original = path.read_bytes()
        if original == data:
            return
        destination = backup / (path.name + '.' + hashlib.sha256(original).hexdigest())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != original:
            raise ValueError(f'Backup mismatch: {destination}')
        destination.write_bytes(original)
    path.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steamapps', type=Path, default=Path.home() /
                        '.local/share/Steam/steamapps')
    parser.add_argument('--backup', type=Path, default=Path.home() /
                        '.local/state/zomboid-mod-patches/loader')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    game = args.steamapps / 'common/ProjectZomboid/projectzomboid'
    source = args.steamapps / 'workshop/content/108600/3619862853/mods/ZombieBuddy/libs/ZombieBuddy.jar'
    launcher = game / 'ProjectZomboid64.json'
    # Validate both files before changing either one.
    updated = configure(launcher.read_bytes())
    with zipfile.ZipFile(source) as jar:
        manifest = jar.read('META-INF/MANIFEST.MF').decode()
        if 'Premain-Class: me.zed_0xff.zombie_buddy.Agent' not in manifest:
            raise ValueError('Unexpected ZombieBuddy agent manifest')
        if jar.testzip() is not None:
            raise ValueError('Corrupt ZombieBuddy archive')
    payload = source.read_bytes()
    if args.apply:
        save(game / 'ZombieBuddy.jar', payload, args.backup)
        save(launcher, updated, args.backup)
    print(f"{'Installed' if args.apply else 'Would install'} ZombieBuddy in {game}")
    print('The next game launch will prompt for Java mod approvals as needed.')


if __name__ == '__main__':
    main()

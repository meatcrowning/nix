"""Interactive ROM imports: verified catalog choices, local launchers, live Steam IDs.

The UI owns Steam's live shortcut API; never edit shortcuts.vdf behind Steam.
Imported files stay in place. Runtime records supplement the private manifest.
"""
import base64
import difflib
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import msgpack
import games

IMPORTS = games.DATA / 'games/imports.json'
DETAILS = games.DATA / 'games/library-details.json'
CACHE = games.LOGS / 'catalogs'
# key, database name, display name, runner/core, accepted file extensions.
SYSTEMS = [
    ('nes', 'Nintendo - Nintendo Entertainment System', 'NES', 'fceumm', '.nes'),
    ('snes', 'Nintendo - Super Nintendo Entertainment System', 'Super Nintendo', 'snes9x', '.sfc .smc'),
    ('n64', 'Nintendo - Nintendo 64', 'Nintendo 64', 'mupen64plus', '.z64 .n64 .v64'),
    ('gb', 'Nintendo - Game Boy', 'Game Boy', 'mgba', '.gb'),
    ('gbc', 'Nintendo - Game Boy Color', 'Game Boy Color', 'mgba', '.gbc'),
    ('gba', 'Nintendo - Game Boy Advance', 'Game Boy Advance', 'mgba', '.gba'),
    ('gc', 'Nintendo - GameCube', 'GameCube', 'dolphin', '.iso .gcm .rvz .ciso'),
    ('psx', 'Sony - PlayStation', 'PlayStation', 'swanstation', '.cue .chd .pbp .m3u'),
    ('ps2', 'Sony - PlayStation 2', 'PlayStation 2', 'pcsx2', '.iso .chd .cso .gz'),
    ('psp', 'Sony - PlayStation Portable', 'PSP', 'ppsspp', '.iso .cso .pbp'),
]


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked():
    IMPORTS.parent.mkdir(parents=True, exist_ok=True)
    with (IMPORTS.parent / '.import.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def system(key):
    return next((s for s in SYSTEMS if s[0] == key), None) or fail('Choose a supported console.')


def fail(message):
    raise ValueError(message)


def validate_file(filename, spec):
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in spec[4].split():
        fail('Choose a ROM or disc image for this console. Extract archives first.')
    if path.stat().st_size == 0:
        fail('This file is empty.')
    if path.suffix.lower() in ('.cue', '.m3u'):
        content = path.read_text(encoding='utf-8-sig')
        members = (re.findall(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', content, re.I | re.M)
                   if path.suffix.lower() == '.cue' else
                   [(line.strip(), '') for line in content.splitlines() if line.strip() and not line.startswith('#')])
        if not members:
            fail('This playlist or cue sheet contains no files.')
        for quoted, plain in members:
            child = path.parent / (quoted or plain)
            if not child.is_file() or child.resolve() == path:
                fail(f'Missing or invalid disc file: {child.name}')
    runner = 'pcsx2-qt' if spec[3] == 'pcsx2' else 'retroarch'
    if not shutil.which(runner):
        fail(f'{spec[2]} emulation is not installed on this host.')
    if runner == 'retroarch' and not (games.CORES / games.CORE_FILES[spec[3]]).is_file():
        fail(f'The {spec[2]} emulator core is not installed.')
    return path


def catalog(spec):
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / (spec[0] + '.rdb')
    if not cached.exists() or time.time() - cached.stat().st_mtime > 7 * 86400:
        url = 'https://raw.githubusercontent.com/libretro/libretro-database/master/rdb/' + urllib.parse.quote(spec[1]) + '.rdb'
        try:
            with urllib.request.urlopen(url, timeout=25) as response:
                data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024 or not data.startswith(b'RARCHDB\0'):
                fail('The game catalog download was invalid. Try again later.')
            # Parse before caching; a truncated download must not replace a good cache.
            records = decode_catalog(data)
            fd, temp = tempfile.mkstemp(dir=CACHE)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            os.replace(temp, cached)
            return records
        except OSError:
            if not cached.exists():
                fail('Could not download the game catalog. Check your connection and retry.')
    return decode_catalog(cached.read_bytes())


def decode_catalog(data):
    if not data.startswith(b'RARCHDB\0'):
        fail('Invalid game catalog.')
    records = {}
    # RDB's 16-byte header precedes MessagePack records, terminated by nil.
    for entry in msgpack.Unpacker(io.BytesIO(data[16:]), raw=False, strict_map_key=False):
        if entry is None:
            return list(records.values())
        if not isinstance(entry, dict):
            fail('Invalid game catalog entry.')
        # Some catalogs retain orphan checksum/serial annotations with no title.
        # They cannot be offered as a match or attributed to another game.
        if not isinstance(entry.get('name'), str):
            continue
        # Disc checksum records and rich metadata records can share a title.
        # Merge only exact titles, never credits from a different regional port.
        previous = records.setdefault(entry['name'], {})
        for key, value in entry.items():
            if value and not previous.get(key):
                previous[key] = value
    fail('Incomplete game catalog. Retry the download.')


def clean_title(name):
    return re.sub(r'\s*[([][^)\]]*[)\]]', '', name).strip()


def normalized(name):
    return re.sub(r'[^\w]', '', clean_title(name).casefold())


def metadata(entry, spec):
    developer = entry.get('developer', '')
    if isinstance(developer, list):
        developer = ' / '.join(developer)
    return {'console': spec[2], 'year': str(entry.get('releaseyear') or ''),
            'developer': developer.strip(), 'controllerSupport': 'emulated',
            'source': 'https://github.com/libretro/libretro-database', 'catalogTitle': entry['name']}


def search(request):
    spec = system(request['system'])
    path = validate_file(request['path'], spec)
    query = normalized(request.get('query') or path.stem)
    if not query:
        fail('Enter a game title to search.')
    entries = catalog(spec)
    scored = []
    for index, entry in enumerate(entries):
        name = normalized(entry['name'])
        full_name = re.sub(r'[^\w]', '', entry['name'].casefold())
        score = max(difflib.SequenceMatcher(None, query, name).ratio(),
                    difflib.SequenceMatcher(None, query, full_name).ratio())
        if query in name:
            score = max(score, .85)
        if score >= .4:
            scored.append((score, entry['name'], index, entry))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return {'matches': [{'id': name, 'title': name, **metadata(entry, spec)}
                        for _, name, _, entry in scored[:20]], 'path': str(path)}


def prepare(request):
    spec = system(request['system'])
    path = validate_file(request['path'], spec)
    entry = next((e for e in catalog(spec) if e['name'] == request['match']), None)
    if entry is None:
        fail('The catalog changed. Search again and select a game.')
    details = metadata(entry, spec)
    for key in ('developer', 'year'):
        value = str(request.get(key, details[key])).strip()
        if key == 'year' and not re.fullmatch(r'(19|20)\d{2}', value):
            fail('Enter the release year for this console version.')
        if not value or len(value) > 250 or any(ord(c) < 32 for c in value):
            fail('Enter the developer for this console version.')
        if value != details[key]:
            details.setdefault('manualFields', []).append(key)
        details[key] = value
    slug = 'rom-' + spec[0] + '-' + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    # Include the console to keep ports distinct and match the existing library.
    title = clean_title(entry['name']) + ' (' + spec[2] + ')'
    if len(title) > 250 or any(ord(c) < 32 for c in title):
        fail('The catalog title is invalid.')
    thumb = spec[1].replace(' ', '_') + '/' + entry['name']
    game = {'slug': slug, 'name': title, 'path': str(path), 'runner': 'pcsx2' if spec[3] == 'pcsx2' else 'retroarch',
            'thumb': thumb, 'details': details}
    if game['runner'] == 'retroarch':
        game['core'] = spec[3]
    with locked():
        imports = read_json(IMPORTS, {'games': []})
        library = games.load()
        existing = next((g for g in library if Path(g['path']).resolve() == path), None)
        if not existing and any(g['name'] == title for g in library):
            fail('This game is already in the library at a different path. Import stopped to avoid a duplicate.')
        if existing:
            # Preserve the launcher identity (and user customizations) on retry.
            if existing['runner'] != game['runner'] or (existing.get('core') and existing['core'] != spec[3]):
                fail('This file is already registered for another emulator.')
            game = {**game, **existing, 'details': details}
        old = next((g for g in imports['games'] if g['slug'] == game['slug']), None)
        if old:
            imports['games'].remove(old)
        imports['games'].append(game)
        atomic_json(IMPORTS, imports)
    arts = games.artwork(game)
    portrait = arts.get('p')
    image = None
    if portrait and portrait.stat().st_size <= 10 * 1024 * 1024:
        image = base64.b64encode(portrait.read_bytes()).decode()
    return {'slug': game['slug'], 'title': game['name'], 'exe': games.GAMES_BIN,
            'startDir': str(games.HOME), 'options': 'run ' + game['slug'],
            'existingAppId': game.get('steamAppIdRuntime'), 'expectedAppId': games.srm_app_id(game['name']),
            'details': details, 'portrait': image,
            'warning': '' if image else 'No box art was available. You can add artwork with SteamGridDB.'}


def finish(request):
    appid = request['appid']
    if not isinstance(appid, int) or isinstance(appid, bool) or not 0 < appid < 2**32:
        fail('Steam did not return a valid shortcut ID.')
    with locked():
        imports = read_json(IMPORTS, {'games': []})
        game = next((g for g in imports['games'] if g['slug'] == request['slug']), None)
        if game is None:
            fail('Import not found. Select the ROM again.')
        game['steamAppIdRuntime'] = appid
        # Record the live ID before anything that can fail, so retries reuse it.
        atomic_json(IMPORTS, imports)
        details = read_json(DETAILS, {})
        details[str(appid)] = {**details.get(str(appid), {}), **game['details']}
        atomic_json(DETAILS, details)
    # Only this import's launcher; do not rebuild or remove other entries.
    games.ICONS.mkdir(parents=True, exist_ok=True)
    games.ENTRIES.mkdir(parents=True, exist_ok=True)
    icon = games.ART / game['slug'] / 'p.png'
    if icon.exists():
        shutil.copyfile(icon, games.ICONS / (game['slug'] + '.png'))
    (games.ENTRIES / ('game-' + game['slug'] + '.desktop')).write_text(
        '[Desktop Entry]\nType=Application\n'
        f"Name={game['name']}\nComment={game['details']['console']}\n"
        f"Exec=games run {game['slug']}\nIcon={games.icon_for(game, offline=True)}\n"
        'Categories=Game;\nTerminal=false\n')
    return {'appid': appid, 'title': game['name']}


def dispatch(action, request):
    if action == 'systems':
        return {'home': str(games.HOME), 'systems': [
            {'id': s[0], 'label': s[2], 'extensions': s[4].split()} for s in SYSTEMS]}
    return {'search': search, 'prepare': prepare, 'finish': finish}[action](request)

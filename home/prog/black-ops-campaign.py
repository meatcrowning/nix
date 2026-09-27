"""Present the original campaign assets alongside the updated LAN installation."""

import hashlib
import json
import os
from pathlib import Path
import sys


game, backups, cache = map(Path, sys.argv[1:])
manifests = sorted(backups.glob("*/manifest.json"))
if not manifests:
    print(game)
    sys.exit(0)

# The first DLC installation saved the files matching the retail executable.
manifest = manifests[0]
entries = json.loads(manifest.read_text())
overrides = {}
for entry in entries:
    relative = Path(entry["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Invalid backup path: {relative}")
    original_hash = entry["previous_sha256"]
    original = manifest.parent / relative
    if original_hash:
        if hashlib.sha256(original.read_bytes()).hexdigest() != original_hash:
            raise ValueError(f"Campaign backup failed verification: {relative}")
        overrides[relative] = original
    else:
        overrides[relative] = None

identity = hashlib.sha256(os.fsencode(game.resolve()) + manifest.read_bytes()).hexdigest()[:16]
view = cache / identity
if not (view / ".complete").exists():
    view.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(game):
        relative_root = Path(root).relative_to(game)
        target = view / relative_root
        target.mkdir(parents=True, exist_ok=True)
        # Campaign settings and saves remain in their original location.
        if relative_root == Path(".") and "players" in dirs:
            dirs.remove("players")
            if not (view / "players").is_symlink():
                (view / "players").symlink_to(game / "players", target_is_directory=True)
        for name in files:
            relative = relative_root / name
            source = overrides.get(relative, game / relative)
            if source is not None and not (view / relative).is_symlink():
                (view / relative).symlink_to(source)
    (view / ".complete").touch()
print(view)

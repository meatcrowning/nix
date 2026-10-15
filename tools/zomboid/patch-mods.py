#!/usr/bin/env python3
"""Apply reviewed Common Sense / Noir Rifle Slings fixes for PZ 42.21.

Run with --apply after checking the dry run. Workshop updates may overwrite
these fixes; unfamiliar source hashes are refused instead of patched blindly.
Original bytes are kept outside Workshop in the backup directory.
"""

import argparse
import hashlib
from pathlib import Path
import re


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plan(root, backup):
    changes = []

    def patch(relative, expected, transform):
        path = root / relative
        current = path.read_bytes()
        original = backup / expected
        if digest(current) == expected:
            source = current
        elif original.exists() and digest(original.read_bytes()) == expected:
            source = original.read_bytes()
        else:
            raise ValueError(f"Unreviewed Workshop content: {path}")
        result = transform(source)
        if current not in (source, result):
            raise ValueError(f"Unreviewed local edits: {path}")
        changes.append((path, current, result, original, source))

    common = "2875848298/mods/CommonSense/42.0/media/"
    patch(common + "scripts/CS_recipes.txt",
          "71ca0a17050b21b9d580543311ee69d9b9e1be7589d3f2f09e7fc68f9256d456",
          lambda b: b.replace(b"[Alcohol]", b"[RubbingAlcohol;Vodka;Whiskey]"))
    patch(common + "lua/server/CommonSense/BB_CS_RecipeCode.lua",
          "da20bfcf7f04d6da72475736824e4c794613494e33122725398eb938e58d7182",
          lambda b: b'-- B42 craft recipes use tags[Scissors], not the removed Recipe.GetItemTypes API.\n')

    variants = [
        ("NoirRifleSlings", ["Sling"],
         "e5a722ec5c9e17afc7ab7ede5cbd29e3451426800411c29dd8fcdca78df4eddc",
         "3dda16acddae7670a3b0eafbe84b0b03401f5bfc6e0d56c139574205972bf6f7"),
        ("NoirRifleSlings4", ["Sling", "SlingA", "SlingB", "SlingC"],
         "69b158dd9ff36437e19d9026a223bfbb99d2a9d0b5c23a9b830ee6d3fb755b09",
         "8406d76dd61266e37797052db707f6152477d8cabaed2f001e5623cdff5fc8de"),
    ]
    for name, slots, lua_hash, items_hash in variants:
        prefix = f"3388107363/mods/{name}/common/media/"
        registry = '-- Register custom equipment slots before item scripts load.\n'
        body = 'local group = BodyLocations.getGroup("Human")\n'
        for slot in slots:
            identifier = f"NoirRifleSlings:{slot}"
            registry += f'ItemBodyLocation.register("{identifier}")\n'
            body += ('group:getOrCreateLocation(ItemBodyLocation.get('
                     f'ResourceLocation.of("{identifier}")))\n')
        patch(prefix + "lua/shared/NPCs/Sling_BodyLocations.lua", lua_hash,
              lambda b, text=body: text.encode())
        patch(prefix + "scripts/clothing/Sling_items.txt", items_hash,
              lambda b: re.sub(rb"(BodyLocation\s*=\s*)(Sling[A-C]?)(\s*,)",
                               rb"\1NoirRifleSlings:\2\3", b))
        path = root / prefix / "registries.lua"
        result = registry.encode()
        current = path.read_bytes() if path.exists() else None
        if current is not None and current != result:
            raise ValueError(f"Existing registry needs review: {path}")
        changes.append((path, current, result, None, None))
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() /
                        '.local/share/Steam/steamapps/workshop/content/108600')
    parser.add_argument('--backup', type=Path, default=Path.home() /
                        '.local/state/zomboid-mod-patches/originals')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    # Validate every input before writing any Workshop file.
    changes = plan(args.root, args.backup)
    for path, current, result, original, source in changes:
        if current == result:
            print(f"OK {path.relative_to(args.root)}")
            continue
        if args.apply:
            if original is not None:
                original.parent.mkdir(parents=True, exist_ok=True)
                if original.exists():
                    if original.read_bytes() != source:
                        raise ValueError(f"Backup mismatch: {original}")
                else:
                    original.write_bytes(source)
            path.write_bytes(result)
        print(f"{'PATCHED' if args.apply else 'WOULD PATCH'} {path.relative_to(args.root)}")


if __name__ == '__main__':
    main()

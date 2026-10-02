#!/usr/bin/env python3
"""Import original F.E.A.R. menu audio locally; never commit the game assets.

Usage: python3 sys/gme/steam-audio/import-fear.py /path/to/FEAR
Requires the original game's FEAR.Arch00 and an installed Steam client.
Audio Loader discovers the new packs on its next refresh/load. Existing packs
and selections are preserved. The existing Decky seed leaves local packs alone.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import tempfile


# Map Steam actions to their original Interface/snd counterparts. Everything
# outside menu interaction (chat, achievements, recording, etc.) stays native.
MAPPINGS = {
    "deck_ui_navigation.wav": "selectchange.wav",
    "deck_ui_tile_scroll.wav": "selectchange.wav",
    "deck_ui_default_activation.wav": "select.wav",
    "deck_ui_into_game_detail.wav": "select.wav",
    "deck_ui_out_of_game_detail.wav": "dialogueclose.wav",
    "deck_ui_launch_game.wav": "pressanykey.wav",
    "deck_ui_show_modal.wav": "dialogueopen.wav",
    "deck_ui_hide_modal.wav": "dialogueclose.wav",
    "deck_ui_side_menu_fly_in.wav": "dialogueopen.wav",
    "deck_ui_side_menu_fly_out.wav": "dialogueclose.wav",
    "deck_ui_tab_transition_01.wav": "pagenext.wav",
    "deck_ui_slider_up.wav": "arrowright.wav",
    "deck_ui_slider_down.wav": "arrowleft.wav",
    "deck_ui_switch_toggle_on.wav": "select.wav",
    "deck_ui_switch_toggle_off.wav": "dialogueclose.wav",
    "deck_ui_bumper_end_02.wav": "unselectable.wav",
    "bumper_end.wav": "unselectable.wav",
    "confirmation_positive.wav": "select.wav",
    "confirmation_negative.wav": "unselectable.wav",
    "deck_ui_typing.wav": "selectchange.wav",
    "deck_ui_volume.wav": "selectchange.wav",
}
SOURCES = {name: f"interface/snd/{name}" for name in set(MAPPINGS.values())}
# The game's database references this as SplashScreenSound. Despite its name,
# it is PCM WAV: keep the original loop lossless, including its loop boundary.
SOURCES["menu_music.wav"] = "interface/menu/snd/theme_mp3.wav"


def read_audio(archive):
    """Read only the required uncompressed entries from a LithTech v3 archive."""
    result = {}
    with archive.open("rb") as stream:
        size = archive.stat().st_size
        header = stream.read(48)
        if len(header) != 48 or header[:8] != b"LTAR\x03\0\0\0":
            raise ValueError("Expected an original F.E.A.R. LTAR v3 archive")
        _, _, name_size, folders, files, *_ = struct.unpack("<12I", header)
        if 48 + name_size + files * 32 + folders * 16 > min(size, 64 * 1024**2):
            raise ValueError("Invalid archive table sizes")
        names = stream.read(name_size)
        entries = iter(struct.iter_unpack("<IQQQI", stream.read(files * 32)))
        directories = list(struct.iter_unpack("<4I", stream.read(folders * 16)))

        def name(offset):
            return names[offset:names.index(0, offset)].decode("ascii").replace("\\", "/").lower()

        wanted = {source: output for output, source in SOURCES.items()}
        if sum(folder[3] for folder in directories) != files:
            raise ValueError("Inconsistent archive entry count")
        for folder, _, _, count in directories:
            for _ in range(count):
                filename, offset, packed, raw, method = next(entries)
                path = f"{name(folder)}/{name(filename)}"
                if path not in wanted:
                    continue
                if method != 0 or packed != raw or offset + raw > size or raw > 16 * 1024**2:
                    raise ValueError(f"Unsupported or invalid audio entry: {path}")
                stream.seek(offset)
                data = stream.read(raw)
                if len(data) != raw or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                    raise ValueError(f"Invalid WAV: {path}")
                result[wanted[path]] = data
    missing = SOURCES.keys() - result.keys()
    if missing:
        raise ValueError(f"Missing menu audio: {', '.join(sorted(missing))}")
    return result


def install(game, destination, steam_sounds):
    audio = read_audio(game / "FEAR.Arch00")
    native = {p.name for p in steam_sounds.iterdir() if p.suffix in (".wav", ".m4a", ".mp3")}
    if "deck_ui_navigation.wav" not in native:
        raise ValueError("Steam sound directory is missing its menu sounds")
    packs = ("F.E.A.R.", "F.E.A.R. Ambience")
    if any((destination / pack).exists() for pack in packs):
        raise FileExistsError("F.E.A.R. pack already exists; refusing to overwrite it")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fear-import-", dir=destination) as temp:
        for pack, music in zip(packs, (False, True)):
            folder = Path(temp) / pack
            folder.mkdir()
            selected = {"menu_music.wav"} if music else set(MAPPINGS.values())
            for filename in sorted(selected):
                (folder / filename).write_bytes(audio[filename])
            manifest = {
                "name": pack, "author": "Monolith Productions", "version": "v1.0",
                "description": "Original F.E.A.R. menu audio extracted from the local game installation.",
                "manifest_version": 2, "music": music,
                "mappings": {"menu_music.mp3": ["menu_music.wav"]} if music else
                    {key: [value] for key, value in MAPPINGS.items()},
                "ignore": [] if music else sorted(native - MAPPINGS.keys()),
                "sources": {filename: {"path": SOURCES[filename],
                    "sha256": hashlib.sha256(audio[filename]).hexdigest()} for filename in sorted(selected)},
            }
            (folder / "pack.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for pack in packs:
            (Path(temp) / pack).rename(destination / pack)
            print(f"Installed {destination / pack}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path, help="directory containing FEAR.Arch00")
    parser.add_argument("--destination", type=Path, default=Path("/var/lib/decky-loader/sounds"))
    parser.add_argument("--steam-sounds", type=Path,
                        default=Path.home() / ".local/share/Steam/steamui/sounds")
    args = parser.parse_args()
    install(args.game, args.destination, args.steam_sounds)

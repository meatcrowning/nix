"""Launchers for games that live outside Steam.

The manifest (a host-local JSON list, kept in the private docs repo because it
names the user's own files) says where each game is and how it runs. `sync`
turns it into desktop entries with icons; `run` starts one game; `check`
reports which entries would launch without starting anything.

Games stay where they are, often on removable drives, so `run` names the
missing drive instead of failing silently when one is unplugged.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))
MANIFEST = Path(os.environ["GAMES_MANIFEST"])
CORES = Path(os.environ["GAMES_RETROARCH_CORES"])
ENTRIES = DATA / "applications/games"
ICONS = DATA / "games/icons"
PREFIXES = DATA / "wineprefixes/games"
PROTON = DATA / "Steam/steamapps/common/Proton - Experimental"

CORE_FILES = {
    "swanstation": "swanstation_libretro.so",
    "dolphin": "dolphin_libretro.so",
    "mupen64plus": "mupen64plus_next_libretro.so",
    "mgba": "mgba_libretro.so",
    "snes9x": "snes9x_libretro.so",
    "fceumm": "fceumm_libretro.so",
    "ppsspp": "ppsspp_libretro.so",
}

# Shown as the launcher comment, and used as a fallback icon when neither the
# game's executable nor the thumbnail archive provides one.
RUNNER_LABELS = {
    "proton": ("Windows · Proton", "wine"),
    "steam-run": ("Linux", "applications-games"),
    "pcsx2": ("PlayStation 2 · PCSX2", "PCSX2"),
}
SYSTEM_LABELS = {
    "Sony_-_PlayStation": "PlayStation",
    "Nintendo_-_GameCube": "GameCube",
    "Nintendo_-_Nintendo_64": "Nintendo 64",
    "Nintendo_-_Super_Nintendo_Entertainment_System": "Super Nintendo",
    "Nintendo_-_Nintendo_Entertainment_System": "NES",
    "Nintendo_-_Game_Boy_Advance": "Game Boy Advance",
    "Sony_-_PlayStation_Portable": "PSP",
    "Sony_-_PlayStation_2": "PlayStation 2",
}


def load():
    if not MANIFEST.exists():
        return []
    return json.loads(MANIFEST.read_text())["games"]


def find(slug):
    for game in load():
        if game["slug"] == slug:
            return game
    sys.exit(f"games: no game named {slug!r} in {MANIFEST}")


def command(game):
    """The argv and working directory that start this game."""
    path = Path(game["path"])
    runner = game["runner"]
    args = game.get("args", [])
    if runner == "proton":
        return ["umu-run", str(path), *args], path.parent
    if runner == "steam-run":
        return ["steam-run", f"./{path.name}", *args], path.parent
    if runner == "pcsx2":
        return ["pcsx2-qt", "-batch", "--", str(path)], None
    if runner == "retroarch":
        core = CORES / CORE_FILES[game["core"]]
        return ["retroarch", "-L", str(core), str(path)], None
    sys.exit(f"games: unknown runner {runner!r}")


def missing_reason(path):
    """Why a game file is absent: an unplugged drive, or the file itself."""
    parts = Path(path).parts
    if parts[:4] == ("/", "run", "media", HOME.name) and len(parts) > 4:
        mount = Path(*parts[:5])
        if not os.path.ismount(mount):
            return f"The {parts[4]} drive isn't mounted. Plug it in or open it in Dolphin, then try again."
    return f"{path} is missing."


def run(slug):
    game = find(slug)
    if not Path(game["path"]).exists():
        reason = missing_reason(game["path"])
        subprocess.run(["notify-send", "-a", "Games", "-i", "dialog-warning",
                        "--", game["name"], reason])
        sys.exit(reason)
    argv, cwd = command(game)
    env = dict(os.environ)
    if game["runner"] == "proton":
        prefix = PREFIXES / slug
        prefix.mkdir(parents=True, exist_ok=True)
        env.update(WINEPREFIX=str(prefix), PROTONPATH=str(PROTON),
                   GAMEID="umu-default", STORE="none")
    if cwd:
        os.chdir(cwd)
    os.execvpe(argv[0], argv, env)


def check():
    games = load()
    bad = 0
    for game in games:
        argv, cwd = command(game)
        exists = Path(game["path"]).exists()
        core_ok = game["runner"] != "retroarch" or Path(argv[2]).exists()
        ok = exists and core_ok
        bad += not ok
        state = "ok     " if ok else ("NO CORE" if exists else "MISSING")
        print(f"{state} {game['slug']:<32} {' '.join(argv)}")
    print(f"{len(games) - bad}/{len(games)} launchable")
    return 1 if bad else 0


def exe_icon(exe, out):
    """Extract the largest icon embedded in a Windows executable."""
    with tempfile.TemporaryDirectory() as tmp:
        ico = Path(tmp) / "icon.ico"
        with open(ico, "wb") as f:
            if subprocess.run(["wrestool", "-x", "-t", "14", str(exe)], stdout=f,
                              stderr=subprocess.DEVNULL).returncode or not ico.stat().st_size:
                return False
        return ico_to_png(ico, out)


def ico_to_png(ico, out):
    listing = subprocess.run(["icotool", "-l", str(ico)], capture_output=True, text=True).stdout
    best = None
    for line in listing.splitlines():
        m = re.search(r"--index=(\d+).*--width=(\d+).*--bit-depth=(\d+)", line)
        if m:
            key = (int(m[2]), int(m[3]))
            if best is None or key > best[0]:
                best = (key, m[1])
    if best is None:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["icotool", "-x", f"--index={best[1]}", "-o", tmp, str(ico)],
                       stderr=subprocess.DEVNULL)
        pngs = list(Path(tmp).glob("*.png"))
        if not pngs:
            return False
        shutil.copyfile(pngs[0], out)
    return True


def thumbnail(thumb, out):
    """Box art from the libretro-thumbnails archive, named by No-Intro/Redump title."""
    system, title = thumb.split("/", 1)
    title = re.sub(r'[&*/:`<>?\\|"]', "_", title)
    url = (f"https://raw.githubusercontent.com/libretro-thumbnails/{system}/master/"
           f"Named_Boxarts/{urllib.parse.quote(title)}.png")
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            out.write_bytes(response.read())
        return True
    except OSError:
        return False


def icon_for(game, offline):
    """A cached PNG path for the game, or a theme icon name when there is none."""
    out = ICONS / f"{game['slug']}.png"
    if out.exists():
        return str(out)
    made = False
    if "icon" in game:
        src = Path(game["icon"])
        if src.exists():
            if src.suffix.lower() == ".ico":
                made = ico_to_png(src, out)
            elif src.suffix.lower() == ".exe":
                made = exe_icon(src, out)
            else:
                shutil.copyfile(src, out)
                made = True
    elif game["runner"] == "proton" and Path(game["path"]).exists():
        made = exe_icon(game["path"], out)
    if not made and "thumb" in game and not offline:
        made = thumbnail(game["thumb"], out)
    if made:
        return str(out)
    if "thumb" in game:
        return "retroarch" if game["runner"] == "retroarch" else "PCSX2"
    return RUNNER_LABELS[game["runner"]][1]


def comment(game):
    if "thumb" in game:
        return SYSTEM_LABELS.get(game["thumb"].split("/", 1)[0], "Console")
    return RUNNER_LABELS[game["runner"]][0]


def sync(offline):
    games = load()
    ICONS.mkdir(parents=True, exist_ok=True)
    ENTRIES.parent.mkdir(parents=True, exist_ok=True)
    # Build beside the live directory and swap it in, so the menu never sees a
    # half-written set; mkdtemp's name has no .desktop entries of its own.
    staging = Path(tempfile.mkdtemp(prefix=".games.", dir=ENTRIES.parent))
    try:
        for game in games:
            categories = ";".join(["Game", *game.get("categories", [])]) + ";"
            (staging / f"game-{game['slug']}.desktop").write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={game['name']}\n"
                f"Comment={comment(game)}\n"
                f"Exec=games run {game['slug']}\n"
                f"Icon={icon_for(game, offline)}\n"
                f"Categories={categories}\n"
                "Terminal=false\n"
            )
        if ENTRIES.exists():
            shutil.rmtree(ENTRIES)
        staging.rename(ENTRIES)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    subprocess.run(["systemctl", "--user", "start", "--no-block", "plasma-games-refresh.service"],
                   stderr=subprocess.DEVNULL)
    print(f"games: wrote {len(games)} launchers to {ENTRIES}")


def main():
    args = sys.argv[1:]
    if args[:1] == ["run"] and len(args) == 2:
        run(args[1])
    elif args[:1] == ["sync"]:
        sync(offline="--offline" in args)
    elif args == ["check"]:
        sys.exit(check())
    else:
        sys.exit("usage: games run SLUG | games sync [--offline] | games check")


if __name__ == "__main__":
    main()

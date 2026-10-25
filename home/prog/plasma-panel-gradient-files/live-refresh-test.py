#!/usr/bin/env python3
"""Isolated contracts for the Plasma panel's live palette refresh path.

Source checks and mocked commands verify the path without starting a
Plasma shell, which would be unsafe on the user's desktop.  The derivation
copies the fragment into Panel.qml, adds its directory-model import, and the running
panel then changes an Image URL when the renderer publishes a content hash.
"""

from pathlib import Path
import importlib.util
import subprocess
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = Path(__file__).with_name("Surface.qmlfrag").read_text()
RENDERER = Path(__file__).with_name("render-surface.py").read_text()
NIX = (ROOT / "plasma-oxygen-scheme.nix").read_text()


def require(text: str, needle: str, where: str) -> None:
    if needle not in text:
        raise AssertionError(f"{where} is missing {needle!r}")


def main() -> int:
    scheme_path = ROOT.parent / "srvs/wal-files/plasma-scheme.py"
    spec = importlib.util.spec_from_file_location("plasma_scheme", scheme_path)
    scheme = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scheme)
    # Model a path-triggered render already running with the previous palette.
    # A start would join it. Only a restart after the completed writes replaces
    # that stale result, including when a scheme pick calls the generator alone.
    roles = {}
    rendered = {"background": "old"}

    def run(command, **kwargs):
        if command[0] == "kwriteconfig6":
            roles[command[command.index("--key") + 1]] = command[-1]
        elif command[:3] == ["systemctl", "--user", "restart"]:
            assert command[3] == "plasma-panel-surface.service"
            assert roles["ColorSchemeHash"] == "finished"
            assert kwargs["check"] is True
            rendered["background"] = roles["BackgroundNormal"]
        return subprocess.CompletedProcess(command, 0)

    with patch.object(scheme.shutil, "which", side_effect=lambda name: name), \
            patch.object(scheme.subprocess, "run", side_effect=run):
        scheme.push_to_kdeglobals("[Colors:Window]\nBackgroundNormal=15,44,49\n",
                                  "OxygenDarkFlat", "finished", "9be0eb")
    assert rendered["background"] == "15,44,49", "stale in-flight render survived"

    for needle in (
        "plasma-panel-surface.*.serial",
        "FolderListModel",
        "panelSurfaceGeneration.count",
        "?generation=",
    ):
        require(FRAGMENT, needle, "Surface.qmlfrag")

    replace = RENDERER.index("temporary.replace(target)")
    # The identical-image branch can backfill a missing serial for the already
    # installed target.  The changed-image branch is the one whose ordering
    # matters, and it is the final publication call.
    publish = RENDERER.rindex("publish_generation(state, target)")
    if replace >= publish:
        raise AssertionError("renderer publishes the generation before replacing the PNG")
    require(RENDERER, "hashlib.sha256", "render-surface.py")
    require(RENDERER, "time.time_ns()", "render-surface.py")
    if 'temporary.replace(serial)' in RENDERER:
        raise AssertionError("generation token still uses the missed rename event")
    if 'state.glob("plasma-panel-surface.*.serial")' in RENDERER:
        raise AssertionError("generation publication still erases the insertion event")

    require(NIX, "import Qt.labs.folderlistmodel", "plasma-oxygen-scheme.nix")
    refresh = NIX.split('panel-surface-refresh =', 1)[1].split('panel-gradient-view =', 1)[0]
    for forbidden in ("try-restart plasma-plasmashell.service", "/bin/sleep", "last-restart"):
        if forbidden in refresh:
            raise AssertionError(f"live refresh still contains restart-era operation: {forbidden}")

    oxygen = (ROOT.parent / "srvs/wal-files/oxygen-live-icons.py").read_text()
    if "plasma-plasmashell.service" in oxygen:
        raise AssertionError("Oxygen icon completion still restarts Plasma")

    print("panel live-refresh contract: ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError) as exc:
        print(f"panel live-refresh contract: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Static contract for the Plasma panel's live palette refresh path.

This is intentionally source-level: it verifies the path without starting a
Plasma shell, which would be unsafe on the user's desktop.  The derivation
copies the fragment into Panel.qml, adds its directory-model import, and the running
panel then changes an Image URL when the renderer publishes a content hash.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = Path(__file__).with_name("Surface.qmlfrag").read_text()
RENDERER = Path(__file__).with_name("render-surface.py").read_text()
NIX = (ROOT / "plasma-oxygen-scheme.nix").read_text()


def require(text: str, needle: str, where: str) -> None:
    if needle not in text:
        raise AssertionError(f"{where} is missing {needle!r}")


def main() -> int:
    for needle in (
        "plasma-panel-surface.serial",
        "FolderListModel",
        "fileModified",
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

    require(NIX, "import Qt.labs.folderlistmodel", "plasma-oxygen-scheme.nix")
    refresh = NIX.split('panel-surface-refresh =', 1)[1].split('panel-gradient-view =', 1)[0]
    for forbidden in ("try-restart plasma-plasmashell.service", "/bin/sleep", "last-restart"):
        if forbidden in refresh:
            raise AssertionError(f"live refresh still contains restart-era operation: {forbidden}")

    print("panel live-refresh contract: ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError) as exc:
        print(f"panel live-refresh contract: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""Headless contract checks for DeskStyle's cache-to-profile boundary.

This deliberately imports no GI/Qt bindings and never starts the service or a
wallpaper helper.  It proves the controller can only accept a complete
prepared manifest, and that the active profile identity is derived from the
prepared palette and selected Plasma scheme rather than a wall-clock value.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[3]
SERVICE_PATH = Path(__file__).with_name("deskstyle-service.py")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("ok -", message)


def load_service():
    spec = importlib.util.spec_from_file_location("deskstyle_service_tested", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


with tempfile.TemporaryDirectory() as directory:
    home = Path(directory) / "home"
    home.mkdir()
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    old_library = os.environ.get("DESKSTYLE_WALLPAPER_DIR")
    try:
        service = load_service()
        check(len(inspect.signature(service.DeskStyleService._on_call).parameters) == 8,
              "uses PyGObject's seven-argument D-Bus method callback")
        wallpaper = home / "Pictures" / "wall" / "blue.png"
        wallpaper.parent.mkdir(parents=True)
        os.environ["DESKSTYLE_WALLPAPER_DIR"] = str(wallpaper.parent)
        wallpaper.write_bytes(b"wallpaper bytes")
        key = __import__("hashlib").md5(str(wallpaper).encode()).hexdigest()
        profile_dir = home / ".cache" / "wal" / "profiles" / key
        profile_dir.mkdir(parents=True)
        schemes = {}
        for name in ("dark", "darkNeutral", "light", "mixed"):
            scheme = profile_dir / f"{name}.colors"
            scheme.write_text(f"[{name}]\n", encoding="utf-8")
            schemes[name] = str(scheme)
        aero = profile_dir / "Aero.colors"
        aero.write_text("[Aero]\n", encoding="utf-8")
        schemes["aero"] = str(aero)
        manifest = {
            "version": 1,
            "source": str(wallpaper),
            "schemes": {"ready": True, **schemes},
        }
        (profile_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        selected = service.prepared_profile(wallpaper, "OxygenDarkFlat")
        check(selected["schemes"]["ready"] and selected["selectedSchemePath"] == schemes["dark"],
              "accepts a complete prepared scheme set without a live writer")
        check(service.prepared_profile(wallpaper, "OxygenMixed")["selectedSchemePath"] == schemes["mixed"],
              "selects the prepared mixed scheme")
        check(service.prepared_profile(wallpaper, "Aero")["selectedSchemePath"] == schemes["aero"],
              "uses a host-provided Aero body when the selected scheme is prepared")
        check(service.authorized_wallpaper(str(wallpaper)) == wallpaper.resolve(),
              "authorizes only a direct supported wallpaper-library file")
        outside = home / "outside.png"
        outside.write_bytes(b"not offered")
        try:
            service.authorized_wallpaper(str(outside))
        except ValueError as exc:
            check("wallpaper library" in str(exc), "rejects D-Bus paths outside the wallpaper library")
        else:
            raise AssertionError("accepted a wallpaper outside the library")
        unsupported = wallpaper.parent / "notes.txt"
        unsupported.write_text("not an image", encoding="utf-8")
        try:
            service.authorized_wallpaper(str(unsupported))
        except ValueError as exc:
            check("not supported" in str(exc), "rejects unsupported wallpaper file types")
        else:
            raise AssertionError("accepted an unsupported wallpaper type")

        (home / ".config").mkdir()
        (home / ".config" / "kdeglobals").write_text(
            "[General]\nColorScheme=OxygenDarkFlat\n", encoding="utf-8")
        (home / ".cache" / "wal" / "themes").mkdir(parents=True)
        (home / ".cache" / "wal" / "themes" / f"{key}.env").write_text(
            "ACCENT=1a2b3c\n", encoding="utf-8")
        (home / ".cache" / "wal" / "themes" / f"{key}.mode").write_text(
            "MODE=scale\n", encoding="utf-8")
        live_scheme = home / ".local" / "share" / "color-schemes" / "OxygenDarkFlat.colors"
        live_scheme.parent.mkdir(parents=True)
        live_scheme.write_text("[Colors:Window]\n", encoding="utf-8")
        first = service.build_profile(1, wallpaper)
        second = service.build_profile(1, wallpaper)
        check(first.digest == second.digest and first.accent == "#1a2b3c",
              "builds a stable profile digest from the prepared palette")
        check(service.elapsed_ms(10.0, 22.345) == 12345.0,
              "reports completion elapsed time across the full acknowledgement interval")
        source = inspect.getsource(service.DeskStyleService._complete)
        check('"elapsedMs": elapsed' in source and "elapsed * 1000" not in source,
              "stores the millisecond duration without multiplying it twice")

        try:
            service.prepared_profile(wallpaper, "Breeze")
        except RuntimeError as exc:
            check("not prepared" in str(exc),
                  "refuses a selected scheme without an exact prepared body")
        else:
            raise AssertionError("accepted an unprepared selected scheme")

        (profile_dir / "light.colors").unlink()
        try:
            service.prepared_profile(wallpaper, "OxygenDarkFlat")
        except RuntimeError as exc:
            check("light scheme" in str(exc), "rejects a manifest whose advertised scheme is missing")
        else:
            raise AssertionError("accepted a partial prepared profile")
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
        if old_library is None:
            os.environ.pop("DESKSTYLE_WALLPAPER_DIR", None)
        else:
            os.environ["DESKSTYLE_WALLPAPER_DIR"] = old_library

print("deskstyle cache/profile contract: passed")

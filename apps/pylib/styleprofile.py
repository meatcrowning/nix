"""Versioned, side-effect-free contract for a desktop appearance apply.

``StyleProfile`` is deliberately independent of Qt, D-Bus, KConfig, and the
wallpaper scripts.  The future controller is the only writer of this record;
clients use its digest and generation to establish that they have adopted the
same appearance.  Keeping this small, canonical record separate from the
individual mutable files lets an apply be measured and acknowledged without
pretending that a file write means a visible repaint happened.

The on-disk form is canonical JSON.  ``write_profile`` is atomic for the one
profile file it targets, but does not itself apply anything to the session.
``ApplyTrace`` is an in-memory monotonic trace intended for the controller and
its test harness; it contains no wall-clock times or user paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Mapping


SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_MODES = frozenset(("scale", "tile"))


class ProfileError(ValueError):
    """Raised when a profile is malformed or incompatible."""


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProfileError(f"{name} must be a non-empty string")
    return value


def _digest(value: Any, name: str) -> str:
    value = _string(value, name)
    if not _SHA256.fullmatch(value):
        raise ProfileError(f"{name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class StyleProfile:
    """The minimum identity of one fully prepared desktop appearance.

    ``wallpaper_path`` is absolute so clients can distinguish two different
    images with the same basename.  Authorization that it is inside the
    wallpaper library belongs to the controller, not this portable contract.
    """

    generation: int
    wallpaper_path: str
    wallpaper_sha256: str
    wallpaper_mode: str
    palette_sha256: str
    accent: str
    color_scheme: str
    color_scheme_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation < 1:
            raise ProfileError("generation must be a positive integer")
        if not os.path.isabs(_string(self.wallpaper_path, "wallpaper.path")):
            raise ProfileError("wallpaper.path must be absolute")
        _digest(self.wallpaper_sha256, "wallpaper.sha256")
        if self.wallpaper_mode not in _MODES:
            raise ProfileError("wallpaper.mode must be scale or tile")
        _digest(self.palette_sha256, "palette.sha256")
        if not isinstance(self.accent, str) or not _COLOR.fullmatch(self.accent):
            raise ProfileError("palette.accent must be #RRGGBB")
        _string(self.color_scheme, "colorScheme.name")
        _digest(self.color_scheme_sha256, "colorScheme.sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "generation": self.generation,
            "wallpaper": {"path": self.wallpaper_path, "sha256": self.wallpaper_sha256,
                          "mode": self.wallpaper_mode},
            "palette": {"sha256": self.palette_sha256, "accent": self.accent},
            "colorScheme": {"name": self.color_scheme, "sha256": self.color_scheme_sha256},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StyleProfile":
        if not isinstance(data, Mapping) or data.get("schemaVersion") != SCHEMA_VERSION:
            raise ProfileError(f"schemaVersion must be {SCHEMA_VERSION}")
        wall = data.get("wallpaper")
        palette = data.get("palette")
        scheme = data.get("colorScheme")
        if not isinstance(wall, Mapping) or not isinstance(palette, Mapping) or not isinstance(scheme, Mapping):
            raise ProfileError("wallpaper, palette, and colorScheme must be objects")
        return cls(generation=data.get("generation"), wallpaper_path=wall.get("path"),
                   wallpaper_sha256=wall.get("sha256"), wallpaper_mode=wall.get("mode"),
                   palette_sha256=palette.get("sha256"), accent=palette.get("accent"),
                   color_scheme=scheme.get("name"), color_scheme_sha256=scheme.get("sha256"))

    def canonical_json(self) -> bytes:
        return (json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                + "\n").encode("utf-8")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json()).hexdigest()


def read_profile(path: Path) -> StyleProfile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot read profile {path}: {exc}") from exc
    return StyleProfile.from_dict(data)


def write_profile(path: Path, profile: StyleProfile) -> None:
    """Atomically replace one profile file, retaining private user permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(profile.canonical_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@dataclass(frozen=True)
class TraceEvent:
    phase: str
    elapsed_ms: float
    detail: str = ""


class ApplyTrace:
    """Monotonic phase timing for one request; it neither applies nor waits."""

    def __init__(self, clock_ns: Callable[[], int] = time.monotonic_ns) -> None:
        self._clock_ns = clock_ns
        self._started_ns = clock_ns()
        self._events: list[TraceEvent] = []

    def mark(self, phase: str, detail: str = "") -> TraceEvent:
        if not isinstance(phase, str) or not phase:
            raise ValueError("phase must be a non-empty string")
        elapsed_ms = (self._clock_ns() - self._started_ns) / 1_000_000
        if elapsed_ms < 0:
            raise RuntimeError("monotonic clock moved backwards")
        event = TraceEvent(phase, elapsed_ms, detail)
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def report(self) -> dict[str, Any]:
        return {"events": [{"phase": e.phase, "elapsedMs": e.elapsed_ms, "detail": e.detail}
                            for e in self._events],
                "totalMs": self._events[-1].elapsed_ms if self._events else 0.0}

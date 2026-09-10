"""Deterministic ``__name__`` expansion for Painter prompt boxes."""

from __future__ import annotations

import random
import re
from pathlib import Path


WILDCARDS = Path(__file__).resolve().parent / "wildcards"
TOKEN = re.compile(r"__([A-Za-z0-9][A-Za-z0-9_.-]*)__")


def choices(name: str, root: Path = WILDCARDS) -> list[str]:
    """Return usable lines for *name*, matching CTE's wildcard-file rules."""
    try:
        text = (root / f"{name}.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def expand(text: str, seed: int, root: Path = WILDCARDS) -> str:
    """Expand wildcard tokens, choosing once per name from the job seed.

    Unknown names stay literal so a typo cannot silently disappear from a
    submitted prompt. Repeated uses of one name, including across positive and
    negative prompts when sharing *cache*, resolve to the same line.
    """
    picked: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in picked:
            lines = choices(name, root)
            if not lines:
                return match.group(0)
            rng = random.Random(f"{int(seed)}:{name}")
            picked[name] = lines[rng.randrange(len(lines))]
        return picked[name]

    return TOKEN.sub(replace, str(text))


def expand_prompts(positive: str, negative: str, seed: int,
                   root: Path = WILDCARDS) -> tuple[str, str]:
    """Expand both boxes with a shared per-job wildcard selection."""
    joined = positive + "\0" + negative
    expanded = expand(joined, seed, root)
    return tuple(expanded.split("\0", 1))

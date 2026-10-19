"""Deterministic ``__name__`` expansion for Painter prompt boxes."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import random
import re
from pathlib import Path


WILDCARDS = Path(__file__).resolve().parent / "wildcards"
TOKEN = re.compile(r"__([A-Za-z0-9][A-Za-z0-9_.-]*)__")


def names(root: Path = WILDCARDS) -> list[str]:
    return sorted(p.stem for p in root.glob('*.txt')
                  if p.is_file() and TOKEN.fullmatch('__' + p.stem + '__'))


def choices(name: str, root: Path = WILDCARDS) -> list[str]:
    """Return usable lines for *name*, matching CTE's wildcard-file rules."""
    try:
        text = (root / f"{name}.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def expand(text: str, seed: int, root: Path = WILDCARDS, options: dict | None = None) -> str:
    """Expand wildcard tokens, choosing once per name from the job seed.

    Unknown names stay literal so a typo cannot silently disappear from a
    submitted prompt. Repeated uses of one name, including across positive and
    negative and region prompts with the same seed, resolve to the same line.
    """
    picked: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in picked:
            rows = options.get(name) if options is not None else None
            lines = [row['text'] for row in rows if row['enabled']] if rows is not None else choices(name, root)
            if rows and not lines:
                raise ValueError('Wildcard __%s__ has no enabled lines.' % name)
            if not lines:
                return match.group(0)
            rng = random.Random(f"{int(seed)}:{name}")
            picked[name] = lines[rng.randrange(len(lines))]
        return picked[name]

    return TOKEN.sub(replace, str(text))


def expand_prompts(positive: str, negative: str, seed: int,
                   root: Path = WILDCARDS, options: dict | None = None) -> tuple[str, str]:
    """Expand both boxes with a shared per-job wildcard selection."""
    joined = positive + "\0" + negative
    expanded = expand(joined, seed, root, options)
    return tuple(expanded.split("\0", 1))


def expand_layout(layout: dict, seed: int, root: Path = WILDCARDS, options: dict | None = None) -> dict:
    """Expand region descriptions in a copy; preserve the editable document."""
    result = copy.deepcopy(layout)
    if result.get("enabled"):
        for item in result.get("items", []):
            if item.get("enabled", True) and isinstance(item.get("caption"), str):
                item["caption"] = expand(item["caption"], seed, root, options)
    return result


def validate_options(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid wildcard options')
    for name, rows in value.items():
        if not isinstance(name, str) or not TOKEN.fullmatch('__' + name + '__') or not isinstance(rows, list):
            raise ValueError('Invalid wildcard options')
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get('text'), str)
                    or not row['text'].strip() or type(row.get('enabled')) is not bool):
                raise ValueError('Invalid wildcard line')
    return {name: [dict(text=row['text'], enabled=row['enabled']) for row in rows] for name, rows in value.items()}


def load_options(path: Path, root: Path = WILDCARDS) -> dict:
    try:
        saved = validate_options(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        saved = {}
    result = {}
    for name in names(root):
        # Match text and occurrence, so reordering a file preserves choices and
        # duplicate lines remain individually selectable. New lines start enabled.
        prior = {}
        for row in saved.get(name, []):
            prior.setdefault(row['text'], []).append(row['enabled'])
        result[name] = []
        for text in choices(name, root):
            flags = prior.get(text, [])
            result[name].append(dict(text=text, enabled=flags.pop(0) if flags else True))
    return result


def save_options(path: Path, options: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(options, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

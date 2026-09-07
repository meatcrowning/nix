#!/usr/bin/env python3
"""Static coverage for every custom app in DeskStyle applies.

This deliberately imports no app: several applications initialise a handoff,
WebEngine, or other session-facing facility at import time.  It instead checks
the source-level contract that keeps a participant acknowledgement tied to a
successful Palette parse.  The protocol's own event-loop and socket behaviour
is covered by styleparticipant-test.py.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "askpass": "askpass",
    "board": "goetia",
    "editor": "editor",
    "filer": "filer",
    "painter": "painter",
    "reader": "reader",
    "slsk": "slsk",
    "surfer": "surfer",
    "updater": "updater",
    "viewer": "viewer",
    # player and chatter have their own integration, but remain part of the
    # desktop-wide contract so a later edit cannot silently drop either one.
    "player": "player",
    "oracle": "chatter",
}


def palette_load_returns_bool(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Palette":
            continue
        for method in node.body:
            if not isinstance(method, ast.FunctionDef) or method.name != "_load":
                continue
            returns = [child.value for child in ast.walk(method)
                       if isinstance(child, ast.Return) and child.value is not None]
            # The callback contract is deliberately strict: `None` means no
            # acknowledgement, so every Palette loader needs an explicit
            # unsuccessful path plus a parsed-result path (normally `parsed`
            # or `bool(found)`), rather than falling off the method.
            return (any(isinstance(value, ast.Constant) and value.value is False for value in returns)
                    and any(not (isinstance(value, ast.Constant) and value.value is False)
                            for value in returns))
    return False


def participant_name(tree: ast.Module) -> str | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "StyleParticipant":
            continue
        if len(node.args) >= 2 and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str) \
                and isinstance(node.args[1], ast.Attribute) \
                and node.args[1].attr == "_load":
            return node.args[0].value
    return None


failed = []
for app, expected in EXPECTED.items():
    path = ROOT / app / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    name = participant_name(tree)
    if name != expected:
        failed.append(f"{app}: expected StyleParticipant({expected!r}, palette._load), got {name!r}")
    if not palette_load_returns_bool(tree):
        failed.append(f"{app}: Palette._load must return parsed success and False")

if failed:
    print("FAIL")
    print("\n".join(failed))
    raise SystemExit(1)
print("ok - all DeskStyle participants acknowledge only after palette parsing")

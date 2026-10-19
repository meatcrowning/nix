#!/usr/bin/env python3
"""Headless checks for Painter's prompt wildcard expansion."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wildcards as W  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"ok  {label}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "colour.txt").write_text("# ignored\nred\n\nblue\n", encoding="utf-8")
    (root / "pose.txt").write_text("standing\nsitting\n", encoding="utf-8")
    (root / "bad name.txt").write_text("unused", encoding="utf-8")
    check("button names match supported wildcard tokens", W.names(root) == ['colour', 'pose'])

    first = W.expand("a __colour__ cube", 4242, root)
    check("a fixed seed is repeatable", first == W.expand("a __colour__ cube", 4242, root))
    check("the token is replaced", "__colour__" not in first)
    check("comments and blanks are ignored", first in {"a red cube", "a blue cube"})
    check("unknown names remain visible", W.expand("__missing__", 1, root) == "__missing__")

    pos, neg = W.expand_prompts("__pose__, __colour__", "not __colour__", 99, root)
    check("both prompt boxes expand", "__" not in pos and "__" not in neg)
    check("one name has one pick across both boxes", pos.split(", ")[1] == neg[4:])

    import copy
    import moss_layout as M
    editor = M.Editor(M.fresh(1024, 1024, 'A poster'))
    region = editor.add('object')
    region['caption'] = 'A __colour__ cube beside a __missing__ object'
    text = editor.add('text')
    text.update(caption='__colour__ lettering', text='__colour__')
    editor.doc['enabled'] = True
    original = copy.deepcopy(editor.doc)
    resolved = W.expand_layout(editor.doc, 99, root)
    colour = W.expand('__colour__', 99, root)
    check('region prompts expand with the main prompt selection',
          resolved['items'][0]['caption'] == 'A ' + colour + ' cube beside a __missing__ object')
    check('repeated region wildcards share the selection', resolved['items'][1]['caption'] == colour + ' lettering')
    check('exact wording stays literal', resolved['items'][1]['text'] == '__colour__')
    check('editable layout is not mutated', editor.doc == original)
    check('layout geometry is unchanged', resolved['items'][0]['box'] == region['box'])
    check('layout selection is deterministic', resolved == W.expand_layout(editor.doc, 99, root))
    check('different job seeds can produce different region prompts',
          len({W.expand_layout(editor.doc, seed, root)['items'][0]['caption'] for seed in range(20)}) == 2)
    editor.doc['enabled'] = False
    check('disabled layouts remain literal', W.expand_layout(editor.doc, 99, root) == editor.doc)

print("wildcards: all checks passed")

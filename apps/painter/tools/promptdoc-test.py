#!/usr/bin/env python3
"""Focused tests for Painter's lossless prompt-pill document."""

import os
import random
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from promptdoc import PromptDocument  # noqa: E402


def eq(label, got, want):
    if got != want:
        raise AssertionError(f"{label}: {got!r} != {want!r}")


samples = [
    "", "   \t", "a", "a,b", "a,  b", " a ,\t b  ", "a,\n\nb",
    "a\r\nb\rc\nd", "a,  ", ", a", "a,,b", ",,",
    "(lowres, bad hands:1.2), solo",
    "(a,(b,c):1.2),d", "[a, [b,c]], d",
    r"rebecca \(cyberpunk\), solo", r"a\,b,c", r"a\\,b,c",
    r"a\|b, c", "a | b || c, d", "<think>one, two</think>, result",
    "雪, café, 👩🏽‍🎨", "trailing\\",
]
for sample in samples:
    eq("round trip", PromptDocument.parse(sample).serialize(), sample)

doc = PromptDocument.parse("  one,  two,\n\nthree  ")
ids = [row["id"] for row in doc.rows()]
eq("break markers", [row["breakBefore"] for row in doc.rows()],
   [False, False, True])
doc.move(2, 0)
eq("move keeps separator slots", doc.serialize(), "  three,  one,\n\ntwo  ")
eq("move keeps ids", [row["id"] for row in doc.rows()], [ids[2], ids[0], ids[1]])
doc.replace(ids[0], "ONE")
eq("replace by stable id", doc.serialize(), "  three,  ONE,\n\ntwo  ")

doc = PromptDocument.parse("a,\n b,  c")
middle = doc.rows()[1]["id"]
doc.remove(middle)
eq("remove middle keeps separator before it", doc.serialize(), "a,\n c")
doc.remove(doc.rows()[-1]["id"])
eq("remove last removes preceding gap", doc.serialize(), "a")
doc.remove(doc.rows()[0]["id"])
eq("remove final clears formatting", doc.serialize(), "")

doc = PromptDocument.parse("a,\n b")
new_id = doc.insert(1, "middle")
eq("insert copies left style", doc.serialize(), "a,\n middle,\n b")
eq("insert id is stable", doc.rows()[1]["id"], new_id)
doc.insert(0, "first", ", ")
eq("insert explicit style", doc.serialize(), "first, a,\n middle,\n b")

for bad in ("", " x", "x ", "x,y"):
    try:
        PromptDocument.parse("a").insert(1, bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid payload accepted: {bad!r}")

rng = random.Random(0xC0FFEE)
alphabet = string.ascii_letters + string.digits + " ,()[]\\\t\r\n|:._-"
for _ in range(5000):
    sample = "".join(rng.choice(alphabet) for _ in range(rng.randrange(100)))
    doc = PromptDocument.parse(sample)
    eq("fuzz round trip", doc.serialize(), sample)
    if len(doc.items) > 1:
        skeleton = (doc.prefix, list(doc.gaps), doc.suffix)
        ids = sorted(item.id for item in doc.items)
        doc.move(rng.randrange(len(doc.items)), rng.randrange(len(doc.items)))
        eq("move formatting skeleton", (doc.prefix, doc.gaps, doc.suffix), skeleton)
        eq("move id set", sorted(item.id for item in doc.items), ids)

print("promptdoc: ok")

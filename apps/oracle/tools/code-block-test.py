#!/usr/bin/env python3
"""A fenced code block wraps inside the bubble, and says where it is.

Qt's markdown reader marks every fenced block `NonBreakableLines`, so a long
line lays out past the item's width and paints across whatever is beside it —
code spilling out of the bubble it belongs to [his, 2026-08-22]. `MdFormat`
(main.py) clears that flag on the document the reply is already drawing and
returns the character ranges of each run of code lines, which `MarkdownText.qml`
draws the embedded panel behind.

Pure document work, so no window and nothing on screen: the fixture is a
QTextDocument with the same markdown a reply carries.
"""
import json
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

from PySide6.QtCore import QObject                       # noqa: E402
from PySide6.QtGui import QGuiApplication, QTextDocument  # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                    # noqa: E402

app = QGuiApplication([])
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


MD = ("intro line\n\n"
      "```python\n"
      "def reconcile(everything, with_a_really_long_argument_name, more=None):\n"
      "    return everything\n"
      "```\n\n"
      "between the two\n\n"
      "```sh\nsudo rebuild-top\n```\n\n"
      "trailing prose with `inline code` in it\n")


class FakeQuickDoc(QObject):
    """What `styleCode` takes: anything with `textDocument()`. The real one is
    a QQuickTextDocument, which needs a window; this needs nothing."""

    def __init__(self, doc):
        super().__init__()
        self._doc = doc

    def textDocument(self):
        return self._doc


doc = QTextDocument()
doc.setMarkdown(MD)
fake = FakeQuickDoc(doc)


def nonbreakable():
    out = []
    b = doc.begin()
    while b.isValid():
        if b.blockFormat().nonBreakableLines():
            out.append(b.text()[:24])
        b = b.next()
    return out


check("Qt marks the code blocks unwrappable to begin with",
      len(nonbreakable()) == 3, repr(nonbreakable()))

md = oracle.MdFormat()
runs = json.loads(md.styleCode(fake))

check("after the pass nothing is unwrappable", nonbreakable() == [],
      repr(nonbreakable()))
check("the two fenced blocks come back as two runs", len(runs) == 2,
      json.dumps(runs))

text = doc.toPlainText()
if len(runs) == 2:
    first = text[runs[0]["start"]:runs[0]["end"]]
    second = text[runs[1]["start"]:runs[1]["end"]]
    check("the first run covers BOTH of its lines and nothing else",
          "def reconcile" in first and "return everything" in first
          and "intro line" not in first and "between the two" not in first,
          repr(first))
    check("the second run is the short block", second.strip() == "sudo rebuild-top",
          repr(second))
    check("prose with inline code is not a run",
          all("trailing prose" not in text[r["start"]:r["end"]] for r in runs))

again = json.loads(md.styleCode(fake))
check("a second pass finds the same runs (it is idempotent)", again == runs,
      json.dumps(again))

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)

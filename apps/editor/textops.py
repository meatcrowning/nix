#!/usr/bin/env python3
"""editor's editing algorithms — every one of Kate's line commands, on a
`QTextDocument`, in pure Python.

Why here and not in QML: these are all *multi-line, one-undo-step* edits, and a
`QTextCursor` between `beginEditBlock()`/`endEditBlock()` is the only way to get
that. Doing it in QML would mean string surgery on `TextEdit.text` — one giant
replace, which is one undo step that reverts the whole document, loses the
selection and re-runs the highlighter over every block. Kate's behaviour falls
out of the cursor API almost for free instead.

The contract every function here shares:

    op(doc, sel_start, sel_end, ...) -> (new_start, new_end)

It takes the view's selection as two character positions, edits the document,
and hands back where the selection should now be. **QML owns the cursor** — it
applies the returned pair with `select()`/`cursorPosition` — because the
`TextEdit` keeps its own `QTextCursor` and a position set from here would not
reach it. Nothing in this module touches a view, so all of it is testable
offscreen with no window at all (`tools/editor-test.py`, layer 1).

Positions, not (line, column): a document edit shifts every position after it,
and carrying columns through that is how an off-by-one in an indent command
becomes a lost character.
"""
import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QTextCursor, QTextDocument

from highlight import LANGS

#: Lines that make the NEXT line one level deeper (auto-indent). Per language
#: rather than one regex, because `then`/`do` are Lua's and `:` is Python's and
#: a shared rule would indent after a C++ `case x:` label twice.
_OPENERS = {
    "python": r"(?::)\s*(?:#.*)?$",
    "lua": r"\b(?:then|do|function|repeat|else)\s*$|\{\s*$|\(\s*$",
    "nix": r"[\{\[\(]\s*$|\b(?:let|in|rec)\s*$|=\s*$",
    "qml": r"[\{\[\(]\s*$",
    "cpp": r"[\{\[\(]\s*$",
    "json": r"[\{\[]\s*$",
    "sh": r"\b(?:then|do|else|in)\s*$|[\{\(]\s*$",
    "conf": None,
    "md": None,
    "text": None,
}


def indent_unit(use_tabs, width):
    return "\t" if use_tabs else " " * max(1, int(width))


def _line_span(doc, sel_start, sel_end):
    """The whole-line span covering a selection, as (first_block, last_block).

    A selection ending exactly at a line start does NOT include that line —
    Kate's rule, and the one every editor gets wrong at least once: shift-down
    to the start of line 5 then Tab must indent 1-4, not 1-5."""
    a, b = min(sel_start, sel_end), max(sel_start, sel_end)
    first = doc.findBlock(a)
    last = doc.findBlock(b)
    if b > a and last.position() == b and last.blockNumber() > first.blockNumber():
        last = last.previous()
    return first, last


def _blocks(doc, sel_start, sel_end):
    first, last = _line_span(doc, sel_start, sel_end)
    out, blk = [], first
    n = last.blockNumber()
    while blk.isValid() and blk.blockNumber() <= n:
        out.append(blk)
        blk = blk.next()
    return out


# ------------------------------------------------------------------- indenting

def indent(doc, sel_start, sel_end, use_tabs=False, width=4):
    """Tab / Ctrl+I. With a selection: one unit onto every line in it. Without:
    advance to the next tab STOP, so a 4-wide indent from column 2 inserts two
    spaces, not four (Kate, and every terminal)."""
    unit = indent_unit(use_tabs, width)
    if sel_start == sel_end:
        cur = QTextCursor(doc)
        cur.setPosition(sel_start)
        col = sel_start - cur.block().position()
        if use_tabs:
            ins = "\t"
        else:
            w = max(1, int(width))
            ins = " " * (w - (col % w) or w)
        cur.beginEditBlock()
        cur.insertText(ins)
        cur.endEditBlock()
        p = sel_start + len(ins)
        return p, p

    blocks = _blocks(doc, sel_start, sel_end)
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    added_first = 0
    for i, blk in enumerate(blocks):
        if blk.length() <= 1 and blk.blockNumber() != blocks[0].blockNumber():
            continue                     # never indent an empty line
        cur.setPosition(blk.position())
        cur.insertText(unit)
        if i == 0:
            added_first = len(unit)
    cur.endEditBlock()
    a, b = min(sel_start, sel_end), max(sel_start, sel_end)
    return a + added_first, b + _grow(doc, blocks, len(unit))


def _grow(doc, blocks, per):
    """How much a selection's END moves when `per` characters went onto each of
    `blocks` (skipping the empties `indent` skips)."""
    n = 1
    for blk in blocks[1:]:
        if blk.length() > 1:
            n += 1
    return n * per


def unindent(doc, sel_start, sel_end, use_tabs=False, width=4):
    """Shift+Tab / Ctrl+Shift+I. Removes ONE indent unit from each line's left
    edge — a hard tab, or up to `width` spaces, whichever is actually there. A
    line with no leading whitespace is left alone rather than eating its first
    character."""
    w = max(1, int(width))
    blocks = _blocks(doc, sel_start, sel_end)
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    removed_first, removed_total = 0, 0
    for i, blk in enumerate(blocks):
        text = blk.text()
        if text.startswith("\t"):
            take = 1
        else:
            take = 0
            while take < w and take < len(text) and text[take] == " ":
                take += 1
        if not take:
            continue
        cur.setPosition(blk.position())
        cur.setPosition(blk.position() + take, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        removed_total += take
        if i == 0:
            removed_first = take
    cur.endEditBlock()
    a, b = min(sel_start, sel_end), max(sel_start, sel_end)
    a = max(blocks[0].position(), a - removed_first)
    return a, max(a, b - removed_total)


# ------------------------------------------------------------------ commenting

def comment_prefix(lang):
    return LANGS.get(lang, LANGS["text"])["line"]


def block_pair(lang):
    return LANGS.get(lang, LANGS["text"])["block"]


def toggle_comment(doc, sel_start, sel_end, lang):
    """Ctrl+D / Ctrl+Shift+D, as one action: if every non-blank line in the
    selection is already commented, uncomment; otherwise comment.

    Returns `(start, end)` or **None** if the language has no comment syntax at
    all — json. The caller must then refuse VISIBLY (docs/DESIGN.md §10.2); this
    function will not invent a `//` for a format that does not have one.

    A language with no line comment but a block pair (markdown) gets the pair,
    wrapped around the selected lines."""
    prefix = comment_prefix(lang)
    if not prefix:
        pair = block_pair(lang)
        if not pair:
            return None
        return _toggle_block(doc, sel_start, sel_end, pair)

    blocks = _blocks(doc, sel_start, sel_end)
    live = [b for b in blocks if b.text().strip()]
    if not live:
        live = blocks
    all_commented = all(b.text().lstrip().startswith(prefix) for b in live)

    # Comment at the shallowest common indent, so a commented run keeps its
    # shape instead of being flattened to column 0.
    col = min((len(b.text()) - len(b.text().lstrip()) for b in live), default=0)

    cur = QTextCursor(doc)
    cur.beginEditBlock()
    first_delta, total = 0, 0
    for i, blk in enumerate(blocks):
        text = blk.text()
        if not text.strip() and len(blocks) > 1:
            continue
        if all_commented:
            at = len(text) - len(text.lstrip())
            if not text[at:].startswith(prefix):
                continue
            take = len(prefix)
            if text[at + take:at + take + 1] == " ":
                take += 1
            cur.setPosition(blk.position() + at)
            cur.setPosition(blk.position() + at + take,
                            QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
            d = -take
        else:
            cur.setPosition(blk.position() + min(col, len(text)))
            cur.insertText(prefix + " ")
            d = len(prefix) + 1
        total += d
        if i == 0:
            first_delta = d
    cur.endEditBlock()
    a, b = min(sel_start, sel_end), max(sel_start, sel_end)
    a = max(blocks[0].position(), a + first_delta)
    return a, max(a, b + total)


def _toggle_block(doc, sel_start, sel_end, pair):
    op, cl = pair
    blocks = _blocks(doc, sel_start, sel_end)
    start = blocks[0].position()
    end = blocks[-1].position() + blocks[-1].length() - 1
    cur = QTextCursor(doc)
    cur.setPosition(start)
    cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    body = cur.selectedText().replace(" ", "\n")
    stripped = body.strip()
    cur.beginEditBlock()
    if stripped.startswith(op) and stripped.endswith(cl):
        inner = stripped[len(op):-len(cl)].strip("\n")
        if inner.startswith(" "):
            inner = inner[1:]
        if inner.endswith(" "):
            inner = inner[:-1]
        cur.insertText(inner)
    else:
        cur.insertText(op + " " + body + " " + cl)
    cur.endEditBlock()
    return start, cur.position()


# ------------------------------------------------------------- line operations

def duplicate_lines(doc, sel_start, sel_end):
    """Ctrl+Alt+Down — the selected lines again, below, selection following the
    copy (so a second press duplicates the duplicate, like Kate)."""
    blocks = _blocks(doc, sel_start, sel_end)
    start = blocks[0].position()
    end = blocks[-1].position() + blocks[-1].length() - 1
    cur = QTextCursor(doc)
    cur.setPosition(start)
    cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    body = cur.selectedText().replace(" ", "\n")
    cur.beginEditBlock()
    cur.setPosition(end)
    cur.insertText("\n" + body)
    cur.endEditBlock()
    new_start = end + 1
    return new_start, new_start + len(body)


def delete_lines(doc, sel_start, sel_end):
    """Ctrl+K — the whole line(s) gone, newline included, cursor left at the
    start of what moved up into their place."""
    blocks = _blocks(doc, sel_start, sel_end)
    start = blocks[0].position()
    last = blocks[-1]
    end = last.position() + last.length()          # includes the newline
    doc_end = doc.characterCount() - 1
    if end > doc_end:                              # last line: eat the one before
        end = doc_end
        if start > 0:
            start -= 1
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    cur.setPosition(start)
    cur.setPosition(min(end, doc.characterCount() - 1),
                    QTextCursor.MoveMode.KeepAnchor)
    cur.removeSelectedText()
    cur.endEditBlock()
    p = min(start, doc.characterCount() - 1)
    return p, p


def move_lines(doc, sel_start, sel_end, delta):
    """Ctrl+Shift+Up / Ctrl+Shift+Down — swap the selected run with the line
    above or below, carrying the selection with it. Refuses at the ends of the
    document rather than deleting a line into nowhere."""
    blocks = _blocks(doc, sel_start, sel_end)
    first, last = blocks[0], blocks[-1]
    if delta < 0 and not first.previous().isValid():
        return sel_start, sel_end
    if delta > 0 and not last.next().isValid():
        return sel_start, sel_end

    start = first.position()
    end = last.position() + last.length() - 1
    cur = QTextCursor(doc)
    cur.setPosition(start)
    cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    body = cur.selectedText().replace(" ", "\n")
    off_a, off_b = min(sel_start, sel_end) - start, max(sel_start, sel_end) - start

    if delta < 0:
        other = first.previous()
        o_start, o_len = other.position(), other.length() - 1
        cur.beginEditBlock()
        cur.setPosition(o_start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(body + "\n" + other.text())
        cur.endEditBlock()
        new_start = o_start
    else:
        other = last.next()
        o_text = other.text()
        cur.beginEditBlock()
        cur.setPosition(start)
        cur.setPosition(other.position() + other.length() - 1,
                        QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(o_text + "\n" + body)
        cur.endEditBlock()
        new_start = start + len(o_text) + 1
    return new_start + off_a, new_start + off_b


# ------------------------------------------------------------ typing behaviour

def newline(doc, pos, use_tabs=False, width=4, lang="text"):
    """Return, with auto-indent. One edit, so one undo step undoes the newline
    AND its indent — two steps there is the classic "undo left me with a line
    of whitespace"."""
    blk = doc.findBlock(pos)
    text = blk.text()
    lead = text[:len(text) - len(text.lstrip())]
    # Only carry indentation from the part of the line BEFORE the caret: pressing
    # Return in the middle of an indented line must not indent by the tail.
    head = text[:pos - blk.position()]
    unit = indent_unit(use_tabs, width)
    opener = _OPENERS.get(lang)
    if opener and re.search(opener, head):
        lead += unit
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    cur.setPosition(pos)
    cur.insertText("\n" + lead)
    cur.endEditBlock()
    p = pos + 1 + len(lead)
    return p, p


def backspace_indent(doc, pos, use_tabs=False, width=4):
    """Backspace inside a line's leading whitespace removes a whole indent unit,
    not one space. Returns None when the caret is not in leading whitespace, so
    the caller lets the ordinary Backspace through untouched."""
    blk = doc.findBlock(pos)
    col = pos - blk.position()
    text = blk.text()
    if col == 0 or text[:col].strip():
        return None
    if text[col - 1] == "\t":
        take = 1
    else:
        w = max(1, int(width))
        back = (col % w) or w
        take = 0
        while take < back and col - take - 1 >= 0 and text[col - take - 1] == " ":
            take += 1
    if not take:
        return None
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    cur.setPosition(pos - take)
    cur.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
    cur.removeSelectedText()
    cur.endEditBlock()
    p = pos - take
    return p, p


# ----------------------------------------------------------- find and replace

def _find_flags(case, whole):
    f = QTextDocument.FindFlag(0)
    if case:
        f |= QTextDocument.FindFlag.FindCaseSensitively
    if whole:
        f |= QTextDocument.FindFlag.FindWholeWords
    return f


def _matcher(query, regex, case):
    """Either a QRegularExpression or the plain string, ready for
    `QTextDocument.find`. Returns None for a regex that does not compile — the
    caller reports that, it is never a silent no-match."""
    if not regex:
        return query
    opts = QRegularExpression.PatternOption.NoPatternOption
    if not case:
        opts |= QRegularExpression.PatternOption.CaseInsensitiveOption
    rx = QRegularExpression(query, opts)
    return rx if rx.isValid() else None


def find(doc, query, from_pos, backward=False, regex=False, case=False,
         whole=False, wrap=True):
    """The next match, as (start, end), or None.

    Searches from `from_pos` and WRAPS once — a find that stops dead at the end
    of the file is the single most-complained-about behaviour in any editor.
    Whether it wrapped is worth reporting, so the caller compares the result to
    `from_pos` rather than this returning a flag nobody reads."""
    if not query:
        return None
    m = _matcher(query, regex, case)
    if m is None:
        return None
    flags = _find_flags(case, whole)
    if backward:
        flags |= QTextDocument.FindFlag.FindBackward
    cur = doc.find(m, from_pos, flags)
    if cur.isNull() and wrap:
        cur = doc.find(m, doc.characterCount() - 1 if backward else 0, flags)
    if cur.isNull():
        return None
    return min(cur.position(), cur.anchor()), max(cur.position(), cur.anchor())


def match_count(doc, query, regex=False, case=False, whole=False, cap=20000):
    """How many matches the document holds, and which one (1-based) starts at or
    after `mark` — the `3/17` the find bar draws. Capped, because a pathological
    regex over a huge file must not hang the GUI thread."""
    if not query:
        return []
    m = _matcher(query, regex, case)
    if m is None:
        return []
    flags = _find_flags(case, whole)
    out, pos = [], 0
    while len(out) < cap:
        cur = doc.find(m, pos, flags)
        if cur.isNull():
            break
        s, e = min(cur.position(), cur.anchor()), max(cur.position(), cur.anchor())
        out.append((s, e))
        pos = e if e > s else s + 1
    return out


def replace_one(doc, sel_start, sel_end, replacement):
    """Replace exactly what is selected. The caller is responsible for the
    selection actually BEING a match — the find bar only offers replace when it
    is, so replace can never quietly overwrite something else."""
    a, b = min(sel_start, sel_end), max(sel_start, sel_end)
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    cur.setPosition(a)
    cur.setPosition(b, QTextCursor.MoveMode.KeepAnchor)
    cur.insertText(replacement)
    cur.endEditBlock()
    p = a + len(replacement)
    return p, p


def replace_all(doc, query, replacement, regex=False, case=False, whole=False):
    """Every match, in ONE undo step. Returns how many — the honest report the
    footer prints, because "replace all" with no count is indistinguishable from
    "replace all" that matched nothing (docs/DESIGN.md §10.2).

    Walks backwards so an earlier replacement cannot shift a later match's
    position, and `\\1` backreferences are expanded only in regex mode."""
    spans = match_count(doc, query, regex, case, whole)
    if not spans:
        return 0
    rx = None
    if regex:
        try:
            rx = re.compile(query, 0 if case else re.IGNORECASE)
        except re.error:
            return 0
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    for s, e in reversed(spans):
        cur.setPosition(s)
        cur.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        text = replacement
        if rx is not None:
            frag = cur.selectedText().replace(" ", "\n")
            mm = rx.fullmatch(frag)
            if mm is not None:
                try:
                    text = mm.expand(replacement)
                except (re.error, IndexError):    # a backref with no group
                    text = replacement
        cur.insertText(text)
    cur.endEditBlock()
    return len(spans)

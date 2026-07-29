"""board's store: `~/nix/docs/board.md` in, drawable rows out — and back again.

THE FILE IS THE DATABASE, and it is plain markdown on purpose: agents read and
write it as text, it lives in the private `docs/` repo and syncs between the two
machines every five minutes, and he can edit it by hand in any editor. So this
module is a *parser plus a line editor*, never a serialiser:

  * `parse(text)` reads the four sections into structures the QML draws.
  * every write is a TARGETED LINE EDIT on the raw line list — tick a box,
    replace the `>` answer block, relocate a whole decision from NEEDS YOU into
    IN FLIGHT — and returns the whole file back. Nothing this module did not
    deliberately change comes out different, byte for byte.
  * `edit(path, fn)` wraps one of those in the advisory lock, the digest
    re-check and the atomic write, so the app, `board-watch` and
    `tools/boardctl.py` can all write this file while he has it open.

A round-trip that reformats his prose, re-wraps a table or reorders a section is
a bug, and `tools/board-test.py` asserts exactly that: parse -> write with no
change -> the bytes are identical; tick one box -> exactly one line differs.

THE SHAPE OF THE FILE (its own preamble states the conventions; this is what the
parser keys on):

    ## NEEDS YOU              decisions, `### <n>. <title>` each
        prose                 what the decision is
        - [ ] option          alternatives, wrapped continuations indented
        > answer              HIS free text. Always beats the options
        <!-- answered-on: h -->  WHICH MACHINE he answered on. Drawn by nothing;
                              board-watch runs on both and only fires for its
                              own host. `set_answer_host()` is its only writer
        *If unanswered:* ...  what happens if he never answers
    ## WAITING ON YOU TO DO   `- ` bullets. Actions, not decisions. Each one
                              starts with a TAG (`QUESTION:`, `INFORMATION:`,
                              `COMPLETION:`, `PARTIAL:`, `FAILED:`) and then a
                              short description; background goes after that.
                              `add_todo_bullet` refuses one that does not —
                              READING is unaffected, an old untagged bullet
                              parses and draws exactly as it always did
    ## IN FLIGHT              a | table |: what / where / notes
    ## LANDED                 `### <date>` groups of | commit | what | when |
                              tables, plus prose blocks between them. `when` is
                              the commit's own local time, 12-hour, and is
                              OPTIONAL: a row written before it existed, or one
                              with no commit to read a time from, has two cells

Everything else in the file — the `# Board` preamble, the `---` rules, anything
a future agent adds that this parser has no case for — is carried through
untouched and simply not drawn. **An unrecognised line is never an error and is
never rewritten.**

GLYPH MAPPING (docs/DESIGN.md §2.3). Every drawable string goes through
`pylib/glyphs.px()` HERE, at ingest, once per load — the file is full of the
characters More Perfect DOS VGA lacks (`—`, `…`, `§`), and one of them in a
`PixelText` under `FixedHeight` packing clips the whole line it is in. The RAW
line is kept beside the mapped one, because the raw line is what gets written
back: mapping a line and then saving it would quietly rewrite his prose into
ASCII.
"""
import contextlib
import datetime
import fcntl
import hashlib
import os
import re
import tempfile
import time

from glyphs import px

# The store. Absolute like every other path in this tree (`apps/AGENTS.md`):
# `$HOME` is /home/lam on both machines this repo builds.
BOARD_PATH = os.path.expanduser("~/nix/docs/board.md")

_H2 = re.compile(r"^##\s+(.*?)\s*#*\s*$")
_H3 = re.compile(r"^###\s+(.*?)\s*#*\s*$")
_OPTION = re.compile(r"^(\s*)-\s+\[([ xX])\]\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_NUMBERED = re.compile(r"^(\d+)\.\s+(.*)$")
_IF_UNANS = re.compile(r"^\*If unanswered:\*\s*(.*)$", re.I)
#: WHICH MACHINE he answered on. board-watch now runs on `top` AND on `book`
#: (`home/srvs/board-watch.nix`) and `docs/` syncs both ways every five minutes,
#: so without this the same answer is picked up twice, by two agents, on two
#: checkouts of the same repos. The host an answer was typed on works it.
#:
#: It is an HTML comment on a line of its own, immediately under the `>` block,
#: because this file is HIS and must go on reading cleanly: markdown renders it
#: as nothing, `reader` draws nothing for it, and the board app draws nothing
#: for it either. **The parser owns it** — it is never prose, is written only by
#: `set_answer_host()` below, and is carried through a relocation with the rest
#: of the item's raw lines like everything else.
_ANSWERED_ON = re.compile(r"^\s*<!--\s*answered-on:\s*([A-Za-z0-9._-]+)\s*-->\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_HR = re.compile(r"^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")

SECTIONS = ("needs", "todo", "flight", "landed")


def _section_of(title):
    t = title.strip().lower()
    if t.startswith("needs you"):
        return "needs"
    if t.startswith("waiting on you"):
        return "todo"
    if t.startswith("in flight"):
        return "flight"
    if t.startswith("landed"):
        return "landed"
    return None


def _strip_em(s):
    """Emphasis markers carry nothing here — §2.2's "bold emphasis is a
    deliberately accepted loss", the same reading `reader/mdparse.py` makes.
    Backticks go too: board draws prose in one tone, and the app that renders
    markdown properly is `reader`, one titlebar cell away."""
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)   # a link reads as its label
    return s


def text(s):
    """A raw line -> what gets drawn. Strip, de-emphasise, glyph-map."""
    return px(_strip_em(s).strip())


def slug(s):
    """A decision's stable key. It survives the item being renumbered or
    re-worded a little, and it is what a draft answer is filed under, so it must
    not depend on anything the app itself writes into the file."""
    s = re.sub(r"^\d+\.\s*", "", _strip_em(s).strip().lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "item"


def _table_cells(line):
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def parse(src):
    """The whole file -> {lines, digest, needs, todo, flight, landed, intro}.

    `lines` is the raw file split with its line endings kept, and every index in
    the result points into it. That is the contract the write side depends on.
    """
    lines = src.splitlines(keepends=True)
    plain = [ln.rstrip("\n") for ln in lines]

    out = {"lines": lines, "digest": digest(src),
           "needs": [], "todo": [], "flight": [], "landed": [],
           "intro": {"needs": [], "todo": [], "flight": [], "landed": []}}

    sec = None
    item = None           # the decision being built
    date = None           # the LANDED group being built
    prose = None          # an open prose paragraph, in whichever section

    def close_prose():
        # Emphasis and glyph mapping happen on the JOINED paragraph, never per
        # line: `**a bold span** that wraps` in the source is two lines, and
        # stripping each of them separately leaves both `**` markers on screen.
        nonlocal prose
        if prose is not None:
            prose["text"] = text(prose.pop("raw", ""))
        if prose is not None and prose["text"]:
            if sec == "landed" and date is not None:
                date["prose"].append(prose)
            elif sec == "needs" and item is not None:
                item["body"].append(prose)
            elif sec == "todo" and prose["kind"] == "bullet":
                out["todo"].append(prose)
            elif sec in out["intro"]:
                out["intro"][sec].append(prose)
        prose = None

    def close_item():
        nonlocal item
        if item is not None:
            for opt in item["options"]:
                opt["label"] = text(opt.pop("raw"))
            item["ifUnanswered"] = text(item.pop("ifRaw"))
            out["needs"].append(item)
        item = None

    for i, ln in enumerate(plain):
        m2 = _H2.match(ln)
        if m2:
            close_prose()
            close_item()
            date = None
            sec = _section_of(m2.group(1))
            continue
        if sec is None:
            continue

        m3 = _H3.match(ln)
        if m3:
            close_prose()
            if sec == "needs":
                close_item()
                title = m3.group(1)
                mn = _NUMBERED.match(title)
                item = {"key": slug(title), "num": mn.group(1) if mn else "",
                        "title": text(mn.group(2) if mn else title),
                        "titleLine": i, "body": [], "options": [],
                        "answerFrom": -1, "answerTo": -1, "answer": "",
                        "answerRaw": [], "ifUnanswered": "", "ifRaw": "",
                        "answerHost": "", "hostLine": -1}
            elif sec == "landed":
                close_item()
                date = {"date": text(m3.group(1)), "rows": [], "prose": [],
                        "line": i}
                out["landed"].append(date)
            continue

        if not ln.strip() or _HR.match(ln):
            close_prose()
            continue

        # ---- tables: IN FLIGHT's one, and each LANDED group's ----
        if ln.lstrip().startswith("|"):
            close_prose()
            if _TABLE_SEP.match(ln):
                continue
            cells = _table_cells(ln)
            head = [c.lower() for c in cells]
            if sec == "flight":
                if head[:1] == ["what"]:
                    continue                       # the header row
                out["flight"].append({
                    "what": text(cells[0] if cells else ""),
                    "where": text(cells[1]) if len(cells) > 1 else "",
                    "notes": text(cells[2]) if len(cells) > 2 else "",
                    "line": i})
            elif sec == "landed" and date is not None:
                if head[:1] == ["commit"]:
                    continue
                # `when` is the THIRD cell and it is optional, in both
                # directions: rows written before it existed have two cells and
                # parse with an empty time, and an older copy of this app
                # reading a newer file simply never looks at cells[2]. That is
                # why it is last and not between the two — `what` stays at a
                # fixed index whatever the row's age, and `board.md` syncs
                # between the two machines with either app on either end.
                date["rows"].append({
                    "commit": text(cells[0] if cells else ""),
                    "what": text(cells[1]) if len(cells) > 1 else "",
                    "when": text(cells[2]) if len(cells) > 2 else "",
                    "line": i})
            continue

        # ---- a decision's options ----
        mo = _OPTION.match(ln) if sec == "needs" and item is not None else None
        if mo:
            close_prose()
            item["options"].append({"line": i, "checked": mo.group(2) in "xX",
                                    "raw": mo.group(3), "label": "",
                                    "index": len(item["options"])})
            continue
        if (sec == "needs" and item is not None and item["options"]
                and ln.startswith((" ", "\t")) and item["answerFrom"] < 0
                and not _QUOTE.match(ln)):
            # a wrapped option line — it belongs to the option above it
            item["options"][-1]["raw"] += " " + ln.strip()
            continue

        # ---- his answer ----
        mq = _QUOTE.match(ln) if sec == "needs" and item is not None else None
        if mq:
            close_prose()
            if item["answerFrom"] < 0:
                item["answerFrom"] = i
            item["answerTo"] = i
            item["answerRaw"].append(mq.group(1))
            continue

        # ---- which machine he answered on ----
        mh = _ANSWERED_ON.match(ln) if sec == "needs" and item is not None else None
        if mh:
            close_prose()
            item["answerHost"] = mh.group(1)
            item["hostLine"] = i
            continue

        # ---- what happens if he never answers: the whole point of the file ----
        mi = _IF_UNANS.match(ln) if sec == "needs" and item is not None else None
        if mi:
            close_prose()
            item["ifRaw"] = mi.group(1)
            prose = {"kind": "ifunans", "raw": ""}     # continuations follow
            continue

        # ---- everything else is prose, joined until a blank line ----
        mb = _BULLET.match(ln)
        if prose is not None and prose["kind"] == "ifunans" and item is not None:
            item["ifRaw"] = (item["ifRaw"] + " " + ln.strip()).strip()
            continue
        # `endLine` is the LAST raw line of this paragraph, and it exists so a
        # bullet can be removed as a unit: a WAITING ON YOU TO DO item routinely
        # wraps onto indented continuation lines, and deleting only `line` would
        # leave his half-sentence behind as an orphan paragraph.
        if mb:
            close_prose()
            prose = {"kind": "bullet", "raw": mb.group(2), "line": i, "endLine": i}
        elif prose is not None:
            prose["raw"] = (prose["raw"] + " " + ln.strip()).strip()
            prose["endLine"] = i
        else:
            prose = {"kind": "para", "raw": ln.strip(), "line": i, "endLine": i}

    close_prose()
    close_item()

    for it in out["needs"]:
        it["answer"] = "\n".join(it["answerRaw"]).strip()
        it["answered"] = bool(it["answer"]) or any(o["checked"] for o in it["options"])
    return out


# ---------------------------------------------------------------- writing back
# Every edit below returns a NEW list of lines with exactly the lines it names
# replaced. Nothing re-renders, nothing re-wraps, nothing is reordered — the
# rest of the file is the same object it was read as.

def _set_box(line, checked):
    """`- [ ] x` <-> `- [x] x`, touching nothing else on the line (not the
    indent, not the trailing whitespace, not the newline)."""
    return re.sub(r"\[[ xX]\]", "[x]" if checked else "[ ]", line, count=1)


def toggle_option(lines, item, index, checked):
    """Choose an option, or clear it.

    The options of one decision are ALTERNATIVES, so this is a radio and not a
    set of independent flags: choosing one clears the others. Choosing the one
    already chosen clears it, so a mind can be changed without an agent's help —
    §10.2, refuse-and-undo rather than a dead end.
    """
    out = list(lines)
    for opt in item["options"]:
        want = checked and opt["index"] == index
        if opt["checked"] != want:
            out[opt["line"]] = _set_box(out[opt["line"]], want)
    return out


def set_answer(lines, item, answer):
    """Replace the `>` block with his free text (or restore it to empty).

    An empty answer restores the line's own MARKER verbatim — `> ` with the
    store's trailing space, or a bare `>` in a file that spells it that way — so
    writing an answer and clearing it again leaves the file byte-identical
    rather than silently normalising his punctuation.
    """
    out = list(lines)
    frm, to = item["answerFrom"], item["answerTo"]
    if frm < 0:
        return out                       # no answer slot: not ours to invent
    eol = "\n" if out[to].endswith("\n") else ""
    body = (answer or "").strip()
    if not body and not item["answer"]:
        return out                       # nothing to say and nothing was said
    if not body:
        mk = re.match(r"^(\s{0,3}>\s?)", out[frm].rstrip("\n"))
        new = [(mk.group(1) if mk else "> ") + eol]
    else:
        new = ["> " + ln.rstrip() + "\n" for ln in body.split("\n")]
        new[-1] = new[-1][:-1] + eol
    return out[:frm] + new + out[to + 1:]


def set_answer_host(lines, item, host):
    """Stamp (or clear) the machine an answer was given on. One line, no prose.

    board-watch runs on BOTH machines now and `docs/board.md` syncs both ways,
    so "he answered this" is not on its own enough to fire: two watchers would
    read the same `[x]` and put two agents on one job. **The host an answer was
    typed on works it** — race-free by construction, and it matches how he uses
    the two machines. This is where that fact is recorded.

    An HTML comment, so his file still reads cleanly (see `_ANSWERED_ON`), and
    written as a targeted line edit like everything else here: replaced in place
    if it is already there, inserted directly under the `>` block if it is not,
    and REMOVED when `host` is empty — an item with no answer must carry no
    stamp, or clearing an answer would leave a marker behind for a machine that
    no longer has anything to do.

    The caller passes lines it has already computed the answer edit into, so the
    indices must come from a parse of THOSE lines, not of the file before them.
    """
    out = list(lines)
    at = item.get("hostLine", -1)
    if not host:
        return out[:at] + out[at + 1:] if at >= 0 else out
    mark = "<!-- answered-on: %s -->" % host
    if at >= 0:
        if out[at].rstrip("\n").strip() == mark:
            return out                          # already ours: byte-identical
        return out[:at] + [mark + ("\n" if out[at].endswith("\n") else "")] \
            + out[at + 1:]
    anchor = item["answerTo"]
    if anchor < 0:
        anchor = (item["options"][-1]["line"] if item["options"]
                  else item["titleLine"])
    if anchor < 0 or anchor >= len(out):
        return out
    if out[anchor].endswith("\n"):
        return out[:anchor + 1] + [mark + "\n"] + out[anchor + 1:]
    # the anchor is the last line of a file with no trailing newline
    return out[:anchor] + [out[anchor] + "\n", mark] + out[anchor + 1:]


# ------------------------------------------------- moving an item BETWEEN sections
# Answering a decision here STARTS something (`AGENTS.md`), and until this
# existed the item went on sitting in NEEDS YOU while an agent worked it — the
# board asking him for something he had already given. These are the line edits
# that move it on: NEEDS YOU -> IN FLIGHT when work starts, IN FLIGHT -> LANDED
# when it lands, and IN FLIGHT -> NEEDS YOU, verbatim, when the agent died.
#
# Same contract as everything above: they RELOCATE raw lines and insert whole
# ones. Nothing is re-rendered, nothing is re-wrapped, and a decision that comes
# back comes back byte-for-byte as he wrote it — which is why the block is moved
# rather than summarised.


class BoardError(Exception):
    """Something about the file's shape stopped an edit. Never a crash: the
    callers of this module report it (§10) rather than dying on it."""


def section_bounds(lines, name):
    """(start, end) for one `## ` section: the heading's own line, and the line
    the NEXT `## ` heading starts on (or the end of the file). (-1, -1) if the
    section is not there — never invent a heading, that is a store-shape
    decision and not this module's to make."""
    start = -1
    for i, ln in enumerate(lines):
        m = _H2.match(ln.rstrip("\n"))
        if not m:
            continue
        if start < 0:
            if _section_of(m.group(1)) == name:
                start = i
        else:
            return start, i
    return (start, len(lines)) if start >= 0 else (-1, -1)


def _content_end(lines, start, end):
    """Where new content goes at the bottom of a section: after its last real
    line, before the trailing blanks and the `---` rule that separates it from
    the next heading."""
    at = end
    while at > start + 1:
        prev = lines[at - 1].rstrip("\n")
        if not prev.strip() or _HR.match(prev):
            at -= 1
        else:
            break
    return at


def _table_span(lines, start, end):
    """(first, after_last) of the FIRST contiguous pipe table in [start, end).

    "First" matters: IN FLIGHT carries a second `Queued` table under a prose
    block, and the parser reads both as flight rows. A row appended after the
    last of those would silently join the queue.
    """
    i = start
    while i < end and not lines[i].lstrip().startswith("|"):
        i += 1
    if i >= end:
        return -1, -1
    j = i
    while j < end and lines[j].lstrip().startswith("|"):
        j += 1
    return i, j


def cell(s):
    """Anything -> one table cell. A `|` would end the cell and a newline would
    end the row, so both are neutralised; nothing else about his text changes."""
    return " ".join(str(s).replace("|", r"\|").split())


def item_span(lines, item):
    """(start, end) of a decision's raw lines — `### n. title` down to the next
    heading or rule, trailing blank line included, so a cut and a re-insert
    reproduce the spacing he had."""
    start = item["titleLine"]
    for i in range(start + 1, len(lines)):
        s = lines[i].rstrip("\n")
        if _H2.match(s) or _H3.match(s) or _HR.match(s):
            return start, i
    return start, len(lines)


def raw_title(lines, item):
    """A decision's title AS IT IS SPELLED IN THE FILE, number stripped.

    Not `item["title"]`: that one has been through `text()` at ingest, which is
    a one-way trip (`—` -> `-`, backticks gone). Writing it into a table cell
    would quietly rewrite his prose into ASCII — the exact bug this module's
    docstring exists to prevent. Anything going BACK into the file comes from
    here; the mapping happens on the next read, for drawing, as it should.
    """
    m = _H3.match(lines[item["titleLine"]].rstrip("\n"))
    t = m.group(1) if m else item["title"]
    mn = _NUMBERED.match(t)
    return (mn.group(2) if mn else t).strip()


def raw_option(lines, opt):
    """An option's label as spelled in the file, wrapped continuations joined."""
    m = _OPTION.match(lines[opt["line"]].rstrip("\n"))
    if not m:
        return opt["label"]
    out = [m.group(3).strip()]
    for i in range(opt["line"] + 1, len(lines)):
        s = lines[i].rstrip("\n")
        if (not s.strip() or not s.startswith((" ", "\t"))
                or _OPTION.match(s) or _QUOTE.match(s)):
            break
        out.append(s.strip())
    return " ".join(out)


def cut_item(lines, item):
    """Lift a decision out of NEEDS YOU. Returns (lines without it, its block)."""
    a, b = item_span(lines, item)
    return lines[:a] + lines[b:], lines[a:b]


def add_needs_item(lines, block, before=None):
    """Put a decision back into NEEDS YOU, verbatim.

    `before` is the raw heading line the item used to sit above, recorded at the
    cut. With it, a decision that is handed back lands where it was and the file
    is byte-identical to before the move — his numbering stays in order, and a
    failed agent leaves no trace in the store at all. Without it (that heading is
    gone now), the item goes to the end of the section rather than guessing.
    """
    s, e = section_bounds(lines, "needs")
    if s < 0:
        raise BoardError("there is no `## NEEDS YOU` section to put it back in")
    at = -1
    if before:
        want = before.rstrip("\n")
        for i in range(s + 1, e):
            if lines[i].rstrip("\n") == want:
                at = i
                break
    if at < 0:
        at = _content_end(lines, s, e)
    head, tail = list(lines[:at]), list(lines[at:])
    blk = [ln if ln.endswith("\n") else ln + "\n" for ln in block]
    while blk and not blk[-1].strip():        # its own trailing blank(s)...
        blk.pop()
    if head and head[-1].strip():
        blk.insert(0, "\n")
    if tail and tail[0].strip():              # ...restored only if the tail
        blk.append("\n")                      # does not already supply one
    return head + blk + tail


FLIGHT_HEAD = ["| What | Where | Notes |\n", "|---|---|---|\n"]
LANDED_HEAD = ["| Commit | What | When |\n", "|---|---|---|\n"]


def flight_row(what, where="", notes=""):
    return "| %s | %s | %s |\n" % (cell(what), cell(where), cell(notes))


def add_flight_row(lines, row):
    """Append a row to IN FLIGHT's own table (not the `Queued` one below it).

    The table header is written if the section has no table yet — that is the
    documented shape of this section, unlike a `##` heading, which is never
    invented.
    """
    s, e = section_bounds(lines, "flight")
    if s < 0:
        raise BoardError("there is no `## IN FLIGHT` section to move it into")
    a, b = _table_span(lines, s + 1, e)
    if a < 0:
        at = _content_end(lines, s, e)
        new = (["\n"] if lines[at - 1:at] and lines[at - 1].strip() else []) \
            + FLIGHT_HEAD + [row]
        return lines[:at] + new + lines[at:]
    return lines[:b] + [row] + lines[b:]


def remove_row(lines, line_index):
    """Drop one table row by its index into the raw line list."""
    if line_index < 0 or line_index >= len(lines):
        raise BoardError("that row is no longer where it was")
    return lines[:line_index] + lines[line_index + 1:]


# --------------------------------------------- clearing a chore off the TO DO list
# His words: *"i should be able to clear the 'to do, when you feel like it' stuff
# if i wish. currently i cannot remove it via board program"*. Agents add bullets
# there (`add_todo_bullet`, `boardmove.note`) and nothing ever took one away, so
# the section only grew.
#
# ONE verb, `remove`, and no "done". A chore he has finished and a chore he no
# longer wants both end the same way — the line goes — and the record of why it
# existed is already in LANDED, which is where an agent writes what it did. A
# second "done" state would make this list a checklist with a completion to
# account for, which is the debt the no-pressure requirement exists to refuse.
#
# `remove_row` above is not enough for this and cannot be made to be: a table row
# is exactly one line by definition, and a bullet is one line plus however many
# it wrapped onto.


def todo_span(lines, todo):
    """(start, end) of one WAITING ON YOU TO DO bullet, continuations included.

    Refuses rather than guesses if the line it was told about is no longer a
    bullet: the app computes this from a parse and the file has three other
    writers, so a stale index must cost a refusal and not somebody else's line.
    """
    a = todo.get("line", -1)
    b = todo.get("endLine", a)
    if a < 0 or b < a or b >= len(lines):
        raise BoardError("that line is no longer where it was")
    if not _BULLET.match(lines[a].rstrip("\n")):
        raise BoardError("that line is no longer where it was")
    return a, b + 1


def remove_todo(lines, todo):
    """Drop one bullet, and touch nothing else.

    Deliberately NOT tidy: the blank lines around it are left exactly as they
    are, even when the section empties out completely. Squashing them would be
    this module rewriting lines it was not asked about — the one thing its
    docstring forbids — and a stray blank line reads as nothing at all, while a
    reflowed section is a diff he has to understand in a file that syncs to the
    other machine.
    """
    a, b = todo_span(lines, todo)
    return lines[:a] + lines[b:]


def add_todo_block(lines, doc, block, before=None):
    """Put a removed bullet's raw lines back — where they were, if that is still
    there. The undo half of `remove_todo`.

    `before` is the raw line the bullet used to sit above, recorded at the
    removal; the same anchor `add_needs_item` uses and for the same reason. Only
    BULLET lines are matched against it: the line after the last bullet in the
    section is a blank or a `---`, neither of which identifies a position (the
    first blank in the section is the one under the heading), so those fall
    through to "after the last bullet" — which for the last bullet is exactly
    where it came from.
    """
    s, e = section_bounds(lines, "todo")
    if s < 0:
        raise BoardError("there is no `## WAITING ON YOU TO DO` section left")
    at = -1
    if before:
        want = before.rstrip("\n")
        if _BULLET.match(want):
            for i in range(s + 1, e):
                if lines[i].rstrip("\n") == want:
                    at = i
                    break
    if at < 0:
        inside = [t for t in doc["todo"] if s < t["line"] < e]
        if inside:
            at = max(t.get("endLine", t["line"]) for t in inside) + 1
        else:
            at = s + 1
            while at < e and not lines[at].strip():
                at += 1
    return lines[:at] + list(block) + lines[at:]


def landed_row(commit, what, when=""):
    """One LANDED row. THREE cells when there is a time, two when there is not.

    A row with no time is written the old way rather than with an empty third
    cell, because half the rows in the file have no commit to read a time from
    (`no change`, a decision settled) and `| x |  |` is a hole a human reads as
    a mistake. The parser treats a missing third cell and an empty one alike.
    """
    when = cell(when)
    body = "| `%s` | %s" % (cell(commit), cell(what))
    return body + (" | %s |\n" % when if when else " |\n")


def _widen_landed_head(lines, a, b):
    """Give a two-column LANDED table its `When` header, in place.

    A markdown row with more cells than its header has drops the extras in every
    renderer there is — and this file is read in `reader` and on GitHub, not
    only by this parser. So the first time a timed row joins an old group, the
    group's header line and its separator are replaced (two lines, nothing
    else). A table that already has three columns is left byte-identical.
    """
    if a < 0 or b <= a + 1:
        return lines
    head = _table_cells(lines[a].rstrip("\n"))
    if len(head) >= 3 or [c.lower() for c in head[:1]] != ["commit"]:
        return lines
    if not _TABLE_SEP.match(lines[a + 1].rstrip("\n")):
        return lines
    return lines[:a] + list(LANDED_HEAD) + lines[a + 2:]


def add_landed_row(lines, commit, what, date=None, when=""):
    """Append `| commit | what | when |` under today's `### <date>` group,
    creating the group at the TOP of LANDED if today has none. LANDED is newest
    first and append-only — the file says so in its own preamble."""
    date = date or datetime.date.today().isoformat()
    row = landed_row(commit, what, when)
    s, e = section_bounds(lines, "landed")
    if s < 0:
        raise BoardError("there is no `## LANDED` section to record it in")

    grp, first_grp = -1, -1
    for i in range(s + 1, e):
        m = _H3.match(lines[i].rstrip("\n"))
        if not m:
            continue
        if first_grp < 0:
            first_grp = i
        if m.group(1).strip() == date:
            grp = i
            break
    if grp < 0:
        at = first_grp if first_grp >= 0 else _content_end(lines, s, e)
        return lines[:at] + ["### %s\n" % date, "\n"] + LANDED_HEAD + [row, "\n"] \
            + lines[at:]

    end = e
    for i in range(grp + 1, e):
        if _H3.match(lines[i].rstrip("\n")):
            end = i
            break
    a, b = _table_span(lines, grp + 1, end)
    if a < 0:
        at = grp + 1
        while at < end and not lines[at].strip():
            at += 1
        return lines[:at] + LANDED_HEAD + [row, "\n"] + lines[at:]
    if when:
        lines = _widen_landed_head(lines, a, b)
    return lines[:b] + [row] + lines[b:]


# ------------------------------------------- every WAITING bullet says WHAT IT IS
# His words: *"messages in the to do section should start with either QUESTION:
# INFORMATION: COMPLETION: or something like those, maybe others too?, so that
# the user can easily know what that message is about. any sort of elaboration or
# background should go after the short description of the message"*.
#
# So a bullet is TAG, then a SHORT description, then anything else — and the TAG
# is checked HERE, at the one function every writer of that section already goes
# through (`boardmove.note`, `boardmove.stall`, the `why` of `give_back`, and
# board-watch's four failure templates). One choke point, so a new writer cannot
# be added that forgets.
#
# The set is SHORT and every tag in it has a writer that emits it; there is no
# tag here nothing can produce. What each one claims:
TODO_TAGS = (
    #: it asks him something and nothing moves until he answers. NOT a decision
    #: — a decision is an item in NEEDS YOU (`boardmove.ask`), with options and
    #: an `*If unanswered:*` line. This is the small "say the word and X" an
    #: agent leaves behind on its way out.
    "QUESTION",
    #: a fact he may want and nothing is being asked of him. The orchestrator's
    #: "handed to Marbas, nothing landed yet" and `stall`'s moved row.
    "INFORMATION",
    #: the work is finished and on his machine.
    "COMPLETION",
    #: part of it landed and part did not — including "it needs a rebuild, which
    #: an agent may not run". The honest tag for most of what a worker writes.
    "PARTIAL",
    #: it was attempted and NOTHING landed. Every mechanical failure path here
    #: emits this one, and it is the reason the set is not just his three: the
    #: system must never let a failure read as information.
    "FAILED",
)

_TODO_TAG = re.compile(r"^\s*[-*+]\s+(%s):\s+\S" % "|".join(TODO_TAGS))


def _tag_refusal(line):
    return BoardError(
        "a WAITING ON YOU TO DO bullet starts with one of %s, then a SHORT "
        "description, then any background - e.g. `- COMPLETION: **the thing** - "
        "what it does now`. Got: %s"
        % ("/".join(t + ":" for t in TODO_TAGS), line.strip()[:80]))


def check_todo_tag(bullet):
    """Refuse a WAITING ON YOU TO DO bullet that does not say what it is.

    A REFUSAL and not a silent default, because a wrong tag is worse than the
    error an agent can read and fix in one retry: `INFORMATION:` in front of a
    failure would be this system telling him nothing is wrong.

    **Every line is checked, not just the first.** An orchestrator's note is one
    line per task and it passes them in one string, so the second and later ones
    are bullets too — and an unindented one that did not begin `- ` landed in the
    store on 2026-07-29 as a paragraph glued to the bullet above it, drawn as
    part of somebody else's message. A line that is INDENTED is a wrapped
    continuation of the bullet above and carries no tag of its own; that is where
    his "elaboration or background" goes.
    """
    for line in bullet.split("\n"):
        if not line.strip() or line[:1].isspace():
            continue                      # blank, or a wrapped continuation
        if not _TODO_TAG.match(line):
            raise _tag_refusal(line)
    if not bullet.strip():
        raise _tag_refusal(bullet)
    return bullet


def add_todo_bullet(lines, doc, bullet):
    """One `- ` bullet into WAITING ON YOU TO DO, after the last one there."""
    check_todo_tag(bullet)
    if not bullet.endswith("\n"):
        bullet += "\n"
    if doc["todo"]:
        at = max(t["line"] for t in doc["todo"]) + 1
        return lines[:at] + [bullet] + lines[at:]
    s, e = section_bounds(lines, "todo")
    if s < 0:
        # No section: put it at the end of the file rather than inventing a
        # heading. He still sees it; the store's shape is still his.
        return lines + ([] if not lines or lines[-1].endswith("\n") else ["\n"]) \
            + ["\n", bullet]
    at = s + 1
    while at < e and not lines[at].strip():
        at += 1
    return lines[:at] + [bullet] + lines[at:]


# ------------------------------------------------------- one edit, done safely
# board(1), the five-minute docs sync, board-watch and any agent with a terminal
# all write this file. Two defences, and they are separate on purpose: the
# ADVISORY LOCK keeps the writers that opt in from interleaving at all, and the
# DIGEST RE-CHECK catches the one that did not (the app takes no lock — it
# re-reads and refuses, `main.py:_commit`).

def lock_path(path):
    """Beside the state dir, never beside the store: `docs/` is a git checkout a
    timer commits and pushes, and a stray lock file would sync to book."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    d = os.path.join(base, "board")
    os.makedirs(d, exist_ok=True)
    key = hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]
    return os.path.join(d, "edit-%s.lock" % key)


@contextlib.contextmanager
def locked(path, timeout=20.0):
    """Advisory `flock` around one read-modify-write. Best effort: a machine
    where the lock cannot be created still gets the digest re-check."""
    try:
        f = open(lock_path(path), "w")
    except OSError:
        yield False
        return
    try:
        end = time.time() + timeout
        got = False
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.time() >= end:
                    break
                time.sleep(0.1)
        try:
            yield got
        finally:
            if got:
                fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        f.close()


def edit(path, fn, attempts=5):
    """Read -> `fn(doc)` -> write, atomically, and only onto the exact bytes the
    edit was computed from.

    `fn` returns the new raw line list, or None to write nothing. It may raise
    `BoardError` to refuse. Returns True if the file changed.
    """
    last = None
    for n in range(attempts):
        with locked(path):
            src = read(path)
            doc = parse(src)
            out = fn(doc)
            if out is None:
                return False
            new = "".join(out)
            if new == src:
                return False
            if digest(read(path)) == doc["digest"]:
                write(path, new)
                return True
            last = "board.md changed under the edit"
        time.sleep(0.15 * (n + 1))
    raise BoardError(last or "could not get a clean read of board.md")


def digest(src):
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def read(path=BOARD_PATH):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def write(path, src):
    """Atomically. The pattern is `apps/player/atomicsave.py`'s, which is the
    established one in this tree: a temp file in the TARGET'S OWN DIRECTORY (so
    the rename cannot become a cross-device copy), fsync'd before it is
    published, then `os.replace()` — a reader sees either the whole old file or
    the whole new one, and an interruption anywhere leaves the original exactly
    as it was. That matters more here than usual: this file is a git checkout
    that a systemd timer commits and pushes every five minutes, and half a
    board.md would sync to the other machine.

    (`atomicsave.atomic_save` itself is mutagen's, for audio containers, so the
    rules are reused rather than the function.)
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".board-", suffix=".md")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(src.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    try:                                  # durability for the rename itself
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass

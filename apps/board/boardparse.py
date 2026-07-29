"""board's store: `~/nix/docs/board.md` in, drawable rows out — and back again.

THE FILE IS THE DATABASE, and it is plain markdown on purpose: agents read and
write it as text, it lives in the private `docs/` repo and syncs between the two
machines every five minutes, and he can edit it by hand in any editor. So this
module is a *parser plus a line editor*, never a serialiser:

  * `parse(text)` reads the four sections into structures the QML draws.
  * every write is a TARGETED LINE EDIT on the raw line list — tick a box,
    replace the `>` answer block — and returns the whole file back. Nothing this
    module did not deliberately change comes out different, byte for byte.

A round-trip that reformats his prose, re-wraps a table or reorders a section is
a bug, and `tools/board-test.py` asserts exactly that: parse -> write with no
change -> the bytes are identical; tick one box -> exactly one line differs.

THE SHAPE OF THE FILE (its own preamble states the conventions; this is what the
parser keys on):

    ## NEEDS YOU              decisions, `### <n>. <title>` each
        prose                 what the decision is
        - [ ] option          alternatives, wrapped continuations indented
        > answer              HIS free text. Always beats the options
        *If unanswered:* ...  what happens if he never answers
    ## WAITING ON YOU TO DO   `- ` bullets. Actions, not decisions
    ## IN FLIGHT              a | table |: what / where / notes
    ## LANDED                 `### <date>` groups of | commit | what | tables,
                              plus prose blocks between them

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
import hashlib
import os
import re
import tempfile

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
                        "answerRaw": [], "ifUnanswered": "", "ifRaw": ""}
            elif sec == "landed":
                close_item()
                date = {"date": text(m3.group(1)), "rows": [], "prose": []}
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
                date["rows"].append({
                    "commit": text(cells[0] if cells else ""),
                    "what": text(cells[1]) if len(cells) > 1 else "",
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
        if mb:
            close_prose()
            prose = {"kind": "bullet", "raw": mb.group(2), "line": i}
        elif prose is not None:
            prose["raw"] = (prose["raw"] + " " + ln.strip()).strip()
        else:
            prose = {"kind": "para", "raw": ln.strip(), "line": i}

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

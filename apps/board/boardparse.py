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
                              `COMPLETION:`, `PARTIAL:`, `FAILED:` — or a
                              colonless `SUMMONED`/`COMMANDED`, which are drawn
                              under `information`) and then a
                              summary of about a dozen words at most; background
                              goes on indented continuation lines under it.
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
#: WHEN an item was put on the board — his: *"mesages in the needs you section
#: should all have the time they were placed on the board indicated on them."*
#:
#: The same shape as `answered-on` above and for the same reasons: an HTML
#: comment on a line of its own, invisible in markdown and in `reader`, owned by
#: this parser and never prose. It is a local ISO timestamp to the minute
#: (`2026-07-29T15:42`), which is the writer's business; what gets DRAWN is
#: `format_placed()` below, and the two are deliberately not the same string —
#: the store keeps the sortable one, the screen gets the readable one.
#:
#: It is OPTIONAL in both directions, exactly like LANDED's `when`: this file
#: syncs between `top` and `book` and either may be running the older app, so an
#: item without one draws no time at all rather than an empty or invented one,
#: and an older parser carries the line through untouched as it does anything
#: else it has no case for.
#:
#: WHERE it sits is per shape. A decision: on the line right under its
#: `### <n>. <title>`. A WAITING bullet: on the line right under the bullet's
#: last line, so it is inside the span `todo_span()` removes and restores.
_PLACED = re.compile(r"^\s*<!--\s*placed:\s*([0-9T:+.\-]+)\s*-->\s*$")
#: WHO put an item on the board — the agent's name if one wrote it, otherwise the
#: program that did. Same shape as `placed` above, same reasons, and the same
#: OPTIONALITY, which here is not a nicety: every entry that predates this stamp
#: has none, `board.md` syncs between `top` and `book` with either app on either
#: end, and one writer of the three lives outside this tree
#: (`home/srvs/board-watch-files/board-watch.py`) and does not emit it yet. So an
#: unstamped entry parses and draws exactly as it always did, with the gutter
#: simply saying nothing above the time — never `unknown`, never a blank row.
#:
#: It sits ABOVE `placed:` in both shapes, and that order is load-bearing for the
#: WAITING bullet: `placed:` is the line that CLOSES the bullet's span, so a `by:`
#: written under it would fall outside `todo_span()` and be left behind when the
#: bullet is removed.
_BY = re.compile(r"^\s*<!--\s*by:\s*([A-Za-z0-9._-]+)\s*-->\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_HR = re.compile(r"^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")

SECTIONS = ("needs", "todo", "flight", "landed")


def placed_now(when=None):
    """The `<!-- placed: ... -->` line for an item being written right now.

    Local time, to the minute. Seconds would be noise on a board whose whole
    point is that nothing here is urgent, and the zone is left off because both
    machines are in his one zone and a `Z` would make it a fact about UTC that
    he then has to convert in his head.
    """
    when = when or datetime.datetime.now()
    return "<!-- placed: %s -->\n" % when.strftime("%Y-%m-%dT%H:%M")


def by_now(who):
    """The `<!-- by: ... -->` line for an item being written right now, or `""`.

    Empty in, empty out, deliberately: a writer that cannot say who it is writes
    NO stamp rather than one saying `unknown`, so "nobody recorded it" and "an
    entry older than this stamp" are the same state on screen and in the file.
    Anything outside the stamp's charset is dropped for the same reason — a
    mangled attribution is worse than none.
    """
    s = " ".join(str(who or "").split())
    return "<!-- by: %s -->\n" % s if _BY.match("<!-- by: %s -->" % s) else ""


def format_placed(raw):
    """`2026-07-29T15:42` -> `jul 29 3:42 pm`. `""` for anything unreadable.

    12-hour and lowercase, the same clock LANDED's `when` is written in
    (`boardmove.commit_time`) — one way of saying a time on this board.

    It carries the DATE as well, and that is the difference from LANDED: a
    landed row sits under a `### <date>` heading that already says which day,
    whereas an item in NEEDS YOU can sit there for a week with nothing around it
    to date it, and a bare `3:42 pm` on a five-day-old question would read as
    this afternoon.

    **It is an absolute time and it must stay one.** No "3 days ago", no age, no
    badge: the no-pressure requirement (`AGENTS.md`) forbids a clock running
    against him, and a relative string is exactly that. This is a fact about the
    past, like the commit hash beside a LANDED row.

    Unreadable is a normal answer, not a failure — the store is full of items
    written before this existed, and they draw no time rather than a wrong one.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
        # `%-d`/`%-I` are GNU extensions; strip the zeros where it is certain.
        day = dt.strftime("%d").lstrip("0")
        if fmt == "%Y-%m-%d":
            return "%s %s" % (dt.strftime("%b").lower(), day)
        clock = dt.strftime("%I:%M %p").lstrip("0").lower()
        return "%s %s %s" % (dt.strftime("%b").lower(), day, clock)
    return ""


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
            # ...and the same mapping over each HALF of a bullet, for the view
            # that draws the summary and the elaboration as two blocks. The one
            # thing the split costs is a `**bold span**` that wraps ACROSS the
            # first line — its two markers land in different halves and neither
            # is stripped. `text` is the joined string and is unaffected, so the
            # cost is confined to a writer who wraps mid-emphasis, and the rule
            # for this section is a short summary line anyway.
            if "headRaw" in prose:
                prose["summary"] = text(prose.pop("headRaw"))
                prose["detail"] = text(prose.pop("tailRaw", ""))
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
                        "answerHost": "", "hostLine": -1,
                        "placedRaw": "", "placed": "", "placedLine": -1,
                        "by": "", "byLine": -1}
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

        # ---- when it was put on the board ----
        # Checked for BOTH shapes, before the prose branch below would swallow
        # it as a wrapped continuation of the bullet it belongs to. A decision
        # takes it onto the item; a WAITING bullet takes it onto the bullet AND
        # extends that bullet's `endLine` over it, so removing the bullet
        # removes its stamp and the one-level undo puts both back (`todo_span`).
        # Anywhere else it is an unrecognised line: carried through, not drawn.
        # ---- ...and WHO put it there ----
        # Above `placed:`, and it must NOT close a bullet's prose: `placed:` is
        # the line that does that, and closing here would leave the stamp under
        # it outside the span. A decision has no span, so that branch closes as
        # `answered-on` does.
        mby = _BY.match(ln)
        if mby:
            if sec == "needs" and item is not None:
                close_prose()
                item["by"] = mby.group(1)
                item["byLine"] = i
                continue
            if sec == "todo" and prose is not None and prose["kind"] == "bullet":
                prose["by"] = mby.group(1)
                prose["endLine"] = i
                continue

        mp = _PLACED.match(ln)
        if mp:
            if sec == "needs" and item is not None:
                close_prose()
                item["placedRaw"] = mp.group(1)
                item["placedLine"] = i
                continue
            if sec == "todo" and prose is not None and prose["kind"] == "bullet":
                prose["placedRaw"] = mp.group(1)
                prose["endLine"] = i
                close_prose()
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
        # A bullet keeps its FIRST line apart from what wrapped under it — his:
        # *"in the to do section, it should show the PARTIAL INFORMATION whatever
        # text, then a single line summarizing, a new line, and THEN the
        # elaboration if needed."* `raw` still holds the whole thing joined, so
        # every existing consumer (`tag_of`, removal, `reply`, the menus, the
        # glyph check) is untouched; `headRaw`/`tailRaw` are what the view draws
        # as two blocks. See `close_prose` for the one thing this costs.
        if mb:
            close_prose()
            prose = {"kind": "bullet", "raw": mb.group(2), "line": i, "endLine": i,
                     "headRaw": mb.group(2), "tailRaw": ""}
        elif prose is not None:
            prose["raw"] = (prose["raw"] + " " + ln.strip()).strip()
            if "tailRaw" in prose:
                prose["tailRaw"] = (prose["tailRaw"] + " " + ln.strip()).strip()
            prose["endLine"] = i
        else:
            prose = {"kind": "para", "raw": ln.strip(), "line": i, "endLine": i}

    close_prose()
    close_item()

    for it in out["needs"]:
        it["answer"] = "\n".join(it["answerRaw"]).strip()
        it["answered"] = bool(it["answer"]) or any(o["checked"] for o in it["options"])
        it["placed"] = format_placed(it["placedRaw"])
    for t in out["todo"]:
        t["tag"] = tag_of(t["text"])
        t["placedRaw"] = t.get("placedRaw", "")
        t["by"] = t.get("by", "")
        t["summary"] = t.get("summary", t["text"])
        t["detail"] = t.get("detail", "")
        t["placed"] = format_placed(t["placedRaw"])
    out["todoGroups"] = todo_groups(out["todo"])
    return out


# ------------------------------------------------- what a bullet IS, for drawing
#
# `TODO_TAGS` (below) is the WRITE-side rule: a bullet says what it is in its
# first word. These two are the READ-side use of the same word — the view groups
# the bullets by it instead of drawing one flat list, which is his: *"the
# information, completion, partial etc of a message should be used to organize
# them on the board. under the needs you section there should be sub sections
# for each of these headers"*.
#
# It is computed HERE, once per load, for the same reason the glyph map is: a
# view that regrouped per delegate would do it on every scroll. Nothing about
# the STORE changes — no sub-headings are ever written into `board.md`, the raw
# lines and every index into them are untouched, and a group holds the very same
# bullet dicts the flat `todo` list does, so removing one and putting it back is
# the same edit it always was.
#
# THE ORDER, and why it is this one. It is by WHAT THE BULLET ASKS OF HIM, and
# it is fixed by tag — not by age, not by count, not by when it arrived, so a
# bullet never moves between two readings and no group is ranked against a
# clock (the no-pressure requirement, `AGENTS.md`).
#
#   QUESTION     nothing moves until he says a word. It is the only group that
#                is waiting on him, so it is first.
#   FAILED       something was attempted and nothing landed. Second because the
#                one thing this system must never do is let a failure sink to
#                the bottom of a list of good news.
#   PARTIAL      some of it landed and some did not; there is a remainder.
#   COMPLETION   done, and on his machine. A record.
#   INFORMATION  a fact; nothing is asked of him at all. Last for that reason.
#
# An untagged bullet — the store is full of ones written before the tag rule —
# comes FIRST, under no heading at all, so nothing claims it as something it is
# not. Reading is untouched by the tag rule and it is untouched by this too.
TODO_ORDER = ("QUESTION", "FAILED", "PARTIAL", "COMPLETION", "INFORMATION")


def tag_of(text):
    """The tag a drawn bullet leads with, or `""` for one that leads with none.

    The colon first, so an OLD `INFORMATION: **x** - SUMMONED: Marbas ...` line
    still reads as the `INFORMATION` it was written as; only then the bare
    first word, which is how the two summon tags are written now.
    """
    s = str(text or "").strip()
    head = s.split(":", 1)[0].strip()
    if head in TODO_TAGS:
        return head
    head = s.split(None, 1)[0] if s else ""
    return head if head in BARE_TAGS else ""


def section_of(tag):
    """The subsection a tag is DRAWN under — itself, unless `TAG_SECTION` says
    otherwise. `SUMMONED` reads as `SUMMONED` on the line and files under
    `information`, which is exactly what he asked for."""
    return TAG_SECTION.get(tag, tag)


def todo_groups(todos):
    """The WAITING bullets as `[{tag, label, items}]`, in `TODO_ORDER`.

    A tag with no bullets gets no entry, so it gets no heading — an empty
    sub-section would be a slot he has to fill, which is the shape this board
    refuses everywhere else.
    """
    out = []
    untagged = [t for t in todos if not t.get("tag")]
    if untagged:
        out.append({"tag": "", "label": "", "items": untagged})
    for tag in TODO_ORDER:
        # By SECTION, not by tag: a `SUMMONED` bullet keeps its own word on the
        # line and is drawn under `information` with the rest of the facts.
        items = [t for t in todos if section_of(t.get("tag")) == tag]
        if items:
            out.append({"tag": tag, "label": tag.lower(), "items": items})
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
# So a bullet is TAG, then a SHORT description, then anything else — and the
# SHAPE of "anything else" is his too: *"it should show the PARTIAL INFORMATION
# whatever text, then a single line summarizing, a new line, and THEN the
# elaboration if needed. it shouldnt really elaborate that much though"*. One
# line of summary on the bullet's own line; the elaboration, if there has to be
# one, on INDENTED continuation lines under it, and **a sentence or two, not a
# paragraph**. `parse()` splits the two into `summary`/`detail` and the view
# draws them as two blocks with a gap; `text` stays the joined string every
# other consumer already reads.
#
# "SHORT" got a number on 2026-07-29, because prose alone did not hold: he came
# back with *"still too long"* after the ordering rule above landed. The first
# line after the tag is AT MOST about a dozen words (`SUMMARY_MAX_WORDS`,
# enforced by `check_short_summary` at the same choke point); everything past
# that budget belongs on the indented continuation lines. A code span counts as
# ONE word — his interpolated words are data, and a note saying a worker died
# must never be refused for the length of the thing it died on.
#
# The TAG is checked HERE, at the one function every writer of that section goes
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
    #: a fact he may want and nothing is being asked of him. `stall`'s moved
    #: row, and a knob the orchestrator turned. A SUMMON is no longer one of
    #: these — it has its own tag now (below) and files under this one.
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
    #: a minister was started for a piece of work. [his, 2026-07-30] *"the
    #: message posted to the board when a minister is summoned should read
    #: `SUMMONED [agent] [for/to] [task]` instead of what it is now. it should
    #: NOT say INFORMATION: at the beginning HOWEVER the summoned message
    #: should still appear in the information subsection of todo"*. So it is a
    #: tag of its own that FILES under information (`TAG_SECTION`) rather than
    #: a sentence sitting behind `INFORMATION:`.
    "SUMMONED",
    #: ...and the same announcement for an item handed to a worker that was
    #: ALREADY running. The two words are the whole difference he reads off the
    #: board, so they are siblings in every rule that touches either.
    "COMMANDED",
)

#: The two that are written WITHOUT a colon — `SUMMONED Marbas (`w1ff021`) for
#: the flashing titlebar` — because that is the shape he asked for, verbatim.
#: A colon is still accepted everywhere they are read: the store holds notes
#: written the old way and they must keep rendering.
BARE_TAGS = ("SUMMONED", "COMMANDED")

#: Which SUBSECTION a tag is drawn under, when that is not the tag itself. Only
#: the two summon words, and only because he asked for the word `SUMMONED` on
#: the line and the bullet under `information` — the grouping is a view over the
#: store and the store keeps the tag he reads.
TAG_SECTION = {"SUMMONED": "INFORMATION", "COMMANDED": "INFORMATION"}

#: `TAG:` for every tag, or a bare `TAG ` for the two summon words.
_TAG_ALT = "(?:%s):|(?:%s)" % ("|".join(TODO_TAGS), "|".join(BARE_TAGS))

_TODO_TAG = re.compile(r"^\s*[-*+]\s+(?:%s)\s+\S" % _TAG_ALT)


def _tag_refusal(line):
    return BoardError(
        "a WAITING ON YOU TO DO bullet starts with one of %s, then a SHORT "
        "description, then any background - e.g. `- COMPLETION: **the thing** - "
        "what it does now`, or `- SUMMONED Marbas (`w1ff021`) for the thing`. "
        "Got: %s"
        % ("/".join(t + ("" if t in BARE_TAGS else ":") for t in TODO_TAGS),
           line.strip()[:80]))


def is_tagged(text):
    """Does this text START a message — `COMPLETION: ...`, with or without its
    `- `? The public half of `_TODO_TAG`, for the writers that have to tell one
    message from the next (`boardctl._note_text`, `check_one_ask`)."""
    return bool(_TODO_TAG.match("- " + text.lstrip().lstrip("-*+ ")))


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


#: His limit, 2026-07-29: after the tag, the first line is a summary of "at
#: most about a dozen words". Twelve, because that is what a dozen is; the
#: counting is generous instead (a code span is one word, bare punctuation is
#: none), so the slack "about" implies is in the measure, not the number.
SUMMARY_MAX_WORDS = 12

_TAG_LEAD = re.compile(r"^\s*[-*+]?\s*(?:%s)\s*" % _TAG_ALT)


def _summary_words(line):
    """The countable words of a bullet's first line, after the tag.

    A code span collapses to one word — it is interpolated DATA (his typed
    task, a path) and the mechanical failure templates must stay writable
    whatever is in it. `**` is ignored, so the headline's words count like any
    others: a twenty-word headline is exactly the disease the cap is for.
    A token with no letter or digit in it (the `-` separator) is not a word.
    """
    rest = _CODE.sub("code", _TAG_LEAD.sub("", line, count=1))
    return [w for w in rest.replace("**", " ").split()
            if any(c.isalnum() for c in w)]


def check_short_summary(bullet):
    """Refuse a bullet whose FIRST line runs past about a dozen words.

    His rule, and a repeat one — the prompts said "a SHORT description" and he
    came back with "still too long", so the length is now mechanical at the
    same choke point as the tag. Every unindented line is a bullet of its own
    and is measured on its own; the indented continuation lines under it are
    where the elaboration lives and are not measured at all. A REFUSAL, like
    the tag check: the writing agent reads it and moves its prose down a line.
    """
    for line in bullet.split("\n"):
        if not line.strip() or line[:1].isspace():
            continue
        words = _summary_words(line)
        if len(words) > SUMMARY_MAX_WORDS:
            raise BoardError(
                "the first line of a WAITING ON YOU TO DO bullet is the tag, "
                "then a summary of at most about a dozen words (%d max, this "
                "one has %d) - move the elaboration to INDENTED continuation "
                "lines under it. Got: %s"
                % (SUMMARY_MAX_WORDS, len(words), line.strip()[:80]))
    return bullet


# ------------------------------------------------ ONE BOARD ITEM PER ASK
# His rule, 2026-07-29: *"messages should be SEPARATED"* — when an agent reports
# on several things, each one is its own bullet. Never several asks folded into
# one message.
#
# It is not a style preference, it is how the board CLEARS. Replying to a bullet
# clears that bullet (bc1454d), so an ask folded into another agent's paragraph
# is cleared by a reply that was never about it, and survives nowhere he can
# see. That happened: worker Purson (`w88cd31`) was handed four asks and wrote
# ONE bullet — *"PARTIAL: **times on everything under needs you** - landed, plus
# two more items you sent while I was in there"* — whose headline named the
# first. He replied to it; asks 2-4 went with it.
#
# The write path already SUPPORTS separation: `boardmove.note` prefixes `- ` per
# line, so several unindented lines in one call are several bullets, each with
# its own `<!-- placed: -->` stamp, each clearable on its own. What was missing
# was anything that stopped a writer bundling instead. These four checks are
# that, and they are STRUCTURAL — a machine cannot read intent, but every one of
# these shapes is a second ask wearing a disguise:
#
#   1. a second TAG further along a bullet's line. `boardctl.py note 'A: x'
#      'B: y'` used to join its argv with a space and land one bullet saying
#      both; now argv that looks like that is split into bullets instead
#      (`boardctl.cmd_note`) and anything that still gets through is refused.
#   2. a TAG on an INDENTED line — an ask hidden in the elaboration, which is
#      the one place the tag check deliberately does not look.
#   3. more than one `**headline**` on one line. The shape is
#      `TAG: **what you were asked** - what you did`; a second bold span in it
#      is a second thing you were asked.
#   4. a sub-bullet list under a bullet, or a phrase that COUNTS other work
#      ("plus two more items", "the other three"). His shape for the detail is
#      *"a sentence or two, not a paragraph"* about THAT ask; a list or a tally
#      is the rest of the run hiding under the first item's headline.
#
# What it deliberately does NOT do is guess at prose. Two asks written as two
# plain sentences pass, and the prompts (`boardwork.RULES`/`WORKER_PROMPT` rule
# 9) carry the rest. Mechanism where mechanism reaches; a rule where it does not.
#
# **His own words are DATA, not prose to be read**: the mechanical failure
# templates interpolate what he typed, and a note that says a worker died must
# never be refused because of how he phrased the thing it died on. So they pass
# it through `oneline()` and the checks skip anything inside a `` ` `` span.
#: The two summon words are NOT looked for here, colon or no colon. A bare
#: `SUMMONED` mid-line is as likely to be the ordinary English word, and a
#: `SUMMONED:` mid-line is the shape every summon note was written in before
#: 2026-07-30 — `INFORMATION: **subject** - SUMMONED: Marbas (`id`) to x` — so
#: reading one as a second ask would refuse the very line this tag replaced.
_INLINE_TAG = re.compile(r"\S[ \t]+(?:%s):[ \t]"
                         % "|".join(t for t in TODO_TAGS if t not in BARE_TAGS))
_SUB_BULLET = re.compile(r"^[ \t]+[-*+][ \t]+\S")
_BOLD = re.compile(r"\*\*.+?\*\*")
_CODE = re.compile(r"`[^`]*`")
_COUNTS_MORE = re.compile(
    r"\b(?:plus|and|with|besides)\s+(?:the\s+)?"
    r"(?:two|three|four|five|six|\d+)\s+(?:more|other|further|remaining)\b"
    r"|\bthe\s+(?:second|third|fourth|fifth|other|remaining)\s+"
    r"(?:item|items|ask|asks|task|tasks|thing|things)\b"
    r"|\b(?:two|three|four|five|\d+)\s+(?:more|other|further)\s+"
    r"(?:item|items|ask|asks|task|tasks|thing|things)\b", re.I)


def _bundle_refusal(why, line):
    return BoardError(
        "one board item per ask - %s. Reply clears a bullet, so an ask folded "
        "into another one is cleared by a reply that was never about it. Make "
        "it its own `note` call, or its own unindented line in this one. Got: "
        "%s" % (why, line.strip()[:80]))


def check_one_ask(bullet):
    """Refuse a WAITING ON YOU TO DO message that bundles more than one ask.

    See the block comment above for the four shapes and why each one is a second
    ask. Called from `add_todo_bullet` beside `check_todo_tag` — the same one
    choke point, so a new writer cannot be added that forgets this either.
    """
    for line in bullet.split("\n"):
        if not line.strip():
            continue
        bare = _CODE.sub("``", line)
        if bare[:1].isspace():                       # an indented continuation
            if is_tagged(bare):
                raise _bundle_refusal(
                    "this line is tagged, so it is an ask of its own and must "
                    "not hide in another item's elaboration", line)
            if _SUB_BULLET.match(bare):
                raise _bundle_refusal(
                    "a list under a bullet is several things in one message; "
                    "the elaboration is a sentence or two about THIS ask", line)
        else:
            # ...without the `- ` marker: the tag it introduces is the bullet's
            # own and only a LATER one is a second message.
            body = re.sub(r"^[-*+][ \t]+", "", bare.lstrip())
            if _INLINE_TAG.search(body):
                raise _bundle_refusal(
                    "there is a second tag further along this line, so it is "
                    "two messages written as one", line)
            if len(_BOLD.findall(body)) > 1:
                raise _bundle_refusal(
                    "a bullet leads with ONE `**headline**` naming the one "
                    "thing it is about", line)
        # The tally is looked for in the PROSE, never in the `**headline**`:
        # *"INFORMATION: **the third item** - ..."* is a bullet naming what it
        # is about, not one counting the rest of the run into itself.
        if _COUNTS_MORE.search(_BOLD.sub("", bare)):
            raise _bundle_refusal(
                "it counts other work into this item; that work gets its own "
                "bullet, with its own headline he can reply to", line)
    return bullet


def oneline(text, limit=160, code=False, words=None):
    """His words, or another agent's title, made safe to interpolate into a
    bullet. Collapses every run of whitespace — a newline in the middle of a
    template used to make its second line an untagged bullet, and the whole
    failure note was then refused, so nothing said the worker had died — and
    caps the length. ASCII `...`, never the ellipsis glyph: the pixel font has
    none (docs/DESIGN.md §2.3).

    `code=True` returns it as a CODE SPAN, which is the honest one for anything
    he typed: the checks above skip a span, so his `**` and his tag words reach
    the board unedited instead of being read as structure. Use the plain form
    only where the text has to sit inside a `**headline**`, and accept that it
    loses those two markers there — a glob like `apps/**/qml` is exactly why
    this is a flag and not a blanket strip.

    `words=` caps the WORD count too. A span already counts as one word to
    `check_short_summary`, so only the plain form needs this: a headline built
    from his row title must fit the first line's dozen-word budget whatever he
    called the row.
    """
    s = " ".join(str(text or "").split()).replace("`", "'")
    if not code:
        s = s.replace("**", "")
        for t in TODO_TAGS:
            s = re.sub(r"\b%s:" % t, t, s)
    if words is not None and len(s.split()) > words:
        s = " ".join(s.split()[:words]) + "..."
    if len(s) > limit:
        s = s[:limit].rstrip() + "..."
    return ("`%s`" % s) if code and s else s


def add_todo_bullet(lines, doc, bullet, when=None, by=None):
    """One `- ` bullet into WAITING ON YOU TO DO, after the last one there.

    Each top-level bullet in `bullet` gets its own `<!-- placed: -->` line
    under it (`placed_now`), because `boardmove.note()` writes one call per
    MESSAGE and the orchestrator routinely puts several bullets in one — a
    single stamp at the end of the block would time-stamp the last of them and
    leave the rest looking older than the file itself. An indented line is a
    wrapped continuation and keeps its place above the stamp.
    """
    check_todo_tag(bullet)
    check_one_ask(bullet)
    # After the bundling check on purpose: a message that is two asks in one is
    # refused as THAT, not as a long line, so the retry fixes the real thing.
    check_short_summary(bullet)
    if not bullet.endswith("\n"):
        bullet += "\n"
    # `by:` above `placed:`, and both under EVERY top-level bullet: the stamps
    # are per-bullet for the reason the docstring gives, and `placed:` stays last
    # because it is the line that closes the bullet's span (`_BY`, `todo_span`).
    stamp = [s for s in (by_now(by), placed_now(when)) if s]
    block = []
    for ln in bullet.splitlines(keepends=True):
        if block and _BULLET.match(ln.rstrip("\n")) and not ln[:1].isspace():
            block += stamp
        block.append(ln)
    block += stamp
    if doc["todo"]:
        # `endLine`, not `line`: a bullet routinely wraps onto indented
        # continuation lines, and anchoring on the first line of the last one
        # inserted the new bullet INTO the middle of it. Its own stamp made that
        # certain rather than merely likely — `add_todo_block`, the undo half,
        # has always used `endLine`.
        at = max(t.get("endLine", t["line"]) for t in doc["todo"]) + 1
        return lines[:at] + block + lines[at:]
    s, e = section_bounds(lines, "todo")
    if s < 0:
        # No section: put it at the end of the file rather than inventing a
        # heading. He still sees it; the store's shape is still his.
        return lines + ([] if not lines or lines[-1].endswith("\n") else ["\n"]) \
            + ["\n"] + block
    at = s + 1
    while at < e and not lines[at].strip():
        at += 1
    return lines[:at] + block + lines[at:]


# -------------------------------- a summon note dies when its result arrives
# His rule, 2026-07-29: *"once an agent give the board a completed, partial, etc
# message - its related summon information message should be removed since the
# user would already know that part."*
#
# The orchestrator's note is a START, never a result (`boardwork.RULES`), so it
# writes one `SUMMONED` line per task it handed out — *"SUMMONED Marbas
# (`wd690a4`) to add commit times"*, and did the same behind an `INFORMATION:`
# tag before 2026-07-30, which the store still holds. That line is worth reading for as long as
# nothing has come back, and the moment the worker posts its own
# `COMPLETION:`/`PARTIAL:`/`FAILED:` it is worse than noise: two bullets about
# one piece of work, the upper one announcing what the lower one has finished.
#
# It happens HERE rather than in `boardctl`, because the store has more than one
# writer of a result — `boardctl note` for a worker that finished, board-watch's
# `WORKER_FAIL` for one that died mid-sentence — and a rule implemented in one
# caller is a rule that is true in one caller.
#
# CONSERVATIVE BY CONSTRUCTION. A wrong deletion loses something he cannot get
# back; an undeleted summon note is a line he has already read. So:
#
#   * only a bullet tagged `SUMMONED`/`COMMANDED` — or, in the shape written
#     before 2026-07-30, an `INFORMATION` one that SAYS `summoned <Name>` or
#     `commanded <Name>` — is a candidate. A `QUESTION:`, a decision, an
#     ordinary `INFORMATION:` fact and the result itself are never touched.
#   * the ID matches first and the NAME only second, and a name match is
#     accepted only for a summon note that carries no id at all — a name can be
#     moved off a live agent (`boardagents.pick_name`), an id never is.
#   * ambiguity is a REFUSAL to act: two candidates for one worker, or none,
#     and every summon note stays exactly where it is.
RESULT_TAGS = ("COMPLETION", "PARTIAL", "FAILED")

#: `SUMMONED Marbas` — or `COMMANDED Marbas`, which is the same announcement
#: for a worker that was already running (his rule, 2026-07-29: `SUMMONED:` is a
#: NEW agent, `COMMANDED:` is one given more work). **Both words have to be read
#: here.** The note is retired by the worker's own result either way, and a
#: `COMMANDED:` line this regex did not match would sit under that result
#: forever announcing work he has already been told the end of — the exact
#: two-bullets-about-one-piece-of-work this whole mechanism exists to prevent.
#:
#: The words were the lowercase verbs `summoned`/`commanded` until 2026-07-29,
#: when he restyled them as uppercase tags before the name; both spellings and
#: the optional colon are matched, because the store still holds notes written
#: the old way and they must keep being retired.
#:
#: Then the coded id if the writer put one there. The id
#: is PARENTHESISED, immediately after the name — the shape the orchestrator's
#: prompt gives it, and the only one read: something in parentheses further along
#: the line is a path or a log file, not an identity. Written as a code span in
#: the store, so the backticks are optional here and this reads the DRAWN text
#: (`parse` pops a bullet's raw form and keeps the de-emphasised one).
_SUMMONED = re.compile(r"\b(?i:summoned|commanded):?\s+([A-Z][A-Za-z'-]*)"
                       r"(?:\s*\(\s*`?([^`()\s]+)`?\s*\))?")


def _id_key(s):
    """An agent id, normalised for comparison only.

    The same shape as `boardagents.clean_id` and deliberately a separate two
    lines: this module parses the store and imports nothing of the app, and the
    id it is comparing came out of a markdown line rather than off disk.
    """
    return re.sub(r"[^a-z0-9._-]+", "-", str(s or "").lower()).strip("-")


def summon_of(drawn):
    """`{"name", "id"}` if this bullet ANNOUNCES a summon, else None.

    `drawn` is a bullet's `text` — what the view shows, which is the form a
    parsed bullet keeps.
    """
    # `SUMMONED`/`COMMANDED` are the tag now [his, 2026-07-30]; `INFORMATION`
    # is still read because the store holds every note written before that.
    if tag_of(drawn) not in ("INFORMATION",) + BARE_TAGS:
        return None
    m = _SUMMONED.search(drawn)
    if not m:
        return None
    return {"name": m.group(1), "id": _id_key(m.group(2) or "")}


def is_result(bullet):
    """Does this message report an outcome — the thing that retires a summon
    note? Every unindented line is a message of its own, so any one of them
    reporting an outcome is enough."""
    for line in str(bullet or "").split("\n"):
        if not line.strip() or line[:1].isspace():
            continue
        if tag_of(text(re.sub(r"^\s*[-*+]\s+", "", line))) in RESULT_TAGS:
            return True
    return False


def find_summon(doc, agent_id="", name=""):
    """The ONE summon note announcing this agent, or None.

    None both when there is nothing to remove and when it cannot be said which
    of several notes to remove — the caller cannot tell those apart and must not
    need to, since it does the same thing either way.
    """
    aid = _id_key(agent_id)
    cands = [(t, summon_of(t.get("text", ""))) for t in doc.get("todo", [])]
    cands = [(t, s) for t, s in cands if s]
    if aid:
        hit = [t for t, s in cands if s["id"] == aid]
        if len(hit) == 1:
            return hit[0]
        if hit:
            return None            # two notes name this id: say nothing, act on nothing
    who = str(name or "").strip().lower()
    if who:
        hit = [t for t, s in cands if not s["id"] and s["name"].lower() == who]
        if len(hit) == 1:
            return hit[0]
    return None


def drop_summon(lines, doc, agent_id="", name=""):
    """Remove this agent's summon note from `lines`, if exactly one is found.

    `doc` must be a parse of `lines` as they are NOW — the caller adds its result
    bullet first and re-parses, because a bullet is a line plus whatever it
    wrapped onto and an index computed before the insert points at the wrong one.
    """
    t = find_summon(doc, agent_id, name)
    if t is None:
        return lines
    try:
        return remove_todo(lines, t)
    except BoardError:
        return lines               # it moved under us: leave it, never guess


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

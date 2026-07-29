# `board` — what needs him, what is moving, what landed

Vendored source of the decision board: `main.py`, `boardparse.py` and `qml/`.
Built and installed by `home/prog/board.nix`, which mirrors `reader.nix` exactly
(including the `air` system-python split) and runs the **live** source at
`/home/lam/nix/apps/board/main.py`, so `.py`/`.qml` edits need no rebuild. See
[`../AGENTS.md`](../AGENTS.md) for the rules shared by all eight apps, and
`~/nix/docs/DESIGN.md` before you draw anything.

```bash
board                       # ~/nix/docs/board.md
board /path/to/other.md     # any file with the same shape
```

## It is a GUI over ONE file, and that file is not this app's to redesign

**The store is `~/nix/docs/board.md`** — plain markdown, in the private `docs/`
repo, synced between `top` and `book` every five minutes, written by whichever
agent is orchestrating and edited by hand by him. board **parses it, draws it,
and writes his answers back into the same lines**. It does not own it, does not
migrate it, and must never become the only way to edit it.

Consequences that are rules, not preferences:

- **A write is a targeted LINE EDIT, never a re-serialisation.** `boardparse`
  keeps the raw line list from the read and replaces exactly the lines an edit
  names. A round-trip that reformats his prose, re-wraps a table or reorders a
  section is a bug — `tools/board-test.py` asserts *parse -> write with no
  change -> byte-identical*, and *tick one box -> exactly one line differs*.
- **An unrecognised line is carried through untouched and simply not drawn.** A
  future agent will add something this parser has no case for; that must cost a
  blank spot on screen, never a rewritten file.
- **Writes are atomic** — temp file in the target's own directory, fsync,
  `os.replace()`. Same rules as `apps/player/atomicsave.py` (that function is
  mutagen's, for audio containers, so the rules are reused rather than the code).
  This file is a git checkout a timer commits and pushes; half a `board.md`
  would sync to the other machine.

### The store's shape

```
## NEEDS YOU              decisions, `### <n>. <title>` each
    prose                 what the decision is about
    - [ ] option          ALTERNATIVES; wrapped continuations are indented
    > answer              his free text. Always beats the options
    *If unanswered:* ...  what happens if he never answers
## WAITING ON YOU TO DO   `- ` bullets. Actions, not decisions
## IN FLIGHT              a | table |: what / where / notes
## LANDED                 `### <date>` groups of | commit | what |, plus prose
```

Everything else — the `# Board` preamble, the `---` rules — is preserved and not
drawn. `boardparse.py`'s module docstring is the authoritative statement of both
the format and the round-trip contract; do not restate it elsewhere.

## The no-pressure requirement is a design constraint

He asked for this because the terminal chat log made him feel he had to answer
in the moment: *"i feel pressured to act quickly when really i dont need to"*.
So, as binding as the parse:

- **No counts, no badges, no ages, no deadlines, no sort-by-urgency.** A tally
  of open questions is a debt; there is not one anywhere in this app.
- **Nothing is drawn in the `warn`/`crit` ramp.** Those colours mean a machine
  fault on this desktop (§8.1, §9.3); a question is not one.
- **Every decision draws its own `if unanswered` line, always** — never behind a
  fold, never abbreviated. That sentence is what makes walking away safe, and it
  comes from the file rather than from this app's judgement.
- **Nothing leaves NEEDS YOU because board says so.** The store's own rule: an
  agent may add items and move things between IN FLIGHT and LANDED, but only he
  resolves a decision. board ticks boxes and writes his sentence; it never
  deletes an item.
- The empty state says `nothing needs you` / `nothing here expires - come back
  whenever`, in `Theme.dim` with the section rule above it unchanged, so a board
  with nothing on it reads as finished rather than as broken. It is the state he
  will see most often.

## Answering here now STARTS something

`home/srvs/board-watch.nix` watches this file and, when a decision becomes
newly answered, spawns one headless agent on that one decision. Two consequences
for anything in this app that writes:

- **A write must remain a targeted line edit**, above — the watcher fingerprints
  only the ticked option indices and the `>` text, so a re-serialisation that
  moved lines would still not fire it, but a rewritten option list would look
  like him changing his mind. The round-trip contract is now load-bearing twice.
- **The watcher never fires on its own writes or the agent's**, so this app does
  not have to coordinate with it, mark anything, or know it exists. Do not add a
  "worked by an agent" flag to the store to help it; the filter is deliberately
  content-based and authorship-blind (a `git pull` from book has no author it
  could ask about anyway).

## Never clobber him — three defences

The store is edited by agents and by a sync timer **while this window is open**.

1. **Watched and re-read in place.** `QFileSystemWatcher` on the file *and* its
   directory (an atomic save replaces the inode), coalesced by a 120 ms settle
   timer. The QML puts the scroll position back afterwards, so a reload is
   invisible (§6.1).
2. **A write refuses on a race.** `Board._commit` re-reads the file and compares
   its sha256 against the parse the edit was computed from. Different means
   somebody else moved the lines: it reloads, says
   `board.md changed on disk - reloaded, nothing written`, and writes nothing.
   Clicking again works. **This is asserted in the harness**; a stale line index
   landing his answer inside someone else's paragraph is the one failure this
   app must never have.
3. **Unsaved free text is never discarded.** A draft answer is persisted to
   `~/.local/state/board/state.json` on a 700 ms settle timer, survives a
   reload, a relaunch and a crash, and is drawn with
   `(a draft, not written to board.md yet)` under it. Escape leaves the editor
   and *keeps* the draft. Only committing (Enter) or clearing it removes it.

## What it draws, and why it looks like that

One page, three sections, in his stated order of interest — **what needs you,
what is moving, what happened** — inside **one** `KineticFlickable`. §9.2
forbids nested scroll regions, so every section sizes to its whole content and a
wheel notch means the same thing wherever the cursor is. `VScroll` is the bar and
the gutter is reserved from its own `barW`, never a literal.

- **Sections are told apart by a RULE and by spacing, never by size or weight**
  (§2.2 — the font ships Regular only, and every size here is one desktop-wide
  setting). `needs you` takes an accent rule; `in flight` and `landed` take the
  border hairline. The band is also the collapse control and says so: `[-]` /
  `[+]`, ASCII, because the font has no triangles (§2.3).
- **An ANSWERED decision carries the 2px accent gutter** §9.1 gives a current
  row. Nothing marks an unanswered one: an open question is this file's resting
  state, not an exception to flag.
- **Once an option is chosen the alternatives recede a rung** to `textDim`
  (§3.3's ladder). They have to: body text on this desktop *is* the accent
  (§3.1), so "chosen" cannot be said by making one label brighter — there is
  nothing brighter to go to.
- **Options are a RADIO.** They are alternatives; ticking one clears the others,
  and ticking the chosen one clears it, so a mind can be changed here rather
  than only in an editor (§10.2).
- **The WAITING TO DO bullets get no checkbox**, because the store gives them
  none to write to — §10's rule that a control which cannot work is not drawn.
- **LANDED is drawn entirely in the secondary tone**, commits in `dim`. It is
  the answer to "what did that session actually do to my machine", not something
  that wants attention.
- **The `where` column drops widest-first** as the window narrows (§9.1), at
  `width: 0`. Its width comes from a CHARACTER COUNT, not from `implicitWidth`:
  `width: Math.min(implicitWidth, …)` on an elided `Text` is self-referential and
  measured out at zero — the column silently vanished until it was changed.
- **Motion** is `qmlcommon/Motion.qml`'s and there is no duration literal in the
  tree. **Focus** is filer's idiom (§3.1.1): the root `Window` derives
  `fgAccent`/`fgText`/`fgDim` and hands them down; no leaf reads `Window.active`.

### Chrome: the hyprvtb titlebar (§12, §7.4)

`ny` / `if` / `ld` jump to a section **and** report position — the lit one is the
section the top of the viewport is in, like reader's outline marking. `md` opens
the store in `reader`, and says so if `reader` cannot be launched.

**There are deliberately no `<`/`>` cells and no `NavButtons`.** board has one
page and no journey to retrace; §11.1 says a program with no genuine history gets
nothing rather than an invented one. Add a row to DESIGN.md §11.1's table if that
ever changes.

## Recorded limit: the store quotes glyphs the font lacks

`board.md`'s open font decision literally lists the characters More Perfect DOS
VGA is missing — `À Á Â Ã È Ê Ë Ì Í Î Ï Ð Ò Ó Ô Õ Ø Ù Ú Û Ý Þ` — and the shared
map (`pylib/glyphs.py` + the panel's `Glyphs.qml` twin) has no entry for the
Latin-1 accented capitals, so **that one line clips** (§2.3). Extending the table
is a desktop-wide change across both roofs and belongs to that decision, not to
this app. `tools/board-test.py` carries the set as a named baseline and prints a
`NOTE`, so a genuine new regression is still a FAIL rather than being lost in it.

Everything else is glyph-mapped at INGEST, once per load, in `boardparse.text()`
— and emphasis stripping plus mapping happen on the **joined** paragraph, never
per line: a `**bold span**` that wraps in the source is two lines, and stripping
each separately leaves both markers on screen (it did).

## Verify

```bash
W=$(readlink -f "$(which board)"); sed '$d' "$W" > /tmp/brdenv.sh
( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \
    apps/board/tools/board-test.py --shots /tmp/board-shots )
```

`tools/board-test.py`, offscreen, three layers: **the round trip** (pure Python
— byte-identity, one-line edits, the radio, the `> ` marker preserved on a
clear, the atomic write), **the real store** (it parses, every decision has a
title, an `if unanswered` line and somewhere to write an answer, and the font
audit above), and **the window** — the real `qml/Main.qml` under
`QT_QPA_PLATFORM=offscreen`, including the stale-write refusal, an external edit
appearing without a relaunch, and `grabWindow()` PNGs with `--shots`: the real
store, the fixture populated, a decision answered, an EMPTY `NEEDS YOU`, a
420x600 window, and an unreadable store. It redirects `XDG_STATE_HOME` into a
scratch dir (a harness here **must**, or it rewrites his own app's state), works
on a COPY of the store for every write, and stubs the Titlebar, because the real
one registers buttons against the harness's pid in the live compositor.

The *appearance* is his check, as always.

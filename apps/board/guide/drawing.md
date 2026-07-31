# What it draws, and why it looks like that

*The four defences against clobbering him, the visual language, clearing a chore, the hyprvtb chrome, and the font's recorded limit.*

Part of goetia's guide — the map and the shared
rules are in [`../AGENTS.md`](../AGENTS.md); read that first.

---

## Never clobber him — four defences

The store is edited by agents and by a sync timer **while this window is open**.

1. **Watched and re-read in place.** `QFileSystemWatcher` on the file *and* its
   directory (an atomic save replaces the inode), coalesced by a 120 ms settle
   timer. The QML puts the scroll position back afterwards, so a reload is
   invisible (§6.1).
1b. **A reload does not rebuild the world.** **Every Repeater on this page takes
   a list of KEYS as its model, never the rows** — a decision's `key`, a chore's
   `line`, an agent's `id` — and the delegate reads its own row back out by
   `index`, the two lists being parallel. A Repeater over a JS array of rows has
   no diff at all: one character changing in one row destroyed and rebuilt every
   delegate on the page, which took the focus and the caret out of the editor he
   was typing in. An equal key list is not a change, so a row whose text moved
   now updates *through* the delegate's binding and the delegate is never
   touched. **Keep `modelData` meaning the row** (a `readonly property var
   modelData: <rows>[index]` shadowing the injected key) — the harness probes it,
   and every reader in `Main.qml` reads it that way.
   A row genuinely appearing or leaving still rebuilds that one list, and there
   the second half applies: `win.caretIn`/`caretPos` hold WHICH editor has his
   caret and WHERE, every editor on the page reports into it (`InputBox`'s and
   `Decision`'s `caretHeld`/`caretLeft` + `openCaret`), and a rebuilt row comes
   back open with the caret where he left it. It is reported only while an editor
   actually has focus and cleared only when *he* leaves one — **never on
   destruction**, which would erase the very thing it exists to restore, and
   never by a row appearing under a box that already holds the caret.
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

One page, three sections — **what needs you, who is running it, what
happened** — inside **one** `KineticFlickable`. There were four until
2026-07-30: IN FLIGHT sat at the BOTTOM, below LANDED, at his request
(*"for now"*, 2026-07-29), and the section is gone. **The order here is a
DISPLAY order and nothing else** — `board.md`'s own section order and
`boardparse.SECTIONS` are untouched, and a reorder has to carry three things
with it or the titlebar lies: the `section` position readout (which asks
bottom-up and takes the first match), the `tbButtons` cell order, and
`jump()`. §9.2
forbids nested scroll regions, so every section sizes to its whole content and a
wheel notch means the same thing wherever the cursor is. `VScroll` is the bar and
the gutter is reserved from its own `barW`, never a literal.

- **Sections are told apart by a RULE and by spacing, never by size or weight**
  (§2.2 — the font ships Regular only, and every size here is one desktop-wide
  setting). `needs you` takes an accent rule; `in flight`, `agents` and `landed`
  take the border hairline. The band is also the collapse control and says so: `[-]` /
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
  **They can be REMOVED, though** — see below.
- **LANDED is drawn entirely in the secondary tone**, commits in `dim`. It is
  the answer to "what did that session actually do to my machine", not something
  that wants attention. The **time sits at the trailing edge** in `dim` (§9.1 —
  metadata clusters with its kin at the end of the row), so the reading order
  stays hash, what, when and the time never competes with the sentence. Its
  width is a character count like the commit's, and it is `0` for a row that has
  no time, so the older rows give the space back to the `what`.
- **The `where` column drops widest-first** as the window narrows (§9.1), at
  `width: 0`. Its width comes from a CHARACTER COUNT, not from `implicitWidth`:
  `width: Math.min(implicitWidth, …)` on an elided `Text` is self-referential and
  measured out at zero — the column silently vanished until it was changed.
- **Motion** is `qmlcommon/Motion.qml`'s and there is no duration literal in the
  tree. **Focus** is filer's idiom (§3.1.1): the root `Window` derives
  `fgAccent`/`fgText`/`fgDim` and hands them down; no leaf reads `Window.active`.

### Clearing a chore: the one thing in this app that DELETES his prose

*"i should be able to clear the 'to do, when you feel like it' stuff if i wish.
currently i cannot remove it via board program"*. Agents add bullets to WAITING
ON YOU TO DO (`boardmove.note`, the watcher's failure paths) and until now
nothing ever took one away, so the section only ever grew.

`Board.removeTodo(line)` / `Board.undoRemove()`, reached two ways — a **double
click** on the row and the row's right-click menu. Every point of it is a rule:

- **A DOUBLE CLICK removes it**, because that is how he asked: *"i should be
  able to just double click on stuff in the to do when you feel like it section
  to remove them"*. It did nothing for a day and the reason is worth keeping:
  the row's `MouseArea` was `acceptedButtons: Qt.RightButton`, so the left
  button never reached it at all and the double click landed on nothing. **A
  single left click stays inert** — the store gives these bullets no checkbox,
  so there is nothing for one click to do, and a row that acted on one pass of
  the pointer would make the removal an accident waiting to happen.
- Its regression lives in `tools/board-test.py` and must use **`QTest`**, not a
  hand-built `QMouseEvent` sequence: Qt Quick derives a double click from its
  own press bookkeeping, so a `MouseButtonDblClick` posted straight at the
  window is silently dropped and the test passes against the broken code.
  Measured — the hand-built sequence reached `onClicked` and never
  `onDoubleClicked`.

- **ONE verb, `remove`. There is no "done".** A chore he has finished and a
  chore he no longer wants both end the same way — the line goes — and the
  record of *why* it existed is already in LANDED, where an agent writes what it
  did. A second "done" state would make this list a checklist with a completion
  to account for, which is exactly the debt the no-pressure requirement refuses.
- **A confirm was NOT added, an UNDO was.** The deliberateness §10.3 asks for is
  in the second click (or in the right-click plus the entry — the reading
  `ProcMenu`'s `force quit` settled), and unlike a signal to a process a deleted
  line can be put back
  byte-for-byte. `put back "..."` appears in **every** menu, because he may have
  removed the only row there was to right-click, and is **absent rather than
  greyed** when there is nothing behind it (§10). One level, this session only:
  older removals are in `docs/`'s git history, which a timer commits every five
  minutes, and the risk this guards is the misclick he notices immediately.
- **`remove this from the list` is LAST, behind a separator** (§7.2), so the
  pointer never lands on it.
- **`reply` is FIRST**, and it is his: *"the top item on the right click menu
  for to do items should be `reply` that lets me reply directly to it instead of
  typing in the top box like i am doing now"*. It opens an `InputBox` **on that
  row**, and it is **not a second write path** — `boardagents.send()` with
  nothing named, exactly what the box at the top does, so the conservation
  property still holds. The one thing it adds is the QUOTE: the chore's own text
  travels with his sentence, because "yes, do that one" means nothing to the
  orchestrator that reads it half an hour later. §7.2's ordering still holds —
  the thing he does most is first, read-only next, the undo, then the one
  destructive entry behind its separator.
- **His sentence is FIRST in the body, the quote comes after it**
  (`<his reply>  (about the `to do` bullet "...")`), and that order is the whole
  point: *"the resulting agent created should indicate the reply from the user
  rather than the original message"*. Everything downstream reads the HEAD of
  that one string — the `waiting for the next agent` line this window draws,
  `board-watch`'s card title for the orchestrator it spawns
  (`msgs[0]["text"][:70]`), every `boardctl` listing — so a body that opened with
  the quote made all of them announce the chore and bury the answer. Reordering
  the string was the whole fix; none of those readers changed.
- **A reply REMOVES the chore** — *"when the user replies to something in the to
  do section it should then remove the entry from the to do section"* — and only
  once `Agents.send()` has returned non-empty, so a reply he made and a chore
  still sitting there cannot both be true. It goes through `Board.removeTodo`,
  the same one path the menu entry and the double click take, so it inherits the
  one-level undo: a reply aimed at the wrong row costs a right-click, not his
  prose. The bullet is **re-resolved against the doc as it is now**
  (`todoLineOf`, by text, preferring its own line) rather than trusting the index
  the row was drawn from — three programs write this file and it syncs every five
  minutes, and a stale line would take somebody else's bullet. A chore that has
  gone in the meantime removes nothing and the reply still goes.
- **A bullet is removed as a UNIT.** `boardparse.remove_todo` deletes
  `line`..`endLine` — a chore routinely wraps onto indented continuation lines,
  and `remove_row` above it is for a *table* row, which is one line by
  definition. `endLine` is recorded by the parser for every paragraph.
- **Nothing is tidied.** The blank lines around it are left exactly as they
  were, even when the section empties out completely: squashing them would be a
  write touching lines it was not asked about, and this file syncs to book.
- It goes through the app's one write path (`Board._commit`: re-read, digest
  compare, refuse on a race), and `boardctl`/`board-watch` still reach the same
  edits through `boardparse.edit()`. There is no second writer.

### Chrome: the hyprvtb titlebar (§12, §7.4)

`ny` / `if` / `ag` / `ld` jump to a section **and** report position — the lit one is the
section the top of the viewport is in, like reader's outline marking. `md` opens
the store in `reader`, and says so if `reader` cannot be launched. `lg`, in its
own section under it, opens every card's log drawer at once.

**`lg` is a DEFAULT, not a bulk edit of `outputOpen`, and that is the whole
design.** Cards are rebuilt on every 2.5s poll, so a switch that merely wrote
`true` into the ids present when he pressed it would leave the next agent to
appear shut — which is not "all cards". `Main.qml`'s `allLogs` is the default
`isOutputOpen` falls back to; the map holds EXCEPTIONS to it, so a card he shuts
by hand while the switch is on stays shut and the rest stay open. Flipping the
switch clears the exceptions, so both directions are visible on every card.

**It is the one piece of card state that PERSISTS** (§14): a view preference he
sets by using the app and would notice reverting, and it names no process, so it
still means the same thing tomorrow — unlike the exception map and `todoFolded`,
which are session-only because an id names a process that is gone. It lives in
`Settings` (`~/.local/state/board/state.json`, key `allLogs`) beside `collapsed`
and `drafts`; there is no second store. §12.1 does the reporting: the lit cell
IS the state, so there is no status line and no second glyph for "off".

**There are deliberately no `<`/`>` cells and no `NavButtons`.** board has one
page and no journey to retrace; §11.1 says a program with no genuine history gets
nothing rather than an invented one. Add a row to DESIGN.md §11.1's table if that
ever changes.

**The INNER bar carries no name — and the stacked title is not the inner bar.**
[his, 2026-07-29, twice within five minutes] *"remove the 'goetia' text at the
bottom of the inner titlebar"*, then *"really for now there should be no title
text in the left side inner bar of goetia"*. The footer is the status and nothing
else, which answers the first. The second was answered with
`Titlebar.setTitleText(false)` → `TITLETEXT 0` on the vtb socket, and **that was
the wrong lever**: the stacked title is drawn in the OUTER column, while the
inner (left) bar only ever holds the app buttons and the footer. So the flag
erased the title from the RIGHT OUTER bar, which he had not asked about, and the
inner bar was already nameless. Dropped 2026-07-30 (Kimaris' finding); goetia
reads `"titleText":true` in `~/.local/state/hyprvtb/ipc-dump.json`
(`hyprctl eval "hl.plugin.hyprvtb.ipc_dump()"` writes it). The
`Titlebar.setTitleText` wrapper in `main.py` and the plugin verb both stay —
they are correct, and an app with a real document identity would use them.
**Never blank `Window.title` instead**: Qt substitutes the application name for
an empty title, so the bar would read `board` — the one word the rename exists to
keep off screen — and the taskbar and alt-tab would lose the window's name too.

**...and the footer only says what nothing else on screen can.** [his,
2026-07-30] *"when i change the number of ministers in goetia itll flash text
indicating that on the inner bar"* — the third report of that bar flashing, and
the first with a repro. It was not a render fault at all (the plugin's IPC-serial
stamp was already fixed in hyprvtb 2.97, and `tools/vtb-flash-test.sh` measured
the cold footer path clean, 20/20 shots): it was **goetia's own confirmation
message**. `footerStr` IS `status`, so that slot is empty except for the four
seconds a report sits in it — text appearing out of nothing and going again is
exactly what a flash looks like, whatever wrote it.

**...and then: NOTHING, EVER.** [his, 2026-07-30, escalating after the pass
above removed only the confirmation] *"it was not only that. why are you unable
to simply stop ANY text from appearing in the inner titlebar of goetia?"* The
rule below — footer carries a failure or an outcome nothing else shows — was
still a judgement about WHICH strings, so it still let the failure reports and
the phase lines through, and every new call site got to make the call again.
It is not a judgement any more:

> **goetia's inner titlebar carries no text under any condition.** The only
> things in it are the button cells (`ny` `if` `ag` `ld` `md` `lg` — 1-2 char
> glyphs, the navigation chrome he uses; their tooltips pop out BESIDE the bar,
> not in it). There is no other text and no way to add one.

**It is closed structurally, at the client, not at the call sites.**
`main.py`'s `_MuteFooterVtbClient` is a `VtbClient` subclass whose `set_footer`
does not reach the socket, and `Titlebar` constructs that instead of a plain
`VtbClient` — so the `FOOTER` verb does not exist for this app. A future report,
a new phase line, or a direct `self._client.set_footer` cannot reintroduce the
flash without deleting that class. `_footer` therefore stays `""` for the
process's whole life, which also kills the reconnect replay
(`_flag_lines_locked()` emits `FOOTER` only for a non-empty one), the path that
survived a plugin hot-swap. **`pylib/vtbclient.py` is untouched** — eight other
apps draw a real footer through it and are behaviourally identical.

**A report is moved, never dropped** (§10). `Titlebar.setFooter` and the
overridden `set_footer` both call `main.py`'s `_record_status`, which stamps the
line into **`~/.cache/goetia-status.log`** and prints it to stderr. `win.status`
in `Main.qml` still holds it too, unchanged and still cleared on the four-second
timer, so an in-window status surface can bind to it whenever goetia grows one —
the wiring above it did not have to change at all, which is why this fix is one
class and two call lines.

The older rule below is what the app's own `status` channel is still worded to,
and it stays worth reading: **the footer carries a failure, or an outcome
nothing else on screen shows** — where an order went, what Ctrl+Z took back, why
a usage refresh he asked for could not happen. It now decides what is worth a
LOG line rather than what reaches the bar. Two kinds of line were dropped for
failing it:

- **A successful pick in any of the four choosers says nothing.** The closed box
  relabels itself from the store and the tick moves, so the change is on screen;
  the WHEN (`the next tick honours it`) is the `PickBox`'s own `hint`,
  permanently and *before* he picks, so the four-second version bought no
  honesty. A failed pick still reports — that outcome has nowhere else to go,
  and §10 is about those.
- **A reload says nothing.** `board.md changed on disk - reloaded` fired on every
  agent write and every five-minute sync, i.e. §6.1's own rule (the maintenance
  mechanism must not be visible) breaking itself in the one slot he cannot look
  away from. The rows changing is the report.

Harness: **`tools/vtb-cap-probe.py`** — the PRODUCER half, and the one to extend
for anything else this app pushes down that socket. It stands up a fake
`hyprvtb-buttons.sock` in a scratch `$XDG_RUNTIME_DIR`, runs the real app
offscreen against a scratch board/state tree, and asserts two things. First, a
successful cap change publishes **nothing** — no `FOOTER`, no re-`REGISTER`, no
flag line (the real dropdown entry, driven through `QQmlExpression`). Second,
**the invariant**: it then drives a real `Board.status` failure, a direct write
to `win.status` (the funnel all ~20 QML call sites end at) and a reload of the
store underneath the window, and asserts that no `FOOTER` line carrying text was
sent by ANY of them — while checking each report did reach
`~/.cache/goetia-status.log`, so a pass cannot mean "swallowed". Verified
against a negative control: with the mute removed, both the failure and the
direct write put `FOOTER <text>` on the wire and the probe fails on each. It
needs no plugin, no compositor and no window; `tools/vtb-flash-test.sh` and
`tools/vtb-titletext-test.sh` remain the pixel side.

### A usage meter is a BUTTON, and its tooltip is a countdown

`UsageMeter.qml` + `boardusage.readings()` + `Usage` in `main.py`.

- **Clicking a meter refreshes that reading, now** — [his, 2026-07-30]. The
  target is the whole row, label to percentage (a 7px bar is not one, §5.3), and
  the click runs `Usage.refreshNow()`: the SAME fetch the 60s/300s clocks and the
  agent-lifecycle kick run, with the gap set to zero. One fetch path, one place a
  failure is worded.
- **It reports, because it can fail** (§10). `Usage.busy` lights the row's label
  for as long as the round trip lasts and refuses a second click; `Usage.refreshed`
  carries the outcome to the window's footer, in his words — `off` (this host has
  `BOARD_USAGE_OFFLINE=1`), `offline`, an expired token — never a reason word and
  never silence. **Only a hand-driven refresh emits it**: the clocks must not put
  a report in the footer he did not ask for (§10.4). Nothing blanks while it
  works — the last true reading stays on screen with its age.
- **The tooltip is ONE line and it is a countdown**: [his, 2026-07-30] *"the
  tooltip should just say `resets in ____`"* — `resets in 2h 14m`, `resets in
  6d 17h`. It carried `detail` above that line until then; the age is already the
  row's second line and the window's name is two characters from the pointer, so
  the chip spends its width on the one thing the row does not say.
- **The wording is `boardusage.py`'s**, like the figures and the `5h`/`7d` labels
  (§2). The QML picks which field to draw and never composes prose. `_left()` is
  the span (two units, coarsest first, §9.3); `_clock()` still exists for
  `detail`, which is no longer drawn anywhere.
- **`reset` is never empty**: a payload with no `resets_at`, one whose reset has
  already gone by, or no reading at all each say so in the same `resets in ? - …`
  shape rather than showing an empty chip (§10).
- The tooltip is `qml/ToolTipArea.qml`, a second copy of painter's (§8, §19.1) —
  `qmlcommon/` cannot hold it, since the chip is `PixelText` and that type
  resolves per app directory. **This copy snaps its retraction and painter's does
  not**: `Behavior { enabled: area.open }` is a second binding over the same
  property with no ordering guarantee, and painter's animates the close anyway
  (measured offscreen, 240 -> 143 -> 42 -> 0 over ~200ms). Ours sets the gate
  imperatively first. Retune the dwell in both.

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

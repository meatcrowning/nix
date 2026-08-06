# `apps/` — the vendored desktop apps

Nine standalone Qt/QML apps that ship with this config, plus the shared Python
helpers they all import. Each has its own `AGENTS.md` with the detail:

**Read `~/nix/docs/DESIGN.md` before you draw anything in here.** These apps are not
nine programs that happen to share a repo — they are one desktop, alongside the
panel and the compositor plugin, and the user's standing requirement is that a
new app or a new feature *looks like the rest without him having to say so*.
Type, palette, spacing, corners, motion timing, titlebar button glyphs, menus,
tooltips, list rows, drop feedback and the honesty-of-controls rule all live in
that one file. It also records where these apps have already drifted apart from
each other. This guide owns the *mechanics*; that one owns the *look*.

| dir | what it is | packaged by |
| --- | --- | --- |
| [`filer/`](filer/AGENTS.md) | Qt/QML file browser | `home/prog/filer.nix` |
| [`viewer/`](viewer/AGENTS.md) | image viewer (‹/› through a folder) | `home/prog/viewer.nix` |
| [`player/`](player/AGENTS.md) | tag-driven music player (mpv + MPRIS) | `home/prog/player.nix` |
| [`painter/`](painter/AGENTS.md) | text-to-image front end for headless ComfyUI | `home/prog/painter.nix` |
| [`surfer/`](surfer/AGENTS.md) | QtWebEngine browser | `home/prog/surfer.nix` |
| [`askpass/`](askpass/AGENTS.md) | the `sudo -A` password dialog | `home/prog/askpass.nix` |
| [`reader/`](reader/AGENTS.md) | markdown reader (browse + read `.md`) | `home/prog/reader.nix` |
| [`board/`](board/AGENTS.md) | **goetia** — decision board over `docs/board.<hostname>.md` | `home/prog/board.nix` |
| [`editor/`](editor/AGENTS.md) | text editor with Kate's core editing | `home/prog/editor.nix` |
| `pylib/` | shared helpers — see below | (imported, not packaged) |
| `qmlcommon/` | shared QML components — see below | (imported, not packaged) |

## They are the system defaults

Five of them are what the rest of the desktop opens things with: **filer** for
`inode/directory`, **viewer** for every image and video type in its
`IMAGE_EXTS`/`VIDEO_EXTS`, **reader** for `text/markdown`, **surfer** for
`text/html`, `application/xhtml+xml` and `x-scheme-handler/
http(s)`/`about` (plus Plasma's separate `kdeglobals` `BrowserApplication` key
and `$BROWSER`), and **player** for nine of the audio types its `AUDIO_EXTS`
covers.

**editor is ELIGIBLE for the text types but DEFAULT for none of them** (yet).
It declares `text/plain` and the source types it can honour, with `%F` because it
genuinely opens several files as several tabs — but it is deliberately absent
from `mime-defaults.nix`: `text/markdown` already belongs to reader and
`text/html` to surfer, and quietly taking either would change what
double-clicking does without him asking. One line in that file (or one
`xdg-mime default`) is the whole change if he wants it.

**painter and goetia are the deliberate none.** painter has no open-a-file path
at all and goetia is a GUI over one fixed file, so neither declares a
`MimeType=` and neither appears in `mime-defaults.nix`. An app with no honest
file type gets no association.

**player covers ALL of its `AUDIO_EXTS`** since 2026-07-29 — every
shared-mime-info type that globs one of its fourteen extensions, aliases and
ogg subtypes included. It was held to nine of them for a while because its
`Exec=` carried `%F` and `main.py` threw the argument away; **an app may only
claim a type it can honour**, and that rule is the whole reason the list was
short. It is honoured now (`player/AGENTS.md` → "Opening a file by path"), so
the list is full. See `mime-defaults.nix` and
`docs/agents/mime-defaults-audit.md`.

Each app's `.desktop` entry — with its `MimeType=` and its `Exec=` field code —
is written by its own `home/prog/<app>.nix`, because only that file knows the
store path. Which of the eligible apps is the **default** is one central list in
`home/prog/mime-defaults.nix`. Keep viewer's `MimeType=` and its
`IMAGE_EXTS`/`VIDEO_EXTS` in sync with that list; registering a type viewer
can't decode makes it the thing that fails to open it.

Being a **file picker** is a different mechanism entirely — the
`org.freedesktop.impl.portal.FileChooser` D-Bus backend, not a MIME
association. **filer implements it** (`filer/portal.py` + `filer/pick.py`,
packaged by `home/prog/filer-portal.nix`), and it **ships dormant**: turn it on
with `filer-portal-switch on`, off with `filer-portal-switch off`. See
[`filer/AGENTS.md`](filer/AGENTS.md).

## Why this tree is OUTSIDE `home/` and `sys/`

Non-negotiable: `home/default.nix` and `sys/default.nix` use `umport`, which
recursively imports **every** `.nix` file beneath them. An app parked in there
would have its own `flake.nix` eval'd as a NixOS module. `apps/` is inert
vendored source — nothing in the NixOS/home evaluation imports it, it simply
travels with the repo so a `git pull` carries the apps to every machine.

(This is why they sat at the repo *root* historically; the constraint was only
ever "outside `home/`/`sys/`", so `apps/` satisfies it just as well.)

## The live-source pattern — all nine work this way

`home/prog/<app>.nix` builds a wrapper that runs the **live** source at the
absolute path `/home/lam/nix/apps/<app>/main.py` — valid on both `top` and
`air`, which is why it is absolute and not `${./.}`.

- **`.py`/`.qml` edits need NO rebuild.**
- **There is also NO hot-reload — relaunch the app** to pick a change up.
  (Only the Quickshell panel hot-reloads; these do not.)
- A rebuild is needed only when a change adds a **dependency** or edits the
  `.nix` packaging.
- Consequence for agents: after editing app source, do not rebuild reflexively,
  and do not relaunch the user's running app for them — say what to relaunch.

Each app also carries an **`air` split** in its `.nix`: on book (Fedora Asahi)
the wrapper `exec`s the system `/usr/bin/python3` rather than a nix-built
interpreter.

**So a new dependency has two homes, and the rule is both** (root `AGENTS.md`
→ Conventions, "Both machines by default"). Adding a package to the `pyEnv`
does nothing on book — that branch never sees it, and the app fails there at
`import` time, on his laptop, with nothing failing at build. Either the module
is in Fedora's `python3-*` set as well, or the app degrades gracefully without
it; if neither, that is a machine-specific change and he needs telling.

## `pylib/` — shared, resolved relatively

Every app does `sys.path.insert(0, str(HERE.parent / "pylib"))`, so the whole
`apps/` tree must move together or none of it does. Tools one level deeper use
`parent.parent.parent`.

- **`handoff.py`** — hand a request to an app that is ALREADY running, so the
  common case starts no process. Measured on book, opening an image from filer
  cost ~0.5s of which the file was 0.04s; the rest was python + PySide6 + the
  QML engine + a GL context. filer now asks a live `viewer` over an AF_UNIX
  socket in `$XDG_RUNTIME_DIR` and only launches one when nobody takes it —
  **0.7ms instead of ~500ms**.
  - **The client half imports no Qt, on purpose.** `import PySide6` is 0.10s of
    the 0.5s, so a caller must be able to try the handoff before paying it;
    `viewer/main.py` runs it ABOVE its own imports for exactly that reason.
    Keep it stdlib-only.
  - **A refusal is normal and must stay cheap.** The server answers "no"
    whenever it cannot do the job *visibly* — viewer's rule is
    `QWindow.isExposed()`, false on another workspace, rolled up or minimised —
    and the caller then launches as it always did. A false "taken" is a click
    that does nothing, which is the one outcome worse than being slow.
  - `Listener` listens FIRST and only calls `removeServer()` when nothing is
    actually accepting on the path. An unconditional `removeServer()` (the
    obvious way to clear a stale socket) makes every later instance steal the
    name from the running one; `tools/handoff-test.py` stands up two Listeners
    to catch precisely that.
  - Harnesses: `apps/pylib/tools/handoff-test.py` (the transport, both halves)
    and `apps/viewer/tools/handoff-test.py` (what viewer does with a request —
    the exposure refusal, `--order`, caller-relative paths).

- **`vtbclient.py`** — the hyprvtb titlebar-button socket bridge. Every app's
  chrome (transport buttons, close/zoom, view switchers) is drawn by the
  compositor plugin, not by QML, and goes through here.
  **The wire protocol is the module docstring at the top of
  `apps/pylib/vtbclient.py`** — every verb in both directions, the field order,
  the `-` spacer token, and the percent-encoding. It is the authoritative
  statement; nothing else in this tree should restate it, and a per-app guide
  that needs one corner of it should quote the docstring rather than paraphrase
  the rest. (Server side: `home/prog/hyprvtb/vtbIpc.hpp`.)
  **A REGISTER carries its own non-default flags in the SAME write**, and every
  reconnect replays that one write. The plugin holds no state for an unknown pid
  and `dropClient` erases the entry, so a registration the compositor can
  observe on its own is a registration observed at the plugin's DEFAULTS — which
  is what made goetia's bar flash its window title. A new flag must therefore be
  added to `_flag_lines_locked()` as well as its setter, and only when it is off
  the default: an app that wants the defaults must keep sending nothing extra.
  Harness: `apps/pylib/tools/vtb-register-test.py` (offscreen, mocks the
  plugin's poll/drain loop, needs no plugin loaded).
- **`trackmatch.py`** — the one artist/title normaliser. Any new "are these two
  tag strings the same song?" code must use it rather than grow a second copy;
  see `player/AGENTS.md`.
- **`deskstyle.py`** — **THE channel for every desktop-wide appearance setting
  that has to reach the apps. Add a key here; never build a second pipe.**
  Today: `fontFamily` / `fontSize`, the two motion settings `reduceMotion` /
  `animSpeed` (see Motion, below), and `scrollbarStyle` (see `VScroll.qml`).
  That last one has no panel consumer at all — the panel draws no scrollbar —
  and lives here anyway, because one channel with a key the writer ignores
  beats two channels. Read live
  from the panel's own `~/.config/quickshell/settings.json` (the file
  `SettingsStore` persists). Install it as the `DeskStyle` context property
  BEFORE creating the app's `Theme.qml`, exactly like `WalPalette`, and keep a
  Python reference — every app's `Theme.font`/`fontSize` binds to it, so an app
  that forgets loads its theme with an empty font. Any offscreen harness that
  builds a `Theme.qml` needs it too. It exists because those two used to be
  hardcoded `15` per app, so the Settings font-size slider moved the panel and
  the titlebars and left all six apps behind (docs/DESIGN.md §2.7). Point
  `$DESK_SETTINGS` at another JSON file to render at a non-default size without
  touching the user's live settings — that is how the size is verified
  offscreen.
- **`glyphs.py`** — `px()`, the apps' half of docs/DESIGN.md §2.3: the characters
  More Perfect DOS VGA lacks, mapped onto ASCII, so text this desktop did not
  author cannot clip the row it is drawn in. It is the twin of the panel's
  `quickshell-files/Glyphs.qml` — same table, two roofs, **retune both** — and
  it is deliberately Python rather than QML, because §2.3 says to map at the
  INGEST point (where a file is parsed) and not once per delegate per scroll.
  `reader` is its first caller; the other six still draw filenames, tags and
  page titles unmapped (§19.1). `is_mappable()` records what is left alone on
  purpose (CJK, Greek, the maths operators), so a harness can tell a known
  limit from a regression.
- **`spellcheck.py`** — **THE spell checker for every text-entry surface here,
  and the only one.** It talks to the **`hunspell` binary in pipe mode**
  (`hunspell -a`, the ispell protocol) rather than to a Python binding: that
  buys the real affix engine and hunspell's own suggestion ranking with nothing
  to package on Fedora, where `python3-enchant` is not a given. Reading
  `en_US.dic` in Python was considered and rejected — the word list is stems
  plus affix flags, so membership alone accepts `colour` and rejects `walked`.
  The dictionary is the same `pkgs.hunspellDicts.en_US` surfer's `.bdic` is
  compiled from, so the browser and the apps never disagree about a word.
  Install it as the `Spell` context property (like `DeskStyle`) and keep a
  Python reference.
    - **Wiring is two `--set-default`s in the app's `.nix`** —
      `SPELL_HUNSPELL`, `SPELL_DICPATH` — and **book's branch gets neither**:
      there the checker resolves `hunspell` from `$PATH` and
      `/usr/share/hunspell`, i.e. it works if `hunspell` + `hunspell-en-US` are
      dnf-installed and marks NOTHING if they are not. Nothing about either
      package is x86-only.
    - **A missing dictionary must be indistinguishable from no feature**
      (docs/DESIGN.md §10): `available` goes false and every query answers
      "fine", so no input half-underlines itself. That degraded path is the
      first thing `apps/pylib/tools/spellcheck-test.py` checks.
    - The tokeniser deliberately refuses four shapes — under three letters,
      ALL CAPS, an inner capital, and anything touching `/._@:#$` or a digit —
      because without them a code comment or a pasted log line lights up
      entirely. Change those and re-run the harness; they are the difference
      between a marker he keeps and one he asks to have removed.
    - Personal words live in `$XDG_STATE_HOME/spellcheck/personal.dic`, one
      per line, **shared by every app**: "add to dictionary" in editor is added
      in painter too.
- **`kitty-vtb.py`** — kitty's vtb integration, run from the live repo, stdlib
  only.
- **`clipfile.py`** — **THE way to put a FILE on the clipboard here.** Run as a
  program (`python3 clipfile.py FILE…`), not imported: it forks and stays alive
  as the selection's owner, because a Wayland selection dies with the process
  that offered it. Exit 0 means the clipboard is ours; the holder lets go when
  something else takes it.
    - `wl-copy --type text/uri-list` is what painter used, and it is one MIME
      type short: wl-copy offers exactly one (plus the text/plain aliases it
      guesses for a `text/*` type), while GTK — and Chromium/Electron behind
      it, so a browser or a chat client — reads `x-special/gnome-copied-files`
      to decide a paste is a FILE. Missing it, "copy muted" pasted the path as
      TEXT. wl-copy also appends a newline to argv content unless given `-n`,
      so the uri-list was LF- rather than CRLF-terminated (RFC 2483).
    - `QClipboard` cannot do this job at all: `wl_data_device.set_selection`
      wants an input-event serial, which only a focused window has, and the
      selection would die with the app anyway. It also SIGSEGVs PySide on exit
      (Qt's global-static clipboard frees a Python-built `QMimeData` after the
      interpreter is gone — painter's harness exited 139 with every check
      passing).
    - It speaks the Wayland wire protocol directly, stdlib only, over
      `zwlr_data_control_manager_v1` / `ext_data_control_manager_v1` — the
      protocol wl-clipboard itself uses, and the one that needs neither a
      surface nor focus.
    - Harness: `apps/pylib/tools/clipfile-test.sh`. It copies and pastes for
      real, inside a **headless sway** with its own `XDG_RUNTIME_DIR`, so it
      can neither take his clipboard nor put anything on screen — his socket is
      not in that directory. Use that shape for anything else that needs a
      compositor of its own; a nested Hyprland is a window in the live session.

## `qmlcommon/` — shared QML, resolved relatively

The QML counterpart of `pylib/`: components every app's `.qml` can reach with a
plain relative **directory** import, from `apps/<app>/qml/`:

```qml
import "../../qmlcommon"
```

No wrapper change is needed for this — `home/prog/<app>.nix` sets no QML import
path and does not have to. `Theme` resolves inside these components because
every app installs it as a root **context property** in `main.py`, and context
properties are visible to every file-based component whatever directory it
lives in.

### Motion: one duration, one curve, and it is the compositor's

**Never write a duration literal into an animation here.** `Motion.qml` from
`qmlcommon/` is the apps' half of `docs/DESIGN.md` §6.2 — the rule that everything on
this desktop which slides, grows or glides between two resting positions moves
at the same speed as a window rolling out next to it, because the user stated it
as a design-language rule and not a per-widget choice.

```qml
import "../../qmlcommon"
Motion { id: motion }
Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs)
                                      easing.type: motion.slideEasing } }
```

It is **not** a fourth hand-copy of 260. hyprvtb owns the number as
`plugin:hyprvtb:slide_duration_ms` and publishes it to a generated
`~/.local/state/hyprvtb/DeskMotion.qml`, which `Motion` reads with a `Loader` —
plain Qt QML has no file reader at all, and `XMLHttpRequest` refuses a `file://`
URL unless `QML_XHR_ALLOW_FILE_READ` is exported into the app, which is a
blanket local-file-read permission and one of these apps is a **web browser**.
Both were measured offscreen; the `Loader` is the one that degrades correctly,
reporting `Loader.Error` for a missing file. The 260 in that file is the
fallback for a machine with no plugin, and must stay equal to the key's default
in `hyprvtb/main.cpp`.

It resolves once, at construction — consistent with these apps having no hot
reload of any kind, so "relaunch to pick it up" is already the rule here.

`motion.ms()` also applies the panel's `reduceMotion` / `animSpeed`, which
`pylib/deskstyle.py` publishes on the `DeskStyle` context property beside
`fontFamily`/`fontSize` — so an app that forgets to install `DeskStyle` gets
1.0/false through `Motion`'s `typeof` guard rather than a `ReferenceError`, and
an offscreen harness that builds a component without it still animates sanely.
**`animSpeed` is validated the way the PANEL validates it, not the way the
slider is bounded**: any finite value > 0, falling back to 1.0. Clamping it to
the slider's 0.5-2.0 here would mean a hand-edited `settings.json` scaled the
panel and the apps by different amounts.

A duration that is deliberately *not* the slide keeps its number and gets a
comment saying why — hover and crossfades stay at 120/140ms, take the house
curve, and still go through `ms()`. See §6.2.1's non-participants table. (The
scrollbar used to be on that list; it has no animation at all now — see
`VScroll.qml` below.)

### Scrolling: every scrollable view is kinetic BY CONSTRUCTION

**Never write a bare `ListView`, `GridView`, `Flickable` or `ScrollView` in
`apps/`.** Use `KineticListView`, `KineticGridView` or `KineticFlickable` from
`qmlcommon/`. They are the same types with Qt's own flicking off
(`interactive: false`, `boundsBehavior: StopAtBounds`) and one `WheelScroll`
overlay wired to themselves; everything else — model, delegate,
`positionViewAtIndex`, `ScrollBar.vertical` — behaves exactly as before.

Because momentum on this desktop is **compositor-side**: hyprvtb synthesizes
macOS-style decay at the seat, so a coast reaches a client as an ordinary
high-resolution wheel/axis stream (`docs/kinetic-scroll.md`,
`home/prog/AGENTS.md`). A view honours it only if it moves *proportionally to
the delta* and adds *no momentum of its own*, and Qt's default `Flickable`
fails both halves. Measured offscreen (PySide6 6.11, 5000px of content, a 240px
synthetic coast — 30 × 8px `pixelDelta`, `ScrollBegin` + updates, no
`ScrollEnd`, since the compositor withholds the terminal stop ≥300 ms):

| | during the stream | after it stops |
| --- | --- | --- |
| bare `Flickable` | 285 px | flicks on to **342 px** (+43%) |
| `Kinetic*` | 240 px | 240 px, dead stop |

and one classic detent animates a bare Flickable 0 → 72 px on its own timeline.
That second decay curve is not "more kinetic", it is two curves fighting.

**The overlay sits at `z: -1`, BEHIND the content, and it must stay there.**
The reparent (`Component.onCompleted: parent = view`) makes it a *sibling* of
the view's `contentItem`, appended after it — so at the default z it is the
topmost item over the whole viewport and sees every wheel first, silently
shadowing every wheel handler nested in the content. That shipped for a few
hours and painter is where it showed: its `Spin` steppers, the model and LoRA
lists, an open `Picker` dropdown and both `PromptBox` editors all live inside
one `KineticFlickable`, and none of them responded to the wheel while the left
column could scroll. Measured offscreen against the real components — a nested
handler went 5/5 → 0/5 wheel events, and a nested `KineticListView` never
scrolled. `z: -1` restores the ordinary rule: the content gets the wheel, and
anything that declines it (a delegate with no `onWheel`, or a nested
`WheelScroll` with nothing left to scroll — it leaves those unaccepted on
purpose) falls through to the overlay. Both branches are verified offscreen;
re-check them if the reparent is ever touched.

Knobs, all optional: `wheelLines` / `wheelStep` (how far one *classic mouse
detent* moves — the touchpad path is 1:1 finger pixels and has no knob),
`wheelEnabled: false` (let the wheel bubble out of a view that must not eat it),
`wheelGain` (**surfer only**, below), `onWheelScrolled` (the view moved because
the user drove it).

**One place for the values.** `qmlcommon/WheelScroll.qml` is the only QML
implementation — it used to exist twice, in `player/qml/` and `painter/qml/`,
while `filer/qml/Main.qml` merely quoted its rationale in a comment and had no
copy at all. `apps/pylib/kinetic.py` is the only Python one (`DETENT`,
`ANGLE_PER_PIXEL`, `WHEEL_GAIN`, `is_wheel_detent()`); anything touching
`QWheelEvent` in Python imports from there rather than re-deriving the numbers.

### `SpellMarks.qml` — the one spelling marker

`pylib/spellcheck.py` decides what is wrong; **`qmlcommon/SpellMarks.qml` is the
only thing that draws it**, and docs/DESIGN.md §3.7 owns the look (1px dashed
`crit` underline — Qt Quick renders no wavy underline and ignores
`setUnderlineColor`, both measured, so the marker is `QtQuick.Shapes` geometry
and not a character format). Drop one in as a **sibling of the text item, in the
same coordinate space**, and hand it the flickable it scrolls in:

```qml
TextEdit { id: input; ... }
SpellMarks { id: marks; target: input; viewport: flick
             x: input.x; y: input.y; width: input.width; height: input.height }
```

- `viewport` is not optional in practice: it limits the check to the visible
  screenful, which is what keeps a 40k-word document cheap.
- `menuItems(pos)` returns `CtxMenu` items for the word at a character offset —
  suggestions, `add to dictionary`, then a separator — or **[]** when the word
  is fine or there is no dictionary. Concatenate it onto the front of whatever
  menu that input already opens; never build a second menu for it.
- `replaceFn` when the host has a real edit block. editor passes
  `Buffers.replaceOne`, so a correction is ONE Ctrl+Z; the default
  `remove` + `insert` costs two.

**Which surfaces have it, and which were left alone on purpose.** Prose gets it:
editor (documents detected as `text`/`md` only — `highlight.py` is regex-per-line
and cannot tell a comment from an identifier, so a source file is not checked,
and the language menu is how you turn it on by hand) and painter's two
`PromptBox`es. Deliberately NOT spellchecked, because none of them is prose:
filer's inline rename/mkdir field, reader's and player's find/filter fields,
editor's find bar and path bar, surfer's find bar and file-picker fields (its
*pages* are Chromium's own checker — `surfer/AGENTS.md`), painter's numeric
`Spin`/`Field`, and **askpass, which is a password box and must never send
characters anywhere**. goetia's inbox is a separate decision; see
`board/AGENTS.md`.

### `VScroll.qml` — the one scrollbar

`ScrollBar.vertical: VScroll {}` on every scrollable view, and **the call site
never chooses how it looks.** docs/DESIGN.md §9.2 is one idiom for the whole
desktop, and since 2026-07-28 it is a pixel-era one in three variants — `win31`
(default, 16px, stepper arrows), `beveled` (14px, no arrows), `flat` (11px, no
bevel) — selected by the user in Settings > Appearance. `VScroll` reads the
choice itself off `DeskStyle.scrollbarStyle` (below), behind the same `typeof`
guard `Motion.qml` uses, so a harness with no `DeskStyle` still renders.

Three properties of it are rules, not details:

- **`policy: AlwaysOn`, full opacity, no `Behavior` anywhere.** The old 120 ms
  fade is gone and §6.2.1's non-participants table no longer lists a scrollbar
  duration. Always-on is what stops content reflowing when a view starts to
  overflow.
- **Arrows are drawn as GEOMETRY** (five 1px `Rectangle` rows), never as a
  glyph — the font has no `↑`/`▲` and a missing one clips the line (§2.3) — and
  they genuinely step, 48px per click via a `stepSize` derived from the
  flickable's `contentHeight`. An arrow that cannot move the view goes `dim` and
  refuses the click.
- **The thumb is pixel-snapped** against the fractional offset `ScrollBar`
  computes for it, or every 1px bevel shimmers for the length of a drag.

**A call site that reserves a gutter must read `VScroll.barW`**, never a
literal: the width is a setting now and ranges 11-16px. reader's `DocPane`,
painter's `Main`, player's `LyricsView`/`TrackList` and the album grid's cell
arithmetic all had a hardcoded 8/10/12 fitted to the old 9px bar, and all four
left content under an opaque one until they were changed.

It used to exist as four copies — player's, painter's, and an inline `component
VScroll` in each of filer's and reader's panes. **All folded in** in the same
pass; `qmlcommon/` is the only copy, and §19.1's entry for it is closed.

**A control that STEPS a value is not a scroller.** `qmlcommon/WheelNotch.qml`
is for those — painter's numeric `Spin` boxes today — and it is the apps-side
twin of `home/prog/quickshell-files/WheelNotch.qml` (same algorithm, two roofs,
retune both). One classic detent is exactly one step; a touchpad's sub-notch
remainder is *carried*, never rounded up; `maxSteps` caps a single event, so a
compositor momentum coast cannot walk a value across its whole range on one
flick. painter had its own accumulator with the constants written out again and
no ceiling, which is what this replaces.

### The mouse's side buttons are `NavButtons`, never a hand-rolled MouseArea

`qmlcommon/NavButtons.qml` + `qmlcommon/NavHistory.qml`. The desktop-global rule
is `~/nix/docs/DESIGN.md` §11.1 — *"back and forward mouse buttons should function in
every program"* — so an app wires the shared handler to whatever its own history
is and does not re-implement either half:

```qml
NavButtons {                      // a child of the root Window, nothing else needed
    onBack:    win.pane.goBack()
    onForward: win.pane.goForward()
}
```

- It accepts **only** `Qt.BackButton | Qt.ForwardButton`, so every other press,
  wheel notch and hover falls through — which is why `z: 9000` is safe over the
  whole window, and why it must stay a sibling of the content rather than a
  wrapper.
- **In a multi-pane app it acts on the FOCUSED pane**, like every other control
  (filer's `win.pane`, viewer's `win.prev/next`, surfer's `win.current`).
- `NavHistory` reassigns its stacks instead of mutating them, so `canBack` /
  `canForward` notify and a titlebar button can bind to them. player's
  hand-rolled stack did the opposite and only got away with it because nothing
  was bound.
- **A program with no genuine history gets nothing** (painter, askpass). Do not
  invent one; docs/DESIGN.md §11.1 records the reading for each app and why.
- Regression test: `filer/tools/nav-test.py` (offscreen, posts real
  `QMouseEvent`s for buttons 275/276).

**The one exception, and why it is one:** `viewer/qml/ImageViewer.qml` keeps a
bare `Flickable`. Its `interactive` buys DRAG-panning of a zoomed image, and its
`WheelHandler` (delta-proportional, `exp(ln1.2/120 · d)`) consumes every wheel
event before the Flickable can see one — so a coast lands on the zoom, which is
why viewer came off `kinetic_deny_classes`. Add a comment like that one if you
ever need another exception.

**surfer is special.** Its window-scoped `ZoomFilter` divides every touchpad
wheel event by `WHEEL_GAIN` (1/6) so QtWebEngine pages track the finger like the
QML apps do — and that scaling hits surfer's own QML overlays too. Any
scrollable view in surfer's window must therefore take `wheelGain: WheelGain`
(the reciprocal, published by `main.py` from `pylib/kinetic.py`). The web page
itself is Chromium's scroller and cannot be made to use `WheelScroll`; parity
there is the gain plus the compositor's ≥300 ms withheld stop, which zeroes
Chromium's 200 ms fling estimator so it never adds a fling of its own.

**The panel has the same convention under a different roof**
(`home/prog/quickshell-files/Kinetic.qml` + its `Kinetic*` types, documented in
that directory's `AGENTS.md`). The two trees cannot share a component — the
panel's QML is Quickshell's and this is plain Qt — so they are deliberate
parallel implementations of one rule, anchored to the same
`kinetic_friction`. Retune one and retune the other. Note the panel additionally
needs its own Qt-side deceleration because hyprvtb refuses to coast over a
*layer surface* at all, which almost all of the panel is; the apps are ordinary
toplevels and do get compositor momentum.

**Momentum has to be ON to be honoured, and `hyprctl reload` clears a runtime
`kinetic_set(true)`.** The durable switch is the `plugin:hyprvtb:kinetic`
config key, set in **both** copies of `hyprland.lua` and per-host via
`home/prog/hypr-host.nix` (on for air/book, off on top, which drives a wheel
mouse). None of that is in `apps/` — if momentum seems absent, check there
before suspecting a view.

**Guard every rect you hand hyprvtb.** Hyprland's `renderRect` aborts the
compositor on a zero-size box, so an app feeding the vtb socket can take the
whole session down (the player's paused-at-0:00 `PLAYBAR` did exactly that).
Fixed plugin-side in v2.45, but guard on the app side too.

## Verifying changes

- **The user does ALL visual/animation/interaction checks.** Never screenshot or
  drive these GUIs yourself unless explicitly asked.
- **Never open a test window on the user's screen** — use `tools/sandbox.sh`
  (off-screen virtual monitor: `start` / `exec CMD` / `shot` / `clients` /
  `stop`).
- **Every harness in `apps/*/tools/` opens with the same four lines, and a new
  one copies them** (2026-07-30, after he reported test windows appearing and
  his pointer being moved while agents worked):

  ```python
  os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
  os.environ.pop("WAYLAND_DISPLAY", None)       # and nothing to fall back TO
  os.environ.pop("DISPLAY", None)
  ...
  app = QGuiApplication(sys.argv)
  if app.platformName() != "offscreen":
      raise SystemExit("refusing to run on platform %r, not offscreen" % ...)
  ```

  `setdefault` was the hole: an exported `QT_QPA_PLATFORM` — his session's, or a
  packaged wrapper's, which several of these harnesses borrow — silently won,
  and the test mapped a real window. With no display there is nothing to fall
  back to, so Qt aborts loudly instead, and the assertion says so in one line
  rather than after a screenful of Qt noise. A child process gets the same
  treatment in its `env` dict (surfer's `split-test.py`, filer's `e2e-test.py`,
  askpass's selftest).
- **Tear down in a trap** (`try/finally`, or `atexit.register`), never at the
  end of the happy path: the harnesses that leak into his session are the ones
  that failed halfway.
- **Never source an app's wrapper to borrow its Qt env — use `surfer-qtenv`.**
  A wrapper is a program, not an env file: sourcing it runs its BODY. surfer's
  body probes the single-instance socket, so `. $(which surfer)` hands his LIVE
  browser an `OPEN` with no url — a new home-page tab in the window he is
  looking at — and the next line redirects the sourcing shell's stdout into
  `~/.cache/surfer.log`. That is not hypothetical: three DuckDuckGo tabs
  appeared in his session on 2026-07-30, from three attempts to borrow the env
  for an offscreen harness. The `sed '$d'`/`head -n -1` variants do **not**
  help — they strip the final `exec`, which is the one line that was harmless.

  The safe recipe, and it is one line on both hosts:

  ```bash
  surfer-qtenv python3 apps/surfer/tools/find-test.py   # exec form: Qt env + surfer's own python
  ( eval "$(surfer-qtenv)"; ... )                       # print form, in a SUBSHELL
  ```

  `surfer-qtenv` is built beside `surfer` by `home/prog/surfer.nix` from the
  same `wrapQtAppsHook` arguments, so it is the identical environment with none
  of the body — no socket, no redirect, no browser. Three guards now make the
  old route fail loudly instead of silently: the wrapper refuses to be sourced,
  `apps/surfer/singleton.py` refuses a bare no-URL invocation from a caller
  with no tty, and `surfer.desktop` carries `SURFER_DESKTOP_LAUNCH=1` so his own
  launches are still allowed. **Only surfer ships a `-qtenv` helper so far** —
  for the other eight, take the interpreter path out of the wrapper's last line
  and set nothing else, and add the helper if you find yourself needing more.
- **Never script hyprvtb's Lua actions to probe behaviour** — `hl.dsp.focuswindow`
  is nil there, so `rollup`/`minimize_active` land on HIS active window. Play
  the plugin's part instead: bind a scratch `hyprvtb-buttons.sock` in a scratch
  `XDG_RUNTIME_DIR` and read the wire (`surfer/tools/split-test.py` is the
  pattern), or stub `Titlebar` outright.
- Syntax-check QML headlessly: `qmllint -I <qml import paths> qml/Main.qml`
  (import paths from the app's wrapper env). The "Failed to import" lines are
  missing paths, not errors.
- For app logic, write a headless PySide harness (e.g. pre-grant a permission
  and assert a signal fires) rather than clicking.
- QtWebEngine/permission/notification API details are best confirmed against the
  QML type defs (`plugins.qmltypes`) rather than guessed.

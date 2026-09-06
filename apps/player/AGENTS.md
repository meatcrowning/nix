# `player` — music player

Vendored source of the standalone Qt/QML music player (`main.py`, `qml/`).
Built/installed by `home/prog/player.nix` (mirrors `viewer.nix`); runs the
**live** source, so `.py`/`.qml` edits need no rebuild — relaunch the app. See
[`../AGENTS.md`](../AGENTS.md) for the shared live-source/pylib/vtb rules.

Tag-driven library (background mutagen scan of `/run/media/lam/SSD/aud` →
`~/.local/share/player/library.db`, art thumbs in `~/.cache/player/art/`),
libmpv playback (python-mpv), MPRIS via `mpris-server` (the panel's MediaPanel
controls it), FMPS rating/playcount/favourite tag writeback (journaled to
`~/.local/state/player/tagwrites.log`, gated by prefs `tagWrites: off|log|on`,
ships in `log`), synced lyrics, ReplayGain volume levelling.

## Every write to a library file goes through `atomicsave.py`

**There are exactly two paths that modify a file in `aud/`** — `TagWriter`
(FMPS rating / FAVORITE / playcount) and `lyrics.write_embedded` (USLT /
`LYRICS` / `©lyr`, also used by `tools/lyrics-sync.py`) — and **both** now end
in `atomicsave.atomic_save(path, mutate)`: copy beside the original, mutate the
copy, `fsync`, `os.replace()`. Never add a third `mutagen.save()`.

Both used to save in place, which for a tag block that outgrows its padding
shifts the audio data itself; an interruption there leaves a truncated file on
exFAT, with no snapshots anywhere on this machine to undo it. The lyrics path
was the live one — it defaults on and had already written to the library.

The module's docstring carries the reasoning; the four rules it is easy to
undo are: the temp file must be **in the target's own directory** (elsewhere,
`os.replace` is not a rename), it must **keep the original extension**
(`mutagen.File()` scores partly on the filename — a `.tmp` copy of a `.dsf`
sniffs wrong), **mtime is preserved** (the scan caches on (mtime, size) and
dbsync ships the DB to book on mtime passing through SMB byte-exact; both write
paths update the DB row themselves, so no rescan has anything to rediscover —
size still changes, so a genuine re-read still happens), and free space is
checked against the **target's own filesystem** before the copy, failing with
`NoSpace` and a journal line rather than filling the disk. The old "in-place, no
free-space cost" rationale was written against a 95%-full SSD; it is 932G with
662G free (2026-07-28).

`TagWriter` **coalesces**, because a copy is far heavier than an in-place save:
a popped entry waits `COALESCE_S` (1.5s) and then absorbs every other queued
entry for the same path, last value winning per field. Five stars clicked in a
row are one rewrite of the FLAC.

```bash
tools/atomic-write-test.py --samples DIR [--exfat-probe DIR]
```

Runs on COPIES only and refuses to run inside `aud/`. Per format
(mp3/flac/m4a/dsf/wav) it hashes the **audio stream alone**
(`ffmpeg -map 0:a -f s16le - | md5sum` — never plain `-f md5 -`, which is
nondeterministic with cover art), round-trips the tags, and checks mtime and
temp-file hygiene; then every failure path (no space, missing file, unreadable
audio, read-only directory, a `mutate()` that raises) for "original intact, no
litter"; then hammers `os.replace()` with a concurrent reader to show it is a
real rename on **exFAT** too. 53/53 on the SSD, 2026-07-28.

## `tools/tagtool.py` — the arbitrary tag/art edit, and its one door

`curate/` decides what a cluster of files SHOULD be called and converges it.
`tagtool.py` is the other half: the single edit he asks for in a sentence —
*"remove the disc numbers from this album"*, *"replace the cover with the one
from last.fm"* — on the selection he names, on any key, in any container. Ops
`show / set / remove / art / art_remove / undo / list_undo`, as a CLI or as
`--json` on stdin.

Four invariants, and none of them is optional:

- **Dry run is the default.** The apply is the same code path one step further
  on, so what the dry run printed is exactly what the apply writes.
- **Every write goes through `atomicsave.atomic_save`** (see above). No bare
  `mutagen.save()` here either.
- **The rating, the favourite and the play count are refused by name**
  (`RESERVED`), in `set` and in `remove` alike. They are the only library
  metadata with no second copy anywhere.
- **Every apply writes an undo manifest** to `~/.cache/player-tagtool/` — old
  values, and the old cover bytes — and `undo <token>` restores it. It also
  updates the tracks row it changed, so the player shows the edit with no
  rescan.

`AUD_ROOT` / `PLAYER_DB` / `TAGTOOL_STATE` move the three paths, which is how
`tools/tagtool-test.py` exercises all of it (mp3/flac/m4a/ogg made with
ffmpeg, in a temp dir) without going near the library. Chatter reaches it as
the custom tool `music_tag` (`~/.local/share/oracle/tools/`), which runs it on
`top` over ssh from `book`; the model-facing rules live in the
`music-library` skill.

**`tagWrites` cannot be changed while the app is running** — `Prefs` holds the
whole file in memory and rewrites all of it on any `set()` (volume, sort,
album-grid scroll, quit), and reads prefs only at startup. `tools/set-pref.py`
sets a key from outside, backs the file up, and refuses while `main.py` is up.

**IN A PLASMA SESSION PLAYER IS A REAL KDE WINDOW** (2026-08-22). Not a window
imitating one: a `QMainWindow` with a real `QMenuBar`, a real view `QToolBar`, a
real transport `QToolBar` along the bottom, a real `QStatusBar` and the KDE
style's own window background, with `qml/Root.qml` as the central widget's QML.
All of that is `pylib/kdeshell.py` — read `../AGENTS.md` → *pylib/kdeshell.py*
before touching any of it; only what is player-specific is here.

- **`Main.qml` is now a 25-line `Window` around `Root.qml`**, and is loaded in
  the Hyprland session only. `Root.qml` is an `Item` and holds the whole app.
  Nothing Window-only lives in it: the title goes out as `windowTitle` (bound by
  `Main.qml`, and put on the QMainWindow by `kdeshell.bind_title`).
- **ONE TABLE, EVERY CHROME.** `Root.qml`'s `tbButtons` is the hyprvtb titlebar
  column *and* the menubar *and* both toolbars *and* their shortcuts, annotated
  with `menu`/`menuText`/`icon`/`bar`/`group`/`shortcut` — all inert on the vtb
  wire. `bar: true` is the top toolbar, `bar: "transport"` the bottom one.
- **`qml/ViewBar.qml` and `qml/PlayBar.qml` are GONE** (they were the 2026-08-18
  first pass: QML strips imitating a view toolbar and a transport bar, gated on
  `DeskStyle.plasma`). The three page switches are a radio group of real toolbar
  rows, the sort cycler is one with `barText` so it carries the full word, and
  the finder is a real `QLineEdit` at the right-hand end
  (`kdeshell.toolbar_search`), where Dolphin and Gwenview keep theirs. The
  transport is six `QAction`s on the bottom bar plus `transport.py`.
- **The menus are the COMPLETE set, the toolbar the primary verbs** — so the
  three views and the sort row are in the View menu *as well as* on the bar.
  The old `menuBarButtons` filter that took the whole `view` group out of the
  menubar is gone with the strip it existed for.
- **`transport.py` is the seek bar**, the one thing on the bottom toolbar that
  cannot be a `QAction`: a `QSlider` between two fixed-width clocks, drawn by
  the KStyle. Controlled, never stateful — the handle follows `Player.position`,
  a drag or a wheel notch only calls `Player.seekFrac` — with the same two held
  values `PlayBar.qml` had, and for the same reasons: `_drag` while the pointer
  is down, `_pending` until the source catches up with a wheel seek. A press on
  the groove seeks to the CLICK, not one page towards it, and the wheel banks a
  touchpad's sub-detent remainder (`qmlcommon/WheelNotch.qml`'s algorithm, in
  Python, because this control is not QML). Harness: `tools/transport-test.py`
  — offscreen, against a FAKE Player, because the running one is his and must
  never be driven.
- **Settings are a dialog, not a drawer.** There is no titlebar edge for a
  drawer to slide out of, so the rows moved into `qml/SettingsPage.qml` and
  `qml/SettingsPanel.qml` is now only the Hyprland roof over them — the same
  page is the content of "Configure player…" (`kdeshell.dialog`, opened through
  `kdeshell.on_action("settings", …)`). The dialog is a separate scene, so its
  `columns`/`scanStatus`/`scanning` are pushed rather than bound; `pad` is how
  the roof says how much room the rows get from the edge.
- **`qml/+plasma/` swaps the controls**, through the file selector, with no
  branch at any call site: `HeaderButton` is a flat `Button`, `SelectButton` a
  real `ComboBox`, `Slider` a QQC2 `Slider` (re-applied
  through a `Binding`, since a QQC2 Slider owns its value and a plain binding
  would break on the first drag), `CtxMenu` the style's own `Menu`, `EditField`
  a `TextField` and `SheetFrame` a `Pane`. Each
  carries `property string face: "plasma"`, which is the only way to prove the
  selector took — an unowned `QQmlFileSelector` is collected moments after it is
  made and every component then loads its unselected file, silently.
    - **A glyph is not a label on a real button.** `HeaderButton`'s `label` is
      written for the pixel face, where an affordance IS a character — `> play`,
      `+ queue`, `x close`, a bare `x`. On the styled Button the twin draws,
      that is the hyprvtb titlebar's vocabulary leaking into a session with a
      whole icon theme for it, so a call site with a glyph states `plainLabel`
      and `iconName` (or `iconOnly` for the wordless ones) beside it and the
      twin draws THOSE. All three are inert in the sibling, so the Hyprland
      button is byte-for-byte what it was — verified by rendering both views
      offscreen against `HEAD` and comparing the PNGs. `tools/plasma-chrome-test.py`
      asserts it over the SOURCE, not a render: a button on a page nobody opened
      in that run is exactly the one a render misses.
    - **`SelectButton`'s choices are DECLARED** (`options`, `chose(value)`),
      not built inside an `onPicked` handler. That is what lets the twin be a
      ComboBox at all — the KStyle's popup needs a model — and the Hyprland
      sibling still opens the pane's one shared `CtxMenu`, from an items array
      the button hands it. It was a `Button` with a hand-drawn `▾` in a `Text`
      indicator until 2026-08-23, under a comment claiming the style drew the
      arrow; no QQC2 primitive hands out Oxygen's arrow on its own, because
      Oxygen draws it as part of the whole combo.
    - **`EditField` is THE one-line text entry**, and `SheetFrame` the surface a
      modal sheet sits on. Both exist because the rule editor was the last place
      in this app drawing a KDE widget by hand: three `bgAlt` rectangles with a
      `TextInput` in them, inside a box wearing a window frame of ours. The
      editor's row heights come off the twins' own `implicitHeight`
      (`SmartEditor.ctrlH`, 0 outside Plasma), because Oxygen's field and combo
      are taller than the pixel face's 24 and a row pinned to 24 crops the frame
      it is drawing. `EditField`'s focus helper is `focusInput()` and NOT
      `forceActiveFocus`: a function declared over an Item method loads with no
      error and then behaves as if the body calling it had stopped running.
    - **A separator in the Plasma `CtxMenu` is a `MenuSeparator`.** An
      `Instantiator` makes one delegate type, so it used to arrive as a disabled
      empty `MenuItem` 8px tall — a gap where Oxygen draws an etched line. The
      menu is built imperatively from two components now. Same fix in chatter's
      and painter's copies.
- **The search results overlay binds `Theme.windowFill`, not `Theme.bg`.** It
  covers the whole content area, so a flat fill of the scheme's window colour
  was a patch laid over Oxygen's gradient — the one break in the surface that
  runs unbroken from the titlebar down. It still has to OCCLUDE the pages under
  it, so `qmlcommon/StyledBackground.qml` is drawn behind it instead, put back
  at the VIEW origin (`x: -root.x`) and cut by the overlay's own clip: the
  provider crops the style's render to the view's rectangle and pads from the
  item's top-left, so an overlay inset from the top would otherwise restart the
  gradient at its own edge.
- **The QML `Shortcut`s all stand down under Plasma** (`enabled: !win.plasma`),
  except Escape: the sequences are on the QActions there, and two owners of one
  sequence in one window is an ambiguous shortcut, which Qt answers by firing
  NEITHER. Space and `L` are bare keys, so `kdeshell.guard_typing` suspends them
  while the toolbar finder has the keyboard.
- **The finder is still ONE field.** `Root.qml`'s `searchInput` remains the
  window's single source of search truth in both sessions — filter vs full
  results, Escape, the click-out unfocus are all decided there — and under
  Plasma `main.py` mirrors it onto the `QLineEdit` and back, guarded against the
  loop a two-way mirror otherwise makes. The box itself is `visible: !plasma`.
- **`Titlebar` must publish `buttonsChanged`, and that is not optional.**
  `kdeshell.bind_chrome` hangs its whole refresh on that signal: the vtb socket
  is dead in a Plasma session, but `Root.qml` still pushes its entire button
  table through `setButtons` on every state change, so it is the one "the chrome
  changed" notification this face gets. player's class had no such signal for a
  day, and the menubar and both toolbars were built once and then FROZE — play
  never became pause, the favourite never lit, and prev/play/next stayed greyed
  by the empty queue they had started with. Nothing failed and nothing warned.
  `bind_chrome` now falls back to a 300ms poll and says so on stderr, but the
  signal is the fix.
- **`main.py --selftest`** builds the whole thing OFFSCREEN and quits: no MPRIS
  name, no queue socket, no library scan, no `save_state` — all four are
  singletons or state a running player already owns. `PLAYER_MENUS` dumps the
  chrome as text (a menu is not on screen until it is opened, so no render can
  show what is in one), `PLAYER_FACES` proves the selector took, `PLAYER_SHOT`
  writes a PNG, `PLAYER_DIALOG` grabs Configure player…, `PLAYER_TREE` dumps
  item geometry, `PLAYER_VIEW` picks the page without persisting it (on the
  Hyprland side it reaches the Root INSIDE `Main.qml`'s Window — set on the
  window it invented a property nothing read, so the flag silently did
  nothing in that session), `PLAYER_SMARTEDIT` opens the smart-playlist
  editor over the playlists page (`1` for a new list, else a list name to
  edit; an in-window sheet, so `PLAYER_SHOT` does contain it), and
  `PLAYER_STATEPOKE=1,2,3` (+ `PLAYER_STATEPOKE_PLAYING=1`) puts a queue under
  the app with nothing decoding a byte — mpv is his audio device — so a harness
  can watch the chrome follow the app's state. That poke happens LAST, just
  before the dump: mpv's own idle and pause observers fire during the wait and
  would put `_playing` back under it. Harness:
  `tools/plasma-chrome-test.py`. **`QT_QPA_PLATFORMTHEME=kde` is not optional**
  in any of those commands — without it the widgets take Qt's default light
  palette while the QML takes his dark scheme.

**ALL chrome is hyprvtb titlebar buttons** — transport + view switcher + sort +
the `fs` search toggle (`Ctrl+F`; it was labelled `/`, a key nothing was ever
bound to — docs/DESIGN.md §11.2, §12.1) + a bottom-anchored settings button
whose drawer (surfer's `dm`-panel idiom) holds rescan and the album gallery's live column count — plus
the `PLAYBAR`/`SEEK` scrub bar. The pushed playbar fraction is floored at 0.002
because plugin builds ≤2.44 abort the compositor on a zero-height fill rect
(fixed plugin-side in v2.45 — guard every computed rect when adding hyprvtb
drawing).

**The now-playing cover art is RESPONSIVE, and the narrow window is the
reference.** `NowPlaying.qml`'s art is a full-width top row in the ~480x826
window this page normally lives in, and a full-height LEFT COLUMN once the
window is wide (`sideArt`) — because a top row scales a square cover to the
window's *width*, so maximized it kept a 1406x472 band, 30% of the art. Both
branches bleed to the window outline; neither letterboxes (docs/DESIGN.md §5.1)
— **except in a Plasma session, where the cover is never cropped**: his call,
2026-08-18, so there `fillMode` is `PreserveAspectFit` and the shortfall shows
`artBox`'s own `bgAlt`. That is a straight trade of §5.1's edge-to-edge fill for
the whole picture, taken in that session only; the responsive row/column switch
above is unchanged and still runs in both.
Two constraints when touching it: the switch reads **window geometry only**,
never `artFrac` (a layout that flipped mid-drag would rearrange the page under
the cursor), and it must be a **strict no-op below the breakpoint** — verified
by rendering both branches offscreen and comparing PNGs byte-for-byte across
sizes, `artFrac` values and with/without lyrics, which is the harness pattern to
reuse for any further change here.

**Track list, album grid and both lyrics panes are `Kinetic*` views from `../qmlcommon/`** — player's scrolling policy is the scrollbar and the wheel only, never drag-flicking, so the compositor's momentum is the only momentum. `WheelScroll.qml` used to live in `player/qml/`; it is shared now and player is no longer its owner. `TrackList` passes `wheelEnabled: root.scrollable` so a table sized to hold every row (AlbumPanel) hands the wheel out to the gallery behind it. See [`../AGENTS.md`](../AGENTS.md).

## Focus: three tones, derived once, handed down — the fade is RETIRED (`docs/DESIGN.md` §3.1.1)

**No file under `qml/` may read `Theme.text`, `Theme.textDim` or `Theme.accent`
for a thing it draws, and none may read `Window.active`.** `Main.qml` derives

```qml
readonly property bool renderActive: true   // §3.1.1's fade, pinned off
readonly property color fgText:   renderActive ? Theme.text    : Theme.inactive
readonly property color fgDim:    renderActive ? Theme.textDim : Theme.inactive
readonly property color fgAccent: renderActive ? Theme.accent  : Theme.inactive
```

and every pane, list, drawer and leaf takes those three as plain `color`
properties (defaulting to the lit tones, so a harness can build one alone).
**The app-side §3.1.1 fade is RETIRED — his board call, 2026-08-09**: with "dim
unfocused" on, the native `decoration:dim_inactive` scrim is the ONE dimming
mechanism, and an app that also greys its own foreground reads darker than a
plain window. `renderActive` is pinned to `true`; the plumbing is retained so a
one-line change at the window re-arms the whole fade. `Theme.inactive` is still
the exact grey hyprvtb fades the titlebar to; player was the **third** app to
grey its chrome and leave its content lit, after painter and reader — the
history is in `docs/DESIGN.md` §3.1.1, and the wiring exists so the fade can
come back whole if he ever asks.

**The artwork rode the same fade**, through a fourth derived value on the same
chain — `readonly property real fgArt: renderActive ? 1.0 : 0.55`, wired
`Main` → `AlbumGrid` → `AlbumPanel` and `Main` → `NowPlaying`. **All three
covers**: the gallery thumbnails, the album section's art and the now-playing
full-bleed cover. The 2026-07-28 call — *"dim it with everything else — the
window reads as one unfocused surface"* — survives; the mechanism died with the
retirement: `fgArt` is pinned to 1.0 and the native scrim dims the covers as
part of the surface. Do not resurrect either half on its own.

Deliberately never faded, and each for a reason (unchanged by the retirement):

- **`Theme.dim`** — the tertiary tone (the `♫` art placeholder, an unrated star,
  a play count, the search placeholder). It sits *below* the inactive grey, so
  mapping it there would BRIGHTEN it on focus loss.
- **`Theme.crit`** — the favourite heart is a status colour, per `PreviewTile`'s
  error tone.
- **`Theme.border` / `Theme.bgAlt` / `Theme.highlight` / `Theme.bg`** — §3.1.1
  moves foregrounds only. The row-highlight fill in particular must not move, or
  the window reads as broken rather than unfocused.
- **`CtxMenu` / `TrackMenu`** — `CtxMenu.qml` is byte-identical to filer's, and
  inside it `Theme.inactive` already means *disabled*: fade the whole menu and a
  greyed-out entry becomes indistinguishable from a live one. A menu is also
  only ever open on a focused window. Changing it is a seven-app decision, not
  player's.
- **`Theme.windowBorder`** on the settings drawer — nine call sites across five
  apps draw an overlay frame with it and none of them switch to the
  `windowBorderInactive` that `Theme` already defines. Worth doing, but
  desktop-wide and in one pass.

```bash
tools/focus-fade-test.py [--png DIR]   # offscreen, never touches the live player
```

Its job inverted with the rule: instead of asserting that focus loss greys
everything, it asserts that focus changes NOTHING. Two layers: the derivation
(real `Window.active`, driven by activating a second offscreen window — no faked
flag — asserting `fgText`/`fgDim`/`fgAccent`/`fgArt` do not move), and the
pixels (480x826 — the size player actually runs at — histogrammed focused vs
unfocused, with a fake palette that gives every theme slot a unique hue so a
count is unambiguous: the two frames must be IDENTICAL slot for slot, cover art
included). Any app-drawn inactive state makes the frames differ and the test
fails. Two traps that harness paid for: `highlight` must not be a grey, because
`Theme.inactive` over `bg` composites to exactly `#404040`; and Qt caches a
directory's file listing on first load, so a scratch `.qml` written afterwards
fails with "File name case mismatch".

## The finder takes `genre:` and `year:` (2026-08-23)

`parse_query(text)` -> `(words, genres, year_lo, year_hi)`, and BOTH search
paths run through it: `Library.search` (the results overlay) and
`Bridge._apply_album_filter` (the album grid). Free text still matches
title/artist/album exactly as before — a filter is opt-in by typing a field
name.

    genre:shoegaze          genre:"post rock"       genre:a genre:b   (both)
    year:1997   year:1990-1999   year:2010-   year:>2010   year:<1980

- **The genre and the year are held BESIDE the search haystack, not in it.**
  Folded into the same string, `year:1997` would also match a track called
  "1997" and `genre:rock` an album called Rock — the one thing a field filter
  exists to prevent. `_search_rows` is now `(haystack, id, genre, year)`.
- **`year` is `COALESCE(orig_year, year)`**, the same expression the smart
  playlists use (`_FIELD_EXPR`), so a 2011 reissue of a 1979 record answers to
  1979 in both places. A track with no year matches only an unbounded query —
  a missing tag is not a 0 (`year_in`).
- **An incomplete term (`genre:`, mid-typing) contributes nothing** rather
  than matching nothing: filtering to zero rows on every keystroke while he
  types is worse than ignoring a half-written term.
- **The albums table has no genre and should not grow one** — a genre is a
  TRACK tag and a compilation has as many as it has tracks. `Library.album_meta()`
  derives `{album_id: (folded genre blob, year)}`, cached beside the search
  haystack and invalidated by the same `changed` signal.
- **This is not a second query language.** It is the two fields the smart
  playlists already own, spelled the way a person types into a search box: a
  smart list is a rule he keeps, this is a question he asks once.
- **The empty results state is where the syntax is named** — a 90px search box
  cannot carry a placeholder that explains it, and a syntax nobody is told
  about is a feature nobody has (docs/DESIGN.md §10).
- Harness: `tools/lastfm-test.py` (the parser cases live with the merge, since
  both needed a real `main.py` import).

## Last.fm: one listen is one play count AND one scrobble

`scrobble.py` is the Qt half; `../pylib/lastfm.py` is the API, the credential
file and the offline queue (read `../AGENTS.md` → `pylib/lastfm.py` first).
Nothing here happens until an account is linked — `tools/lastfm-connect.py`,
or the `connect` button in the settings page, which opens the approval page in
his browser and finishes by itself once he says yes.

- **The account file is machine-local, and that is the whole "wire it up".**
  `~/.config/lastfm/account.json` is a credential, `~/nix` is public and
  nothing syncs it, so player on book scrobbled nothing while top had been
  linked for months [his, 2026-08-24]. Either approve a second token there, or
  **`tools/lastfm-connect.py --copy-from top`**, which reads the file over the
  same BatchMode ssh everything else here uses and writes it 0600 — it refuses
  anything that does not parse as an account, and it needs top awake.
- **`Player._maybe_count` decides, once.** It already owned "this counts as a
  listen" for the library's own play count (half the track, or four minutes);
  it now calls `Scrobbler.submit` at the same instant, so the two counts cannot
  drift into telling him different stories about the same play.
  `lastfm.scrobble_point` is that same rule, and is what refuses a track under
  30 seconds — Last.fm's own floor.
- **The timestamp is when the track STARTED** (`Player._started_at`, set in
  `_set_index`), not when it crossed the threshold: Last.fm orders a history by
  it, and submitting the halfway point puts a 20-minute track in the wrong
  place.
- **now-playing is re-asserted on every start AND every resume**
  (`Player._announce`, called from `_set_index` and from the playing
  transition). A now-playing entry expires by itself, so an unpause that does
  not re-assert it shows him listening to nothing.
- **A heart is a love, and the heart never waits for it.**
  `Library.setFavorite` writes the DB and enqueues the tag exactly as it
  always did, then posts the love; a Last.fm outage costs the love, not the
  favourite. Prefs key `scrobbleLove` turns it off.
- **Every call is on ONE background thread.** They are blocking HTTPS round
  trips and this is the window he is looking at while they happen. Errors land
  in `lastError` (shown in the settings section) and never propagate.
- **Wired in after construction** — `player.set_scrobbler` /
  `library.set_scrobbler`, from `main()` only. Both classes still build with no
  account, no network and no `scrobble.py`, which is what every harness in
  `tools/` relies on.
- Prefs: `scrobble` (default on) and `scrobbleLove` (default on) — the two
  switches in the settings page, both hidden until an account is linked.
- **Pulling the account back in is ONE DIRECTION** [his, 2026-08-23: *"if i
  have a track liked here that's not liked on lastfm keep the local like"*].
  `Library.merge_lastfm` is the whole rule, and every field merges one way:
  **favourite** is set, never cleared (a local-only heart survives and is
  counted into `local_only_loves`, reported rather than reconciled);
  **play_count** is `max(local, remote)`, never lowered — Last.fm has only
  counted since the account was linked and this library has counted for longer,
  and `tools/dbsync.py` merges the two machines by the same rule;
  **last_played** moves forward only; **rating** is untouched, because Last.fm
  has no such thing and a "sync" that cleared one would be a bug.
    - **It does not push local favourites up.** The count is reported instead:
      a bulk write to his account is not what "update the local stuff" asked
      for, and `scrobbleLove` already loves everything hearted from now on.
    - **Matching is `trackmatch.keys`, not tag equality** — a scrobble carries
      whatever tag the file had when it played, decorations and featured
      artists included. Unmatched remote rows are counted, never guessed at.
    - **Several local files can be one recording** (a single and the album
      cut). Last.fm counts the RECORDING, so only the most-played local copy
      takes the remote total; raising every copy would multiply his history.
    - The fetch is the scrobbler's (network, its own thread), the merge is the
      library's (GUI thread, the library's own connection) — a second writer is
      how a library loses ratings. `Scrobbler.set_merger`, wired in `main()`.
      Button: settings ▸ last.fm ▸ **pull stats**.
- Harness: `tools/lastfm-test.py`. It stands up a stub audioscrobbler on
  loopback with `$LASTFM_CONFIG`/`$LASTFM_QUEUE` in a temp directory, so it
  cannot read his credentials or write to his real listening history. Run it
  as `oracle-qtenv python3 tools/lastfm-test.py` to get chatter's half too.

## Smart playlists are RULES the user owns (2026-08-07)

They were seven hard-coded `(name, SQL, params)` tuples in `main.py` under a
comment saying "one tuple to add another" — true for an agent editing this
file, useless to the person using the app. A list is now a **spec**:

```json
{"name": "4+ starred & liked", "match": "any",
 "rules": [{"field": "rating", "op": "at least", "value": 4},
           {"field": "favorite", "op": "is", "value": true}],
 "sort": "rating", "desc": true, "limit": 0}
```

stored in `$XDG_STATE_HOME/player/smartlists.json`. The **built-ins are only
the seed** (`DEFAULT_SMART_LISTS`): once a machine has the file they are the
user's, editable and deletable like any list they wrote, and
`restore_defaults()` puts back only the ones whose NAME is missing so it can
never overwrite an edit to one that is still there. Nothing stores membership —
opening a list re-runs the query, so it is live by construction.

The vocabulary lives in `main.py` and NOWHERE else: `SMART_FIELDS` (key, label,
kind), `SMART_OPS` (per kind), `SMART_SORTS`. The editor asks for all three at
open (`Library.smartFields()` / `smartOps(field)` / `smartSorts()`), so adding a
field there is enough to make it appear in the menus — there is no second list
in QML to keep level.

Four rules, each paid for:

- **A value never reaches the SQL as text.** Every rule contributes a `?` and a
  bound parameter; only the ORDER BY (looked up in `_SORT_COLS`) and the LIMIT
  (through `int()`) are interpolated. The specs are user-editable JSON that
  syncs between the machines — treating one as SQL is an injection into the
  library's own database, and the harness asserts it both ways.
- **A spec that makes no sense is skipped, never raised.** Unknown field, op or
  sort key drops that one rule and the list still opens. The file can be hand
  edited, badly merged, or written by a future build of this app.
- **Text compares through `cfold()`, not `lower()`.** SQLite's `lower()` is
  ASCII-only and a good slice of this library is Japanese; `Library.__init__`
  registers Python's `str.casefold` on its connection. `cfold(NULL)` is `''`,
  which is what keeps "does not contain" true for a track with no genre.
- **`desc` flips the FIRST sort column only.** The tie-breakers stay ascending —
  that is the difference between "best rated first, then alphabetically" and
  "…then backwards alphabetically", and it is what the hard-coded
  `ORDER BY rating DESC, artist, album` did.

Stars are the one unit conversion: the column is FMPS 0..1, the UI is 0..5, and
`_STAR_EPS = 0.01` is why "at least 4 stars" means `rating >= 0.79`. Ratings
written by fooyin/Strawberry land on 0.79/0.99, which is where the old
hard-coded thresholds came from in the first place.

**The view**: `PlaylistsView.qml` (sidebar + right-click menu + "+ new" +
"restore built-in playlists"), `SmartEditor.qml` (the modal, §7.2's spec) and
`SelectButton.qml` (a "pick one" box that opens the app's own `CtxMenu` — there
is no combo box on this desktop; since 2026-08-08 the dropdown is the shape of
EVERY enum pick desktop-wide, and filer holds a verbatim copy for its picker's
filter chooser — retune both or neither, like CtxMenu). Three things in the
editor that are load bearing:

- It holds a **working copy**; the store never sees a keystroke. Cancel is then
  free, and the list behind the modal keeps showing what it currently is.
- `rules` is reassigned (`rules = rules.slice()`) only when a row's SHAPE
  changes. A value edit mutates in place — reassigning rebuilds the delegates
  and would take the focus out of the box being typed into after one character.
  The clicked value controls (stars, yes/no) pass `rebuild = true`, because
  their value is a binding onto the rule.
- The window's global `Space` and `Escape` **stand down while it is up**
  (`PlaylistsView.modal`, read by `Main.qml`). A `Shortcut` is matched before
  the key reaches the focused item, so without that the name box can never
  contain a space — it pauses the music instead.

```bash
QT_QPA_PLATFORM=offscreen apps/player/tools/smartlist-test.py    # the rules
apps/player/tools/smartlist-ui-test.py                          # the editor
```

Both run in a throwaway XDG root with their own scratch `library.db` and
`smartlists.json`; the live library, the live lists and the running player are
never touched, and the UI one builds no `Player` at all (mpv, the MPRIS name
and the queue socket are exactly what a harness must not take). Both resolve
PySide6 by READING the `player` wrapper for its python env — never by sourcing
it, which runs the wrapper's body, i.e. launches the app. The UI harness treats
**every QML warning as a failure**: "the control is drawn and clicking it does
nothing" shows up as a TypeError and nowhere else.

## Right-click: one menu for every listing (`qml/TrackMenu.qml`)

player draws a track in five places — the queue, an album's inline section, a
smart playlist, the search results and the now-playing header — and every one of
them opens the **same** `TrackMenu`. The look and the ordering rule are
`docs/DESIGN.md` §7.2 (which also carries the vocabulary and why each entry
greys out when it does); this section is the mechanics.

- **Four of the five come free from `TrackList`**, which owns the menu and the
  right-click handler. A new listing gets one by existing.
- **The menu is parented to `Window.contentItem`, not to the list.** `CtxMenu`
  measures and clamps against its own bounds, and the queue is a ~240px column
  in a 480px window — owned by the list, the menu would be clamped to a sliver
  of the window or cut off at the list's edge. The right-click `MouseArea` is
  declared **last** in the delegate (so it covers the right-hand rating column
  that `rowMouse` deliberately stops short of) and accepts **only**
  `Qt.RightButton`, so every left click still falls through to the stars, the
  heart and `rowMouse` underneath it.
- **`TrackList` never navigates.** "go to album" / "search for artist" are
  relayed out as `openAlbumRequested` / `browseArtistRequested` and the window
  decides — the same reason `NowPlaying` already had those two signals. The
  relay chain for the album section runs `AlbumPanel` → `AlbumGrid` → `Main`.
- **The site supplies the two facts only it knows**: `inAlbum` (this listing IS
  that album, so "go to album" is absent rather than a no-op) and `isQueue`
  (rows are queue rows, so they can be removed).
- **No multi-select anywhere in this app**, so the menu acts on the row under
  the cursor. The Player slots all take a LIST of ids/indices, so a selection
  model would not need them changed.

Queue mutation lives in `Player.queueTracks` / `playNext` / `removeFromQueue`
(`queueAlbum` is now just `queueTracks` over an album's ids, and the album
cover's whole-album "play next" is `playAlbumNext`, which is `playNext` over
`album_tracks` in album order). Two traps they
exist to respect: `_orig_queue` — the pre-shuffle order — has to be mutated
alongside `_queue`, or anything added while shuffled vanishes the moment shuffle
is turned off; and a removal that does **not** touch the playing row must shift
`_index` arithmetically rather than through `_set_index`, which would also zero
the position readout and the play-count accumulator of a track that never
stopped.

Shuffle semantics (2026-08-08 — the "same shuffled order every time" fix):
`playTracks(ids, start)` takes `start=-1` for a **play-all** (playlist "play
all", album "play"/cover click) — under shuffle it pins nothing, where a real
clicked track (`playFromModel`, `AlbumPanel.onPlayed`) still pins that row
first via `keep_first`. Passing 0 for a play-all is the bug: it silently pins
the first playlist track as the opener of every shuffled play. And a loop-all
wrap goes through `_wrap_to_start()` (both the `next()` end branch and the
mpv-ran-out `_on_idle` path), which deals a fresh shuffled order each cycle —
never opening on the track that just finished — while leaving `_orig_queue`
alone so unshuffle still restores the real order.

```bash
tools/queue-ops-test.py   # headless; a Player built without __init__ (so no
                          # libmpv, no audio device) driven against a fake mpv
                          # playlist. The LIVE player is never touched.
```

## A deleted file leaves the library; an unplugged drive only greys

A track whose file is gone is **pruned, not greyed** — the row disappears from
the album, the playlist and the search, and the DB row goes with it. Deleting
the extra copies of a track outside the player (a dedupe pass over `aud/`) used
to leave them listed, greyed out, until the next full scan came round.

The greying is still there and still load-bearing: it is what an **unplugged
drive** looks like, and that case must never prune — with the drive gone every
path in the DB stats missing, so a blanket prune would erase the library,
ratings and all. `Library.prune_missing` is where both halves live:

- a **remote** library never prunes (`library_is_remote_cached` — its DB is
  authoritative and the per-track stat is skipped there anyway, see the `air`
  section), so those rows never even go grey;
- a **local** one prunes only while `library_mounted()` — the root is a
  directory **with something in it**, because an unmounted mountpoint can
  linger as an empty dir and `is_dir()` alone would wave the erase through;
- it re-stats the paths under that proven mount before deleting, and
  `rebuild_albums` runs after, so an album that lost its last track goes too;
- `changed` is emitted through `QTimer.singleShot(0, …)`: it drives the very
  listing refresh the prune is called from.

`Bridge._track_rows` is the one door — the three listings that stat their files
(`openAlbum`, `openSmart`, `search`) all build their rows through it, so the
behaviour cannot drift between them. A prune it was refused leaves the rows in
place, greyed, exactly as before.

```bash
player-qtenv python3 tools/prune-missing-test.py   # scratch DB + scratch root;
                                                   # the live library is untouched
```

## Opening a file by path (`%F`)

`player /path/to/track.flac` plays that track, and so does double-clicking one
in filer — `home/prog/player.nix` writes `Exec=…/bin/player %F` and player is
now the registered default for **all fourteen** extensions in `AUDIO_EXTS`.
Until 2026-07-29 it was the default for nine and dropped the argument on the
floor; `home/prog/mime-defaults.nix` and `docs/agents/mime-defaults-audit.md`
carry the reason the other five were withheld, which was exactly this defect.

**A LAUNCH WITH NO FILES IS A LAUNCH TOO** [2026-08-24]. `handoff_paths`
returned False on the spot when there were no paths, so the singleton check
simply did not run for a bare `player` — and a bare `player` is the common one:
the runner, the desktop entry, an agent with a shell. The second instance then
took the running one's queue socket (the server unlinks a stale path before it
listens), lost the race for the MPRIS name, and kept playing its own restored
queue with no name at all — a player the panel, Plasma's media applet and
chatter's `control_media` could none of them see. With no files the launch now
sends **`RAISE`**, the running window comes forward and the new process exits,
which is what clicking the icon meant. A player running the OLD source does not
know the verb, so that launch waits out its 2-second timeout and starts as it
used to; one relaunch fixes it.

Three pieces, each with a rule:

- **`paths_from_argv`** takes plain paths and `file://` URIs, skips anything
  starting with `-` (QGuiApplication owns the option namespace), and filters on
  `AUDIO_EXTS`. Honouring a `.pdf` dropped on the icon would be the app acting
  on a type it never registered.
- **`Library.ids_for_paths`** resolves a path inside the library to its **real
  row**, so a double-clicked track behaves exactly like the same track clicked
  in the queue — rating, play count, lyrics and its album all key on the id
  because it *is* that id. A path the library has never scanned gets a
  **transient row under a NEGATIVE id**, held in memory only and returned by
  `tracks_by_ids` alongside the DB rows. That is what lets a download outside
  `aud/` play at all, and the sign is load-bearing: every write path
  (`setRating`, `setFavorite`, `bump_playcount`, `LyricsProvider._resolve_one`)
  is `… WHERE id=?` followed by a guard on having found a row, so all of them
  miss and **nothing is ever written to a file this library does not own**.
  `save_state` stores the id and the next launch's `tracks_by_ids` cannot
  resolve it, so a one-off file does not come back — which is the wanted
  behaviour, not a leak.
- **The queue socket's `OPEN` verb** is the singleton. A second launch calls
  `handoff_paths`, which connects to `$XDG_RUNTIME_DIR/player-queue.sock` with
  a plain stdlib socket (before Qt starts — the whole point is not to start it),
  sends the percent-encoded paths and exits when the server answers. Two players
  must never run at once: they would fight over the MPRIS name, the socket and
  the audio device, and both would be audible. The module's docstring used to
  claim a *library lock* prevented that; there is no such lock — sqlite's WAL
  lets a second writer in after a 60s wait — so before this a second launch
  really did start a second player.

Opening REPLACES the queue (what every player does with a file handed to it
from a file manager), and an open whose arguments were all unreadable is a
no-op rather than a stop. With paths on the command line, `restore_state` is
called with `resume=False`: it brings back the session's shuffle/loop and queue
but does not re-sync mpv or post the delayed position seek, which would land
300 ms later on the queue that has since been replaced.

```bash
QT_QPA_PLATFORM=offscreen python3 apps/player/tools/open-path-test.py
```

Headless, on a scratch DB under an isolated `XDG_DATA_HOME`/`XDG_RUNTIME_DIR`;
the live player's socket, database and audio device are never touched. It covers
all three pieces, including a filename with a space and a `%` in it (the reason
`OPEN` is encoded at all — the protocol splits on whitespace) and the proof that
writing to a transient id creates no DB row. 37/37, 2026-07-29.

**Known gap:** a handoff cannot raise the running window — hyprvtb has no
"activate this window" verb the app can reach, and MPRIS `Raise` is declared
unsupported here. Double-clicking a track while player is minimized starts it
playing without bringing it forward.

## MPRIS: publishing is not owning

`start_mpris` prints and moves on if `mpris_server` is missing or `publish()`
raises — but `publish()` only ASKS for the bus name, on GLib's main context,
and the answer arrives later. A player that lost the race to another instance
therefore sat for an hour with no name at all and said nothing, while the
panel, Plasma's applet and chatter all reported no player [2026-08-24, on
book]. It now re-reads `ListNames` a second and a half later and says which it
is — `mpris: published as …` or a line naming the likely cause and what stops
working. `MPRIS_NAME` is the one place that name is written down.

## The queue socket (`start_queue_server`)

The desktop panel's media widget draws a queue drawer, and MPRIS cannot carry
it — the TrackList interface is optional and the panel's Quickshell has no
client for it. So the app serves its own queue on
`$XDG_RUNTIME_DIR/player-queue.sock`, one line at a time:

```
server -> client   {"index": n, "tracks":[{"title","artist","dur"}, ...],
                    "lyrics": {"source","synced","lines":[{t,line}],"text"} | null}
                   on connect, and on queueChanged / indexChanged / currentChanged
client -> server   GOTO <index>        -> player.jumpTo(index)
                   OPEN <enc> …        -> player.playPaths(...)  (replace + play)
                   QUEUE <enc> …       -> player.queuePaths(...) (append only)
                   LYRICS <0|1>        -> subscribe this connection to lyrics
```

- **`QUEUE` is `OPEN`'s counterpart, and it exists for the agents** [his,
  2026-08-23]. chatter can search the library and put something on
  (`apps/oracle` → `music_library`, `control_player play_these/queue_these`),
  which needs both "replace the queue with this" and "put it on after what is
  playing"; MPRIS has neither (`OpenUri` is a no-op here and there is no append
  in the spec at all). Same percent-encoding, same snapshot answer, and
  `Player.queuePaths` is `playPaths` with `queueTracks` at the end — including
  its "empty is a no-op" rule, so a request whose paths the library does not
  know leaves the queue exactly as it was.
- **Push, not poll**: the panel is animating this, and a file it had to re-read
  on a timer would be both later and more work.
- Only the three fields the drawer draws are sent. The panel has no library and
  no art cache; anything else would be bytes per queue change for nothing.
- A stale socket from a crash is removed before `listen()` — two players never
  run at once (the second dies on the library lock long before this).
- **Every failure is caught and printed.** A queue drawer is a convenience and
  must never be able to take the music player down; the same rule `start_mpris`
  already follows.

### `LYRICS` is a subscription, and that is the whole design

The panel's queue drawer now grows a lyrics box on the right when the playing
track has words (`docs/DESIGN.md` §5.4), and this socket is the only channel there
is: MPRIS has no lyrics field, and `LyricsProvider` lives in this process.

- **Opt-in, per connection.** Resolving is not free — tag reads, an LRCLIB
  request, and (with `lyricsEmbed` on, the default) a writeback into the file.
  Doing it for every track the user plays merely because the panel exists would
  turn a widget nobody has opened into a library-wide sweep, which is what
  `tools/lyrics-sync.py` is for. So nothing is resolved until a client says
  `LYRICS 1`, and the panel only says it while its drawer is actually open.
- **The payload is per CONNECTION, because the subscription is.** `snapshot()`
  takes a `with_lyrics` flag and `push()` builds at most two lines. It read the
  `want` set as a global "is anybody listening" first, so one subscriber turned
  lyrics on for every other client — including a panel predating this protocol,
  handed a few KB of words it has no field for on every push.
- **`lyr_tid` is a join key, not a cache tag.** A resolve is asynchronous, so by
  the time one lands the user may have skipped — and a payload sent under the
  wrong track is the panel confidently scrolling another song's words. Nothing
  is ever emitted unless the cached id still equals what is playing, and a
  track change clears the payload *before* the push that announces it.
- **Whole lines, once per track; the panel does the following.** It has the
  MPRIS position already, so pushing a current-line index would only add socket
  latency to something the other side can compute exactly.
- **`none` / `instrumental` are sent as a payload with no words in it**, which
  is how the panel knows to collapse the column rather than draw an empty box.
  It has no "mark instrumental" control — that needs the library.

```bash
tools/queue-lyrics-test.py     # headless; isolated XDG_RUNTIME_DIR, fake
                               # Player + LyricsProvider, so the LIVE player's
                               # socket is never touched.
```

## Lyrics + ReplayGain (2026-07-25)

`lyrics.py` is a Qt-free module shared by the app and `tools/lyrics-sync.py`:
LRC parse, embedded read/write (LRC text in USLT / `LYRICS` / `©lyr` — *not* ID3
`SYLT`, which nothing reads), and a strict LRCLIB client. Resolution is
**timestamped-first**: embedded synced → sidecar `.lrc` → LRCLIB, and a plain
unsynced tag never ends the search (≈18% of this library has plain words sitting
in its tags, which used to block the lookup permanently). Fetched synced lyrics
are **written back into the file** (pref `lyricsEmbed`, default on; journaled to
`tagwrites.log`).

Two rules learned the hard way here:

1. **Matching must be STRICT because this writes to files.** NetEase's search
   always returns a top hit and was observed matching "Wu-Lu — Run Away Dream"
   to an unrelated Chinese pop song, so it is deliberately NOT used as a
   fallback.
2. **There are THREE negative verdicts, not one**, because "this track has no
   words" and "nobody has indexed them" are different claims and only the first
   is knowable: `instrumental` (LRCLIB's flag — permanent, pane collapses),
   `instrumental-user` (marked by hand from the pane — permanent and undoable),
   and `none` (undetermined — retried on a widening backoff, 7/14/28…180d, via
   `lyrics.attempts`).

**Do not try to infer instrumental from titles or genre**: an audit found only
163 of 11k titles carry any marker, catching 11 of the first 770 misses, and
`Intro`/`Interlude`/`skit` often *do* have lyrics. The miss pile really is mixed
— wordless ambient sits next to vocal tracks too obscure to index (Coaltar of
the Deepers, Astrid Sonne) — so the only thing that could settle the rest is
analysing the audio for singing, which is deliberately NOT built. Title/artist
normalisation (`(Monopoly mix)`, `(ft. X)`, `prod. Y`) lifted the sample hit
rate 42%→60%.

`tools/lyrics-sync.py` sweeps the library: dry run by default, `--write` to
embed, `--embed-cached` to do the file writes with no network. The split exists
because looking up 11k tracks is harmless while music plays, whereas rewriting
tags under the running player is not — the tool refuses `--write` if `main.py`
is up.

**ReplayGain**: the scan mirrors `REPLAYGAIN_*`/`R128_*` (all three tag
families; MP4 freeform names must be matched case-insensitively — some files say
`com.apple.itunes`) into `tracks.rg_*` columns, and **mpv applies the gain
itself** (`replaygain`/`-preamp`/`-fallback`/`-clip`), independent of the volume
slider — verified empirically at −6.3 dB measured vs −6.32 dB tagged. ~93.5% of
the library is already tagged; untagged files use the library's **median** gain
rather than a made-up constant.

The untagged remainder is filled in by `tools/replaygain.py`: it runs the
packaged `rsgain` (an EBU-R128 / ReplayGain 2.0 scanner, on PATH) in scan-only
mode to *compute* each track's gain+peak, then **writes the tags itself through
`atomicsave`** — copy-then-replace, never in place, the same path every other
write into aud/ takes, so a run that dies halfway cannot leave a truncated file
on exFAT. Dry run is the default; `--write` applies. It writes both track and
album gain (album-grouped by directory, so album-mode playback keeps an album's
intended contrast). Formats `rsgain` cannot tag — DSF/DMF/MPC/TTA, listed once
as `RG_UNSUPPORTED_EXTS` in main.py — are skipped and stay on the median
fallback. `AutoScanner` runs it as a child after every rescan
(`scan --write --auto`; idempotent, failures remembered in
`~/.local/state/player/replaygain-auto.json`), so **any track that lands in the
library — a Soulseek download via player-add.py or a file dropped straight into
aud/ — is normalized automatically**, no manual step. Harness:
`tools/replaygain-test.py` (28 checks, offscreen, on scratch copies; the live
library and running player are never touched).

NB when integrity-checking tag writes: `ffmpeg -i f -f md5 -` is
**nondeterministic** on files with embedded cover art — hash audio only
(`-map 0:a -f s16le - | md5sum`).

## Sharing the library with `air` (2026-07-25)

`air` has ~12 GB free and the library is 208 GB, so it is never copied —
`sys/net/share.nix` serves `/run/media/lam/SSD/aud` over SMB (samba, not NFS:
exFAT has no `export_operations` for nfsd) plus avahi (`top.local`) and
keys-only sshd, every port scoped to `enp12s0`; `sys/disks.nix` declares the SSD
so it is up before a session is. Off-LAN, `sys/net/tailscale.nix` joins top to a
tailnet — samba's hosts-allow includes the CGNAT range and `--operator=lam` lets
agents drive it without sudo. **`tailscale0` is deliberately NOT a trusted
interface**: exactly two ports are opened on it, and the header comment in
`sys/net/tailscale.nix` says which and why (an earlier `trustedInterfaces` entry
published every listener on the box). Do not restate the port list here — read
it there, and treat adding to it as a security decision. Book's daemon is
dnf-installed Fedora state, not managed here. `air-launch.sh` probes
`top.local` first, then the MagicDNS name `top`, so the player's metadata sync
follows book onto any network.

**The one invariant everything rests on: `air` mounts the share at the SAME
absolute path**, which makes `top`'s database valid there verbatim — no path
rewriting, no rescan (measured: mtime passes through exFAT-over-SMB3 byte-exact
for all 11 099 tracks).

**A mounted share is not a working share, and the launcher REPAIRS rather than
reports.** The recurring "player won't open on book" is a cifs mount that is
active per systemd and present in `/proc/mounts` while every access returns
`ESTALE` — the SMB session died under a suspend or a network change, and the
automount never re-fires because as far as systemd is concerned the unit is
already up. `air-launch.sh`'s `share_ok`/`share_heal` therefore probe the path
and, on any failure, `systemctl restart` the fstab-generated `.mount` unit
(`systemd-escape -p --suffix=mount`; needs no root and no polkit prompt on
book) before re-probing. Only a share still dead after that is fatal. Apply the
same rule to any precondition added here: **if the launcher can restore it,
restoring it is the behaviour — a `die_ui` is for what it cannot fix.**

**The scanner never holds a SQLite write transaction across a file read.** On
`air`, one tag read crosses SMB; batching 200 `execute()` calls while parsing
the next file held SQLite's sole writer slot for minutes and made ratings,
favourites, play counts and lyrics fail with `database is locked`. Parse a
batch completely first, then land it with one local `executemany()` + commit.
`tools/scanner-lock-test.py` puts slow fake files behind that boundary and
requires a foreground write with a 50 ms timeout to succeed during the scan.

Metadata is reconciled by `tools/dbsync.py` (`pull`/`push`/`sync`/`status`),
keyed on `tracks.path` and never on `id`, stdlib-only so it runs under Fedora's
python, and its own remote agent — it pipes ITSELF to `python3 -` over ssh. It
never deletes, and a first pull **seeds** rather than merges (a locally-scanned
db renumbers the rowids that `prefs.json`'s saved queue is made of). Two traps:
snapshot with sqlite's `backup`, never `cp` (WAL); and `MIGRATIONS` entries are
`(table, col, decl, rescan)` — adding a `tracks` column with `rescan=True`
clears the mtime cache and forces an 11k-file re-read, which over SMB is brutal,
so a column the APP writes (`meta_mtime`) must set it False.

Full plan, runbook and STATUS: `docs/agents/air-library-share.md` — **both parts
are done and verified** (Part B on `book`, 2026-07-26). That doc's STATUS block
is authoritative; this paragraph is not.

## Spotify export → what's missing locally (2026-07-25)

`tools/spotify-dump.py` exports the account's Spotify library (Authorization
Code + **PKCE**, so no client secret exists to leak; token cached 0600 in
`~/.local/state/spotify-dump/`, client id kept out of this public tree) and
`tools/spotify-missing.py` diffs it against `library.db` into
matched/suspect/**missing** TSVs — the last being the work list for finding
copies elsewhere. Both stdlib-only, same reason as `dbsync.py`.

**Saved albums expand into the work list.** The dump writes each saved album's
tracks into `saved_albums[].tracks`, and `spotify-missing.py` folds them into
the missing list alongside saved/liked and playlist tracks — so saving an album
counts as wanting its missing tracks downloaded. The expansion lives in the
dump, so **`tools/spotify-dump.py` must be re-run to regenerate the dump** (and
then `spotify-missing.py`) for the album tracks to reach `missing.tsv`; the
album-origin rows appear under the album name in the `sources` column.

`tools/soulseek-missing.py` acts on that work list: for each `missing.tsv` row
still **not** in the live `library.db`, it submits one slskd search over the
loopback HTTP API (key from `~/.secrets/slskd-api-key`, pinned in
`home/prog/slskd.nix`), matches a peer's offered file by the same
`trackmatch` artist/title folding + a duration check, and queues the download.
Stdlib-only, so it needs no runtime dependency and runs on both hosts; it keeps
a per-dump-dir `soulseek-state.tsv` so re-runs never re-search or re-download
what is already handled (an `error` row, a transient failure, is **retried** on
a later run — only `nofind` is terminal), and `--dry-run` shows picks without
enqueueing. It requires slskd to be **running and logged in** — which the
generated `slskd.yml` alone does not provide (see `home/prog/slskd.nix`).

The sweep itself has no concurrency to tune: slskd rejects concurrent searches
outright (HTTP 429 "Only one concurrent operation is permitted"), so it must
search one track at a time and the batch size (`--limit`, default 40; `--all`
for everything) is the real lever on download throughput. The parallel transfer
is slskd's (`global.download.slots`, pinned to 50); feeding it a real batch
across distinct peers is what turns "one download at a time" into several in
parallel.

**Each run fans the batch out across distinct peers.** slskd serializes
downloads from one peer over a single connection (the Soulseek protocol grants
one upload slot per user), so a run that piled every match onto the same peer —
common when an album/single-artist set lives on one user's share — lined them
all up behind that one slot and read as "only one transfer at a time" however
high `global.download.slots` was. `pick_candidate` therefore de-prioritizes a
peer a run has already enqueued `MAX_ENQUEUES_PER_PEER` (2) files to, and
prefers a peer advertising a free upload slot on the tiebreak. Both biases
break ties only — a file offered solely by an already-loaded/busy peer is still
enqueued there rather than refused.

Each run also **re-sources downloads that ended failed** — slskd's
`Completed, Rejected` (and `Cancelled`/`TimedOut`/`Errored`/`Aborted`) states,
where a peer accepted the request then refused the transfer, so the track
never lands in the library yet the state file keeps it `queued`. It reads
`/transfers/downloads`, matches each failed transfer back to its missing track
(by the same artist/title folding the search uses), drops that track's
`queued` marker so the normal pass re-searches it, and blocks the refusing
peer from the pick so the re-source lands on a different source. Each failed
transfer's id is remembered in a per-dump-dir `soulseek-rescued.json` — only
once a matching queued track was actually re-sourced — so a rejection lingering
in slskd's list is only ever acted on when there is something to do (not on
every poll, and never while the track is in a nofind/error state that would
leave the id burned with nothing re-sourced). Transfers that ended in a failed
terminal state are also excluded from the never-re-queue guard, so a re-sourced
track is not re-marked "queued" pointing at the dead transfer; they only guard
the re-queue while they might still produce a file. This is also what actually
populates the never-re-queue guard: the `/transfers/downloads` response nests
as username → directories → files, and the guard was previously walking only
the top level and matching nothing.

**Every errored/failed download is then cleared from slskd itself.** slskd keeps
completed/failed transfers until explicitly removed, so a re-sourced track left
a dead errored row accumulating in the downloads view forever. `clear_handled_failures()`
DELETE-cleans **every** failed-terminal transfer from `/transfers/downloads` —
pure cleanup of a row that can never produce a file: the re-source (not the
lingering row) is what recovers the track. It runs after the rescue pass, so the
same run has already seen the failures it needed to re-source before removing
the rows. Two traps, both paid for: slskd's `DELETE downloads/{username}/{id}`
only removes the row from the store (which the webapp reads) when
`?remove=true` is passed — a bare DELETE merely "cancels" an already-failed
transfer (a no-op) and the row stays visible; and clearing must not be gated on
`soulseek-rescued.json`, or a failure whose track is nofind/error (never
queued, so never rescued) accumulates in the downloads view forever.

**A "queued" marker whose transfer has vanished is re-queued, not forgot.**
slskd keeps its transfer list in memory, so a daemon restart — or a failed
transfer `rescue_rejected` could not act on before `clear_handled_failures`
removed it — leaves the track marked `queued` in `soulseek-state.tsv` with no
transfer and no file. `wanted()` would then skip it forever. `reconcile_orphaned_queued()`
drops exactly those markers so the normal pass re-searches and re-queues the
track: it must still be on the work list, must not be in the live library, must
have no live transfer, and must not have a completed file sitting in the
downloads dir (Soulseek peer paths use backslashes, so the basename is matched
after normalising separators — a completed-but-unimported file is a real file
that must not be re-downloaded). A live transfer, a landed file or a landed
library row always keeps its marker.

slskd drops completed downloads into `~/.local/share/slskd/downloads/`, and the
player only ever sees a track once it is moved into `aud/` and rescanned. The
pipeline's last step (`tools/player-add.py`, run automatically by
soulseek-missing.py unless `--no-import`) closes that gap: it moves each
completed download into `aud/<Artist>/<Album>/` following the library's folder
convention, fills missing tags from the pipeline's own record (a Soulseek file
can arrive bare — the 0181 mp3 had no artist/title), and does an incremental
rescan of `library.db`. Because the scan is tag-driven, the DB row comes from
the file's own tags; a file whose tags arrive empty is only metadata-correct
once the importer tags it from the pipeline's own record of what was queued.

**Placement is by the pipeline's album record, not by the Soulseek file's
tags.** soulseek-missing.py records the album identity of every queued download
(album_artist, album, album_ref — the MusicBrainz release id / Spotify album
id the album-missing inventory worked from) into `soulseek-state.tsv` at
enqueue time. player-add.py places a download matched to that record into ITS
album: the destination is the folder the library already groups the album
under (live-DB folded album_artist+album, then the MB ref via the audit
tagscan, then a shared-artist-token match), or a fresh
`aud/<AlbumArtist>/<Album>/` per the convention when the album has no files
yet; the file's album/album_artist tags are written to match that folder (the
player groups by TAG, not folder — a track whose Soulseek tags name a
different album would otherwise be invisible in the album it was downloaded
for), and title/artist are filled only when the file is bare. A completed
download that matches no pipeline record and has no usable tags is parked in
`downloads/needs-attention/` and reported — never silently dropped into
`aud/Unknown Artist/Unknown Album`. `player-add.py` runs under the **player's**
python env (it reuses `main.py`'s `read_tags`/`open_db`/`rebuild_albums`),
which soulseek-missing.py resolves from the `player` wrapper; it writes the DB
out-of-process in WAL (busy-timeout 60s) like `tools/dbsync.py`, and never
touches the running player's session.

**Automatic pickup (`main.py`'s `AutoScanner`).** Both feeds into the library
are watched by the app now, so a freshly downloaded track reaches "recently
added" with no manual Rescan:

- the **downloads dir** — on change (debounced 3s) the app runs `player-add.py`
  as a child of itself (`sys.executable`, the player's python env) to move/tag
  new downloads into `aud/` and rescan, then re-scans in-process so the open
  smart playlist refreshes. A startup pass imports anything already sitting in
  `downloads/`. One import runs at a time; a change while one is in flight is
  debounced and picked up next.
- the **library root** — on change (debounced 2s) a rescan picks up files
  dropped straight into `aud/` (a manual copy, a ripper).

Both converge on `Library.rescan()`, whose `changed` signal re-opens the open
smart playlist — that is what makes the track appear in "recently added"
without the button. `AutoScanner` is inert on `air` (no slskd dir) and wherever
`aud/` is unmounted, and the dirs are re-watched every 30s so a remount or a
first slskd launch is picked up. It never reimplements the move/tag logic — it
runs the tool.

Three things worth knowing before touching them:

1. **`GET /playlists/{id}/tracks` no longer exists** — Spotify's Feb–Mar 2026
   migration replaced it with `/playlists/{id}/items` and renamed each entry's
   `track` key to `item`; the old path 403s unconditionally and `/me/playlists`
   reports `tracks:null`, so there is no fallback.
2. A **Development-mode** app gets playlist *contents* only for playlists the
   user created or collaborates on (14 of 92 here are other people's, metadata
   only), so a per-playlist 403 is normal and must never abort the run.
3. The local db has **no ISRC column**, so the diff cannot use the ISRCs the
   dump collects — matching is normalised artist+title with duration as a signal
   that *flags* (`suspect.tsv`) rather than rejects. Adding `isrc` to the scan
   would mean a `MIGRATIONS` entry with `rescan=True`, i.e. a full 11k-file
   re-read.

## `../pylib/trackmatch.py` owns artist/title normalisation

It was extracted from `lyrics.py`, which imports `mutagen` and therefore cannot
be imported by anything running under a bare `python3`. `lyrics.py` imports it
back under its historical private names (`_fold`, `_title_matches`, …), so
behaviour there is unchanged. **Any new "are these two tag strings the same
song?" code must use this module** rather than grow a second copy — the
decoration stripping is what took the LRCLIB hit rate from 42% to 60%, and a
drifting duplicate would silently regress that.

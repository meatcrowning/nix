# `apps/` — the vendored desktop apps

Twelve standalone Qt/QML apps that ship with this config, plus the shared Python
helpers they all import. Each has its own `AGENTS.md` with the detail:

**Read `~/nix/docs/DESIGN.md` before you draw anything in here.** These apps are not
eleven programs that happen to share a repo — they are one desktop, alongside the
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
| [`slsk/`](slsk/AGENTS.md) | Soulseek search + downloads over the local slskd daemon | `home/prog/slsk.nix` |
| [`updater/`](updater/AGENTS.md) | GUI for this flake's package (input) updates | `home/prog/updater.nix` |
| [`oracle/`](oracle/AGENTS.md) | minimal chat window for the local ollama daemon | `home/prog/oracle.nix` |
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

**painter, goetia and updater are the deliberate none.** painter has no
open-a-file path at all, goetia is a GUI over one fixed file, and updater is a
GUI over the flake — so none declares a `MimeType=` and none appears in
`mime-defaults.nix`. An app with no honest file type gets no association.

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

## The live-source pattern — all eleven work this way

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
  - **It runs the other way too, and filer listens as well as sends.** filer
    opens viewer with `--select-back <sock>:<pane>`; viewer echoes each image it
    flips to at that socket and filer selects it, so closing the viewer leaves
    the browser on the picture you stopped at. filer's socket is `filer-<pid>`,
    per process and per pane key, because two filer windows are two processes
    and an echo landing in the wrong one moves a selection nobody is looking at.
    See `filer/AGENTS.md` → "Flipping in viewer moves filer's selection".
  - Harnesses: `apps/pylib/tools/handoff-test.py` (the transport, both halves),
    `apps/viewer/tools/handoff-test.py` (what viewer does with a request —
    the exposure refusal, `--order`, caller-relative paths),
    `apps/viewer/tools/select-back-test.py` and
    `apps/filer/tools/viewer-select-test.py` (the return leg, viewer's half and
    filer's — the latter drives viewer's real client against filer's real
    listener).

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
- **`pngmeta.py`** — the PNG tEXt/zTXt/iTXt reader and writer, stdlib only. Two
  callers by design: painter WRITES the `painter` chunk holding a generation's
  exact parameters, and filer's `Ctrl+F` READS that chunk plus whatever ComfyUI
  (`prompt`, `workflow`) and cte (`cte_*`) left in the same place. It lived in
  `painter/` until 2026-08-12; a second parser for the same bytes is the thing
  to avoid. `read_text_path()` is the cheap route — it never touches the pixels;
  see `filer/AGENTS.md` for what that costs and why the tail fallback exists.
- **`mp4meta.py`** — the same job for the other half of painter's gallery: the
  `mdta` metadata tags in an MP4's `moov/udta/meta`, where ComfyUI's `SaveVideo`
  already writes its `prompt` graph and where painter now writes its own
  `painter` key beside it, so a CLIP carries the job that made it exactly as a
  still does. Stdlib only, and no ffmpeg: it runs in the download callback on
  the GUI thread. **Growing `moov` moves the media data**, so `upsert_tags`
  patches every `stco`/`co64` chunk offset past it — a writer that skips that
  step leaves a file whose pictures decode to nothing.
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
- **`kdetheme.py`** — **THE session switch. In a Plasma session these apps draw
  the KDE global theme, not the wallpaper palette**, his call 2026-08-18: Plasma
  is a real alternative session here (`sys/dsk/plasma.nix`) and in it the look
  belongs to whatever global theme System Settings holds, which every other Qt
  app on the box already obeys through `kdeglobals`. An app still drawing the
  wal palette there is the one window that ignores the theme.
    - **It changes the SOURCE and nothing else.** Every app's `Palette` already
      parses `property color <name>: "#rrggbb"` out of a file and watches it;
      under Plasma this module derives the same twelve tokens from `kdeglobals`
      and writes them into a generated file of exactly that shape
      (`~/.cache/deskstyle/kde-Theme.qml`), rewritten whenever the scheme
      changes. So the per-app change is one call —
      `Palette(theme_source(PANEL_THEME))` — and no `Theme.qml`, binding or
      component knows which session it is in. Do it that way for a new app.
    - **`kde_chrome()` is the exception to "the source and nothing else"**, for
      the one caller that cannot hand the painting back to the style: surfer's
      OneeChan 4chan re-skin, a web page no QStyle will ever draw. It returns
      the KStyle's gradient stops and relief tones (each `kdeglobals` group
      background shaded either side along HLS lightness, scaled by `[KDE]
      contrast`) so that sheet can imitate an Oxygen window; it is None outside
      a Plasma session and under a flat KStyle (`GRADIENT_STYLES`), so no other
      app and neither the Hyprland look ever sees a gradient because of it.
    - **`pylib/chantheme.py` + `pylib/tools/chan-userscript.py` — the same
      look, in a browser that is not ours.** OneeChan themes 4chan from its own
      baked hexes; `chantheme.css()` builds an override sheet with OneeChan's
      selectors + `!important` that wins purely on cascade order (an adopted
      stylesheet follows any document `<style>`), plus the KStyle relief above
      when `kde_chrome()` gives one. surfer adopts it live over
      `surferonee://`; **Vivaldi** has no Stylus and only Tampermonkey (where
      OneeChan already lives), so the generator BAKES the same bytes into a
      userscript — `chan-theme` (wrapper: `home/prog/chan-theme.nix`) writes
      `~/.local/share/chan-theme/desktop-4chan.user.js`, and he opens that
      `file://` URL to install. Baked means stale by design: **re-run
      `chan-theme` after a colour-scheme or wallpaper change.** That is why
      `chantheme` is Qt-free — the generator runs with no Qt, no browser and no
      app. Harness `pylib/tools/chan-userscript-test.py`, whose real job is the
      seam: the baked CSS must equal what surfer serves for the same palette.
    - `deskstyle.py` asks it for `fontFamily`/`fontSize` (KDE's point size,
      converted at the screen's own DPI), `smooth`, the motion factor and the
      scrollbar in that session. The two GEOMETRY keys do not move: border
      width and corner rounding stay the panel's, because KDE publishes no
      equivalent and a window that changed shape between sessions would be the
      surprise.
    - **`accent` and the status four are contrast-guarded.** §3 makes `accent`
      body text while KDE's `DecorationFocus` is designed to be seen as a
      frame, and Oxygen's `ForegroundPositive` (0,109,56) is unreadable on its
      own window background. Both polarities, since a KDE scheme may be either.
    - `DESK_SESSION=plasma|hypr` forces the branch and `DESK_KDEGLOBALS` points
      at another scheme file — that is how the harness renders both looks
      without logging out. Harness: `apps/pylib/tools/kdetheme-test.py` (needs
      an app wrapper's python; the bare `python3` here has no PySide6).
    - **`is_plasma()` is also the menubar's switch**, published to QML as
      `DeskStyle.plasma`: with no hyprvtb in that session the apps' titlebar
      button column is redrawn as a menubar (`qmlcommon/DeskMenuBar.qml`,
      below).
    - The other half of the same rule is `home/prog/mime-defaults.nix`: in a
      Plasma session the file-type defaults are KDE's apps
      (`kde-mimeapps.list`), and `wal-set.sh` leaves `kdeglobals` alone there
      rather than overwriting his colour scheme from the wallpaper.
- **`oxygenstyle.py`** — **the WIDGET STYLE's own store, `~/.config/oxygenrc`,
  for the numbers `kdeglobals` does not carry.** A colour scheme says nothing
  about how wide a scrollbar is, how long a hover fade lasts, how big a tree
  expander's triangle is or whether a tooltip is translucent — the style does,
  and under Oxygen it keeps them in a file of its own. Every real QWidget in one
  of our Plasma windows already obeys it; the QML inside the `QQuickWidget`
  (`apps/*/qml/+plasma/*.qml`) is the half that did not, and a hand-drawn
  control fading at 260ms beside a QToolButton fading at 150 is the same "one
  odd window" failure `kdeshell.py` exists to prevent, one level down.
    - **The defaults table is upstream's, verbatim** (`kstyle/oxygen.kcfg` in
      `github.com/KDE/oxygen`, 6.7.4). A key absent from the rc is not unset, it
      is the compiled-in default — and on a machine that never opened the KCM
      that is nearly all of them, so reading the file alone would have answered
      "nothing" to almost every question. Two numbers are DERIVED the way
      Oxygen's own source derives them (the scrollbar button height
      `qMax(w*7/10, 14)`, the expander triangle's drawn width and pen), because
      they are not in the rc at all.
    - **The gate is Plasma AND Oxygen** (`is_oxygen()`): outside Plasma none of
      it applies, and inside it under Breeze the Oxygen rc still exists on disk
      and would dress our QML in the metrics of a style the window is not
      wearing.
    - **`DeskStyle` is what publishes it** — the `style*` properties, on the
      same watch as everything else, all inert (0 / false / "") whenever no
      style is saying. Every consumer treats that as "use the desktop's own
      value", so none of them knows what session it is in. Two consume it so
      far: `qmlcommon/Motion.qml` takes `styleMs` (Oxygen's
      `GenericAnimationsDuration`, 150) over hyprvtb's 260 slide in a Plasma
      session — there is no window roll there to match — and `qmlcommon/VScroll.qml`
      takes `styleScrollWidth` for its gutter. **Adding one is a row in
      `oxygenstyle._KEYS` and a Property in `deskstyle.py`**, nothing more.
    - Oxygen's `AnimationsEnabled=false` arrives as `reduceMotion`, not as a
      silent ignore: a window whose real widgets have stopped animating must
      not have QML still sliding inside it.
    - **`home/prog/oxygen.nix` declares the half of that file this desktop
      pins** — and deliberately not the durations or the metrics, which are the
      numbers the apps READ. `oxygen-settings6` (already on PATH, from
      `kdePackages.oxygen`) is the GUI that writes the rest; `oxygen-demo6`
      beside it is upstream's gallery of every Oxygen widget in every state,
      which is the reference to diff a `+plasma` component against.
    - `DESK_OXYGENRC` points at another rc. Harness:
      `apps/pylib/tools/oxygen-test.py`.
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
- **`imgfit.py`** — **THE "get this under N bytes" search.** Quality before
  resolution (a binary search over JPEG quality at each resolution rung, the
  next rung only when even `Q_MIN` will not fit), measured by encoding into a
  `QBuffer` rather than by writing and stat-ing, JPEG unless the alpha is
  *really* used — `hasAlphaChannel()` says yes for almost every PNG, so it is
  sampled. It was filer's `imgconv.py` until painter needed the same budget for
  the collage it hands to a drag; filer keeps the part that is filer's (naming
  the copy beside the original, the toast, the menu's QObject). **Importing it
  raises Qt's 256 MB decode ceiling process-wide** — deliberate, and also what
  gives filer's thumbnailer preview tiles for very large PNGs. Harnesses:
  `filer/tools/imgconv-test.py` (the search, ~21 checks over real noise) and
  painter's `ui-test.py` → `test_selection_and_collage`.
- **`kitty-vtb.py`** — kitty's vtb integration, run from the live repo, stdlib
  only.
- **`clipfile.py`** — **THE way to put a FILE on the clipboard here.** Run as a
  program (`python3 clipfile.py [--image] FILE…`), not imported: it forks and
  stays alive as the selection's owner, because a Wayland selection dies with
  the process that offered it. Exit 0 means the clipboard is ours; the holder
  lets go when something else takes it.
    - **`--image` ADDS the picture; it never replaces the file offer.** viewer's
      "copy image" passes it: the file's own bytes go on as `image/png` (or
      whatever its extension says) *after* the two file types, so an editor
      that only understands pixels gets them while everything that understands
      a file paste keeps the filename it has always had — painter's copy is
      byte-for-byte unchanged, and the harness asserts that. There is no
      conversion, because this file is stdlib-only: a JPEG is offered as
      `image/jpeg`, and a consumer that insists on `image/png` falls back to
      the file rather than being handed a lie. Ignored for a multi-file copy
      (two images cannot both be *the* image on the clipboard) and above
      `IMAGE_MAX`, the holder keeping every payload resident.
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

### `CtxMenu.qml` — a menu row acts on a box that still has the keyboard

Not in `qmlcommon/`: filer, player, reader, editor, board, painter and viewer
each hold a **verbatim copy**, and surfer holds the ancestor as
`ContextMenu.qml`. Retune all eight or none. `SelectButton.qml` — the dropdown
face every enum pick wears (docs/DESIGN.md §7.2) — is under the same rule:
player and filer each hold a verbatim copy.

The reason given here for that used to be *"it needs `PixelText`, which a shared
component cannot reach"*, and **that half is no longer true**:
`qmlcommon/PixelText.qml` exists since `DeskMenuBar` needed the same type
(below). Folding these eight copies into one is now a possible job, not an
impossible one — it is simply not done, and doing it is a change of its own.

**Opening the menu takes the active focus** — that is how Escape and the
outside-click scrim reach its sink — so it remembers the item it took the focus
from (`Window.activeFocusItem`) and gives it back in `close()`, *before* the
chosen row's `trigger` runs. A trigger that wants the focus elsewhere (an inline
rename, a dialog) still wins, by running last.

Two things a text box must do to survive that round trip, both landed in
painter's `PromptBox` on 2026-08-07 after `select all` in a prompt box left the
text drawn selected and Backspace doing nothing:

- **`persistentSelection: true` on the editor.** A `TextEdit` drops its
  selection the moment it loses active focus, so `cut`/`copy` rows were offered
  from the selection as it stood at the right-click and then ran against
  nothing.
- **`forceActiveFocus()` on the right-press**, in the same MouseArea that raises
  the menu. A right-click is how a box that was never clicked into gets a menu,
  and without this the keyboard is handed back to wherever it actually was.

### `DeskMenuBar.qml` — the inner titlebar, as a menubar, under Plasma

**In a Plasma session an app's titlebar button column comes back as a menubar
across the top of its window.** There is no hyprvtb in that session, so
`Titlebar.setButtons` reaches nothing and every verb on that column — filer's
file operations, player's transport, surfer's tabs — is simply absent. It is the
same call `kdetheme.py` already makes for the palette (the session owns the look
and its conventions), carried from colour to chrome.

Wiring an app is three things, and the ninth app should look exactly like the
other eight:

```qml
DeskMenuBar {
    id: menuBar
    anchors { top: parent.top; left: parent.left; right: parent.right }
    buttons: win.tbButtons                 // the SAME array the titlebar gets
    menuOrder: ["file", "edit", "go", "view"]
    onTriggered: (id) => win.tbAction(id)
}
```

1. **`tbButtons` gains a `menu:` on each entry** — the top-level menu it belongs
   to. `menuSep: true` asks for a divider above an entry *in the menu only*
   (filer's column carries no `"-"` spacers at all, and `move to trash` still has
   to sit behind one — §10.3). Both are **inert on the wire**: `vtbclient.py`
   reads `id/label/state/tip/drag/bottom` and ignores everything else, so
   annotating the array costs the titlebar nothing. An entry with no `menu:`
   lands in `defaultMenu`; `menuOrder` names the bar's left-to-right order,
   which is not the column's order.
2. **The click handler becomes a function**, `win.tbAction(id)`, called both by
   `Connections { target: Titlebar }` and by the menubar. ONE switch, two
   chromes — the point being that the two can never drift apart, since both are
   driven by the same ids and the same `state`.
3. **The window's content anchors to `menuBar.bottom`** instead of to the top
   (and anything positioned with raw `y`/`height` off the window — filer's and
   painter's panes, board's find bar, surfer's permission bar — offsets by
   `menuBar.height`). Outside a Plasma session that height is **0** and the bar
   is invisible, so the Hyprland layout is byte-for-byte what it was.

A row's label is the button's **tooltip** ("sort by name"), since the
two-character cell is a titlebar affordance and a menu is where the full verb
belongs; `state` 1 lights the row (a `*` in a reserved gutter, `accent` text) and
`state` 2 greys it rather than dropping it. The look is §7.2's menu spec,
unchanged.

Two traps it already paid for, both measured in `pylib/tools/menubar-test.py`:
the dropdown is **re-parented to the top of the item tree**, because an item
outside its parent's bounds renders but never receives a click — a popup hung
off a 23px bar is visible and dead; and the row's `onClicked` calls
`root.choose(id)` rather than closing and emitting inline, because closing
destroys the delegate that is mid-click and the rest of that handler is then
abandoned **silently**.

The session flag is `DeskStyle.plasma` (from `kdetheme.is_plasma()`), so
`DESK_SESSION=plasma|hypr` moves the whole thing for a harness. **Any harness
that asserts window-relative geometry should pin it** — `filer/tools/split-test.py`
asserts full-window panes and needs `DESK_SESSION=hypr` when it is run from
inside a Plasma session.

`qmlcommon/PixelText.qml` exists for this component: a file component here
cannot reach an app's own copy. It is byte-identical to the eight app copies —
retune all of them together (docs/DESIGN.md §2.2).

**An app with the KDE shell below stands this bar down** — `systemBar: true`,
and `shown` goes false while `plasma` stays true. Two menubars, one of them
ours and wrong, is what that flag prevents. painter and player both do; the
other apps still use this bar and are unaffected.

### `pylib/kdeshell.py` — under Plasma, a REAL KDE window `[painter, player]`

**In that session we do not imitate the system theme; we let the system theme
paint.** `kdetheme.py` moves the palette, the font and the motion to
`kdeglobals`, and that is as far as colour tokens can go — the thing that makes
a KDE program read as one object is Oxygen's window background: a vertical
gradient plus a radial splash, drawn by the *decoration* over the titlebar and
by the *style* over the client area with a matching 23px y-shift, so the
titlebar, the menubar, the toolbar and the sides are one continuous surface.
That is `Helper::renderWindowBackground()`, and copying it into QML would be a
copy that drifts.

Two facts from Oxygen 6.7.4 decide the shape of the answer:

- `kstyle/oxygenstyle.cpp:4595` — that background is painted **only for a real
  QWidget window** (`WA_StyledBackground`, `isWindow()`). No QStyle entry point
  will give it to a `QQuickWindow`, whatever style is set.
- `kstyle/oxygenstyle.cpp:8274` — the style registers any `QQuickItem` it is
  asked to draw for with Oxygen's own `WindowManager`, which is
  drag-the-window-from-any-empty-area (`WD_FULL`, ending in
  `QWindow::startSystemMove()`). So that behaviour comes with the real style
  too, inside the QML, and is not ours to reimplement either.

So the Plasma face is shaped like Dolphin: a `QMainWindow` with a real
`QMenuBar`/`QToolBar`/`QStatusBar`, the app's QML in a `QQuickWidget` central
widget, and `QT_QUICK_CONTROLS_STYLE=org.kde.desktop` so QQC2 controls inside
the QML are rendered *through* the live `QStyle` rather than imitated.

**Never make that QQuickWidget transparent.** Letting the parent show through is
the obvious way to continue the one surface behind the content, and it punches a
hole in the window here — the region stops being repainted, windows dragged over
it leave trails *inside* it, and it is absent from screenshots. Both
`WA_TranslucentBackground` and a bare transparent `clearColor` do it, and
**no offscreen render can catch either**: `grab()` re-renders through a fresh
backing store, the fault is in the live one, and both shipped looking correct.
The view is opaque; `qmlcommon/StyledBackground.qml` draws the style's own
window background inside the QML instead, from an image the style renders into a
proxy `WA_StyledBackground` window and crops to the view's rectangle
(pixel-exact against a real window, 0.76 ms). Put it at the back of the app's
root item; it is invisible in the Hyprland session.

Adopting it in an app's `main.py`:

```python
kdeshell.pin_controls_style()                     # before the app object
app = kdeshell.make_app(sys.argv, "painter")      # QApplication under Plasma
plasma = is_plasma()
shell = kdeshell.shell("painter", size=(1280, 900)) if plasma else None
engine = shell.engine() if plasma else QQmlApplicationEngine()
...
if plasma:
    shell.load(QML / "Root.qml")                  # an Item, not a Window
    shell.bind_chrome(bar, menu_order=[...])      # the same tbButtons array
    shell.bind_status()                           # statusLine/statusProgress
    ctl.window = shell.show()                     # a QWindow, as before
```

and in the QML:

- **the root is split in two** — `Root.qml` is an `Item` with the whole app in
  it, `Main.qml` is the Hyprland session's `Window` wrapper around it. A
  `QQuickWidget` hosts an Item, so anything Window-only (`onClosing`,
  `contentItem`, `activeFocusItem`, assigning `width`) moves out or goes
  through `root.Window.*`.
- **`tbButtons` gains `icon:`** (a freedesktop icon name — a two-character cell
  is a titlebar affordance and has no place on a real toolbar) **and `bar:`**
  (this entry earns a toolbar slot; the menus stay the complete set). Both are
  inert on the vtb wire like `menu:`.
- **`Theme.windowFill`** is `bg` under Hyprland and `transparent` under Plasma:
  anything meaning "the window's background" binds it, or a flat fill covers the
  styled gradient. Insets (`bgAlt` panels, fields, rows) keep real colours.
- **the QML status strip stands down** (`barH: 0`) and the app publishes
  `statusLine` / `statusProgress` (-1 = idle) for the real status bar.

Packaging is half the job and fails **silently** when it is missing: the style,
the QPA theme, qqc2-desktop-style, kirigami and the icon set must be in the
app's own wrapper (`home/prog/painter.nix`), or the window comes up in Fusion
with text-only toolbar rows in a session where everything else is Oxygen.
`kdeshell` re-asserts what it can — `[KDE] widgetStyle` from `kdeglobals`, the
icon theme name, and the icon search paths Qt only fills in from a platform
theme — so a stripped or offscreen environment behaves like the session.

**The menus are KDE's, not the app's.** `MENU_ORDER`/`MENU_TITLE` fix the
vocabulary — File, Edit, View, Go, Bookmarks, Tools, Settings, Help — with File
first and Settings/Help last whatever an app's own `menuOrder` says; a group an
app invents is inserted before Settings. `kdeshell` supplies what the app did
not: Quit at the end of File, Show Toolbar/Show Statusbar in Settings, About and
About Qt in Help. A row's shortcut comes from the action table (`"@Quit"`-style
names take the platform's standard sequence), `group:` makes a radio set, and
one `QAction` per id is reused across rebuilds so a menu row and a toolbar row
can never disagree.

**A row that LEAVES the table takes its chrome with it.** A state flip
(`state`, `checkable`) is applied to the existing `QAction`s in place, because
rebuilding the menubar would close a menu the user has open — but that path
cannot delete a button, so a row an app drops from `actions` (painter's
`compare`, offered only for an edit output) used to leave a live button behind
for a verb that was no longer on offer. `_refresh_now` compares the ids it was
last built from and rebuilds only when that set changed; a cached `barText`
widget whose row has gone is hidden explicitly, since `QToolBar.clear()` drops
the action but leaves the widget parented. Dropping a row is still the
exception — a verb with nothing to act on is normally DISABLED, not absent
(docs/DESIGN.md §10.1).

**`shell.toolbar_search(on_text)`** puts a filter field at the right-hand end of
the toolbar, behind a stretch, where Dolphin/Gwenview/Okular keep theirs. It is
re-appended after every `_rebuild`, since that clears the toolbar.

**The status bar's left slot is a `QStackedWidget`** — the message label on
page 0, the progress bar on page 1 — because two widgets with a stretch each and
one of them hidden do NOT hand the room over: the bar came up in the right-hand
half with the empty label holding the left. A stack is one widget in the layout,
so the whole slot is whichever page is showing. The bar carries its own text
(`statusProgressText`), and a literal `%` in it must be escaped to `%%` or
QProgressBar reads it as its own placeholder.

**Never wire `footerChanged` into `set_status`.** The footer is the hyprvtb
titlebar's badge (painter's is the queue depth, "Q3") and it overwrote whatever
`bind_status` had just put in the status line.

**The status bar is not a titlebar** — and blacklisting the BAR is not enough:
Oxygen's WindowManager looks at the widget under the pointer, and a status bar
is mostly covered by its own labels, so the half under the message label went on
dragging the window. `_no_grab()` sets `_kde_no_window_grab` and installs a
press filter, and every child that fills part of the bar gets it (not the size
grip, which wants its press).



**`toolbar_search`'s `align_right_to`** names a QML property holding the x of a
pane's right edge, and keeps the field's right edge over it with a fixed spacer
after it — painter aligns the filter with the results pane's splitter, since it
filters the outputs and has no business over the parameter column. The
property's own change signal covers window resizing, so nothing watches the
window.

**`use_overlay_toolbar` must be re-asserted after `restoreState()`.** A saved
window state records every toolbar by objectName and re-docks it on restore —
so an overlay toolbar came back full width, over-tall and with its buttons
pushed to the bottom of the band the main window had claimed for it, on the
first relaunch after the state was saved. `show()` re-parents and re-lays it
after restoring; a saved state cannot outvote what the app asked for.
`PAINTER_OVERLAY_CHECK=1` on painter's selftest forces the re-dock and proves
the recovery.

**`barText` on an action row** puts the name beside the icon for ONE toolbar
button — the button style is a toolbar-wide setting, so that row is added as a
`QToolButton` with its own style rather than as an action.

**A dock is a second scene graph.** `QQuickWidget` cannot use the threaded
render loop, so every one of them renders on the GUI thread each frame. Two is
measurably more than one: painter had its parameter column in a dock for a day
and the window felt slower. Reach for `dock()` when the panel genuinely wants
to float or tab, not to get a sidebar.

**Never `QMessageBox.about()`** (nor any of the other static `QMessageBox`
helpers) in this session. They run a nested `exec()` and, with the KDE platform
theme loaded, hand the box to a NATIVE dialog helper whose teardown segfaults
the app — core 127749, 2026-08-22, `~QMessageBox` →
`QDialogPrivate::setNativeDialogVisible` → `QWidget::hide()` on freed memory.
Build a `QMessageBox` with `DontUseNativeDialog`, `show()` it modelessly, and
keep a reference on the shell; `_about_action` is the pattern.

**`shell.toolbar(ident, title, area)` is a SECOND toolbar**, and `bar:` on a
row names which one it goes to — `true` for the main bar, `"transport"` for
player's. KDE's music players keep their transport along the bottom rather than
in the top toolbar, and that is a bar, not a strip an app draws for itself: the
rows on it are the app's own `QAction`s, so the bottom bar, the Playback menu
and the hyprvtb titlebar column cannot disagree. `shell.toolbar_widget(ident,
w, stretch=True)` puts a widget on it — player's seek slider is the one thing
there that cannot be an action. Placement and visibility ride the saved window
state like the main bar's, and each extra bar gets its own Show row in Settings.

**`_clear_bar`, not `QToolBar.clear()`** — and this one was silent and total.
`clear()` deletes a toolbar's actions, and a `QWidgetAction` OWNS the widget it
carries, so every rebuild deleted the search field, the `barText` button and
player's whole seek bar out from under the Python objects still holding them.
Re-adding them afterwards LOOKED like it worked — the actions were back in
`tb.actions()` and `dump_chrome` printed them — but their `actionGeometry`
stayed `(0, 0, 100, 30)`, i.e. never laid out, and nothing was on the bar. It
went unnoticed in painter because a rebuild is rare there; player's
`toolbar()` call triggers one immediately after `toolbar_search()`. A persistent
widget now keeps its ORIGINAL `QWidgetAction` (`_append_widget`) and is put back
with `addAction`, never re-wrapped.

**`shell.bind_title(prop)`** tracks a QML property onto the window title, so the
taskbar entry says what player is playing from the same expression `Main.qml`
binds under Hyprland.

**`shell.guard_typing(widget)`** suspends the bare-key action shortcuts while
that widget has the keyboard. A QAction shortcut is matched BEFORE the key
reaches the focused widget, so player giving Space to play/pause — which it has
done since long before this face existed — made its own search field impossible
to type a space into. Ctrl/Alt sequences are untouched.

**`shell.dock(ident, title, qml, …)`** puts a QML file in a real `QDockWidget`:
float, tab, drag to another edge, a View-menu toggle that is the dock's own
action, and placement saved with the window. Three things it has to get right,
all silent when wrong — the view must share the app's engine
(`QQuickWidget(engine, …)`, or it sees none of the context properties and comes
up blank), it needs its own `KdeBackground` in its own child context (or it
draws the central widget's crop and the gradient steps at the seam), and it is
created with `createWithInitialProperties` so its bindings never run once
against an empty model. `show()` restores geometry + `saveState()`; a harness on
the offscreen platform saves nothing, because a test's window size is not his.

**The content changes clothes through a FILE SELECTOR, not a branch.**
`kdeshell.select_plasma_files(engine)` turns on the `plasma` selector, so
`qml/+plasma/Foo.qml` transparently replaces `qml/Foo.qml` at every call site:
painter's `Panel` is a styled `GroupBox` there, `Spin` a `SpinBox`, `Picker` a
`ComboBox`, `Toggle` a `CheckBox`, `TextButton` a `Button`, and `CtxMenu` /
`ToolTipArea` the style's own popups; player's `HeaderButton` is a flat
`Button`, `SelectButton` a `Button` with the style's indicator, `Slider` a QQC2
`Slider` and `CtxMenu` the style's `Menu` — each with the SAME API as the file it
replaces, so `Root.qml` and every panel are untouched. Each variant carries
`property string face: "plasma"`, which is how a harness proves the swap
actually happened. Two traps paid for already:

- **The selector must be OWNED.** `QQmlFileSelector(engine)` does not parent
  itself to the engine; Python collects it moments later and every component
  then loads its unselected file, silently. Pass the engine twice.
- **A variant may not redeclare a FINAL property** (`GroupBox.title`), and it
  must reproduce the original's *layout contract*, not just its properties —
  painter's `Panel` puts content in a `Column`, and a variant whose content
  item was a plain `Item` drew every row of a panel on top of the others.
- **A QQC2 control that owns its value breaks the CONTROLLED contract.** Our
  sliders and fields are controlled — the parent holds the value and the control
  only emits — but a QQC2 `Slider` writes its own `value` on a drag, which
  destroys a plain binding onto the source. After that the parent writing the
  value back never reaches the handle. player's variant re-applies it through a
  `Binding` object instead, which survives the write.

Verify it the only way this can be verified — by rendering:

```
QT_QPA_PLATFORMTHEME=kde DESK_SESSION=plasma PAINTER_SHOT=/tmp/x.png \
    painter-qtenv python3 main.py --selftest        # then LOOK at the PNG
PAINTER_TREE=panel   # …and/or dump item geometry + the widget palette
```

player's is the same shape (`player-qtenv`, `PLAYER_SHOT`/`PLAYER_TREE`/
`PLAYER_MENUS`/`PLAYER_DIALOG`/`PLAYER_VIEW`), plus **`PLAYER_FACES=1`**, which
walks the item tree and prints every component's `face` — the direct check that
the selector took, rather than inferring it from a render.

**`QT_QPA_PLATFORMTHEME=kde` is not optional in that command.** Without it no
KDE platform theme loads, and the two halves of the window disagree: widgets
take Qt's default light palette while the QML takes his dark scheme, which
renders as an empty-looking toolbar and invisible labels — a bug in the
harness, not in the app. `kdeshell` re-asserts the style, palette and icon
theme when it finds them wrong, so this is belt-and-braces rather than the only
line of defence.

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

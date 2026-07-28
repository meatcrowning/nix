# `apps/` — the vendored desktop apps

Six standalone Qt/QML apps that ship with this config, plus the shared Python
helpers they all import. Each has its own `AGENTS.md` with the detail:

**Read `~/nix/DESIGN.md` before you draw anything in here.** These apps are not
six programs that happen to share a repo — they are one desktop, alongside the
panel and the compositor plugin, and the user's standing requirement is that a
new app or a new feature *looks like the rest without him having to say so*.
Type, palette, spacing, corners, motion timing, titlebar button glyphs, menus,
tooltips, list rows, drop feedback and the honesty-of-controls rule all live in
that one file. It also records where these six have already drifted apart from
each other. This guide owns the *mechanics*; that one owns the *look*.

| dir | what it is | packaged by |
| --- | --- | --- |
| [`filer/`](filer/AGENTS.md) | Qt/QML file browser | `home/prog/filer.nix` |
| [`viewer/`](viewer/AGENTS.md) | image viewer (‹/› through a folder) | `home/prog/viewer.nix` |
| [`player/`](player/AGENTS.md) | tag-driven music player (mpv + MPRIS) | `home/prog/player.nix` |
| [`painter/`](painter/AGENTS.md) | text-to-image front end for headless ComfyUI | `home/prog/painter.nix` |
| [`surfer/`](surfer/AGENTS.md) | QtWebEngine browser | `home/prog/surfer.nix` |
| [`askpass/`](askpass/AGENTS.md) | the `sudo -A` password dialog | `home/prog/askpass.nix` |
| `pylib/` | shared helpers — see below | (imported, not packaged) |
| `qmlcommon/` | shared QML components — see below | (imported, not packaged) |

## They are the system defaults

Three of them are what the rest of the desktop opens things with: **filer** for
`inode/directory`, **viewer** for every image and video type in its
`IMAGE_EXTS`/`VIDEO_EXTS`, **surfer** for `text/html` and `x-scheme-handler/
http(s)` (plus Plasma's separate `kdeglobals` `BrowserApplication` key and
`$BROWSER`).

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

## The live-source pattern — all six work this way

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

## `pylib/` — shared, resolved relatively

Every app does `sys.path.insert(0, str(HERE.parent / "pylib"))`, so the whole
`apps/` tree must move together or none of it does. Tools one level deeper use
`parent.parent.parent`.

- **`vtbclient.py`** — the hyprvtb titlebar-button socket bridge. Every app's
  chrome (transport buttons, close/zoom, view switchers) is drawn by the
  compositor plugin, not by QML, and goes through here.
- **`trackmatch.py`** — the one artist/title normaliser. Any new "are these two
  tag strings the same song?" code must use it rather than grow a second copy;
  see `player/AGENTS.md`.
- **`deskstyle.py`** — the desktop-wide `fontFamily` / `fontSize` plus the two
  motion settings `reduceMotion` / `animSpeed` (see Motion, below), read live
  from the panel's own `~/.config/quickshell/settings.json` (the file
  `SettingsStore` persists). Install it as the `DeskStyle` context property
  BEFORE creating the app's `Theme.qml`, exactly like `WalPalette`, and keep a
  Python reference — every app's `Theme.font`/`fontSize` binds to it, so an app
  that forgets loads its theme with an empty font. Any offscreen harness that
  builds a `Theme.qml` needs it too. It exists because those two used to be
  hardcoded `15` per app, so the Settings font-size slider moved the panel and
  the titlebars and left all six apps behind (DESIGN.md §2.7). Point
  `$DESK_SETTINGS` at another JSON file to render at a non-default size without
  touching the user's live settings — that is how the size is verified
  offscreen.
- **`kitty-vtb.py`** — kitty's vtb integration, run from the live repo, stdlib
  only.

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
`qmlcommon/` is the apps' half of `DESIGN.md` §6.2 — the rule that everything on
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
comment saying why — scrollbar and hover fades stay at 120ms, take the house
curve, and still go through `ms()`. See §6.2.1's non-participants table.

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
is `~/nix/DESIGN.md` §11.1 — *"back and forward mouse buttons should function in
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
  invent one; DESIGN.md §11.1 records the reading for each app and why.
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
- Syntax-check QML headlessly: `qmllint -I <qml import paths> qml/Main.qml`
  (import paths from the app's wrapper env). The "Failed to import" lines are
  missing paths, not errors.
- For app logic, write a headless PySide harness (e.g. pre-grant a permission
  and assert a signal fires) rather than clicking.
- QtWebEngine/permission/notification API details are best confirmed against the
  QML type defs (`plugins.qmltypes`) rather than guessed.

# `painter` — text-to-image app

Vendored source of the standalone Qt/QML text-to-image app (`main.py`, `qml/`,
`families/`, `graphs/`, `tools/`), same live-source pattern as the rest of
[`apps/`](../AGENTS.md). Built/installed by `home/prog/painter.nix` (mirrors
`player.nix`, plus `qt6.qtwebsockets`); runs the **live** source, so `.py`/`.qml`
edits need no rebuild.

Front end for a **headless ComfyUI** — the app speaks only the HTTP/ws API
(`/prompt`, `/object_info`, `/ws`, `/view`, `/history`, `/interrupt`, `/queue`),
so a Comfy update cannot break the UI, only individual node contracts (which
`graph.py` checks against the live `/object_info` at build time and reports as a
per-family reason string rather than a silent failure). Chrome is hyprvtb
titlebar buttons (generate/cancel/view switch + bottom-anchored settings
drawer).

## Two roofs: `Main.qml` is the Hyprland one, the KDE shell is the other

`Root.qml` is the app — an `Item`, not a `Window`. `Main.qml` is a twenty-line
`Window` around it for the Hyprland session; in a Plasma session `main.py` puts
the same `Root.qml` in a `QQuickWidget` inside a real `QMainWindow`
(`pylib/kdeshell.py`), so the menubar, toolbar and statusbar are genuine KDE
widgets and the window background is Oxygen's own gradient, painted behind this
QML. The full argument, and what an app has to do to adopt it, is in
[`../AGENTS.md`](../AGENTS.md) → `pylib/kdeshell.py`. What it means when editing
here:

- **Nothing Window-only in `Root.qml`.** `onClosing`, `contentItem`,
  `activeFocusItem` and assigning `root.width` all belong to a Window; they go
  through `root.Window.*`, a `Connections` on `root.Window.window`, or a signal
  the Window wrapper handles (`requestResize`).
- **`Theme.windowFill`, not `Theme.bg`, for a pane's background** — it is
  `transparent` under Plasma so the styled gradient shows through. `bgAlt`
  panels and fields are insets and keep their colour.
- **`tbButtons` carries `icon:` and `bar:`** alongside `menu:`, for the real
  toolbar. The DeskMenuBar in this file is `systemBar: true` — painter has a
  real QMenuBar and must not draw a second one.
- **`statusLine` / `statusProgress`** are what the KDE status bar shows;
  `QueueBar` is the Hyprland strip and is hidden (and `barH` 0) there.
- **`actions` is the whole table of verbs; `tbButtons` is a filter over it.**
  The titlebar column has six cells and a menubar has thirty rows, so the rows
  the titlebar gets are the ones marked `tb:`. Everything else on a row is inert
  on the other side: `vtbclient.py` reads id/label/state/tip/bottom and ignores
  the rest, `kdeshell` never sees `label`. `menu:`/`menuText:`/`icon:`/`bar:`/
  `shortcut:`/`checkable:`/`group:` are the KDE half; `menuOrder` names the
  menus. A row whose target is missing is **disabled, not removed**.
- **A `shortcut:` in that table is the Plasma face\'s alone.** Two owners of one
  sequence in a window is an ambiguous shortcut and Qt fires NEITHER, so the QML
  `Shortcut`s that duplicate one carry `enabled: !root.plasma`.
- **The panes are their own files.** `ResultsPane.qml` (preview + gallery +
  `OutputView`) and `ParamsPane.qml` (the parameter column), because under
  Plasma the parameters are a real `QDockWidget` — a second scene — while
  `Root.qml` stays the app. Each pane declares `id: root` and FORWARDS to an
  `app` property rather than relying on QML resolving `root` up the
  creation-context chain, which is what every panel in here does and which has
  nothing to resolve against when a pane is the root of its own view. Add a
  property to `Root.qml` that a panel reads, and it must be added to the pane\'s
  forwarding block too.
- **The parameter column is NOT a `QDockWidget`.** It was one for a day. A dock
  is a second `QQuickWidget`, which is a second scene graph rendered on the GUI
  thread every frame — a QQuickWidget cannot use the threaded render loop — and
  his verdict (2026-08-22) was that the detaching was not wanted, its header was
  not wanted, and the window felt slower for it. The column lives in the one
  scene, behind the splitter, in both sessions; `showParams` (F7) puts it away
  and on a window too narrow to split it moves `view` with it, so the toggle
  cannot leave you looking at the wrong pane. `kdeshell.dock` stays — general,
  tested, unused here.
- **The window is dragged by its CHROME, and nothing else.** Oxygen's
  WindowManager drags from every unclaimed pixel, including inside the QML —
  it filters the window contentItem, which only ever sees a press nothing in
  the scene accepted. `Root.qml` therefore keeps a full-window `MouseArea` at
  `z: -1000` that accepts those, so a press on a panel's background or between
  two thumbnails no longer moves the window; the menubar and toolbar still do,
  natively. The status bar is excluded on the widget side (`_kde_no_window_grab`
  plus a press filter, `kdeshell._ensure_status`). painter briefly had its own
  26px drag band instead; it was a strip of nothing and it went, along with the
  "output N outputs" heading it replaced — that tally is in `statusRight` now.
  Both panes sit flush under the chrome. Since 2026-08-22 the style is *also*
  narrowed at its own end — `home/prog/oxygen.nix` sets Oxygen's
  `WindowDragMode=WD_MINIMAL`, upstream's supported "chrome only" — but the
  MouseArea stays: it is session-independent and it is the only guard on a
  machine where that rc has not been applied.
- **Under Plasma the results pane paints `QPalette.Base`** — `DeskStyle.viewBg`,
  the colour Dolphin paints its file list with. The window\'s own background is
  the style\'s gradient and the two are deliberately different: the band keeps
  the gradient because it is chrome. Empty string outside Plasma.
- **The grid shows EVERY output** — `load_existing` was capped at 60, a number
  from when the results were a strip, and the history simply stopped partway
  with nothing saying so. A `GridView` only builds what it can see, so the rest
  costs one small dict each. Two things make that affordable: a tile's `Image`
  is `cache: true` at `grid.thumbPx` (a 60px-bucketed 2x of the cell) rather
  than an uncached 420px decode of a multi-megabyte PNG on every scroll past,
  and a clip's poster frame is extracted **on demand** (`Gallery.requestPoster`,
  asked for by the delegate) with only the first 24 queued eagerly.
- **`Gallery` keeps `_all` and shows `_rows`.** The toolbar\'s filter field
  (`kdeshell.toolbar_search`) calls `Gallery.setFilter`, which matches every
  word against the filename AND the prompt — read out of the file once and
  cached on the row. Both lists hold the SAME dicts, so a poster landing
  reaches both; every index QML asks about is a VISIBLE index.
- **The parameter column is a `Repeater` over an ORDER, not a declared stack.**
  `ParamsPane.builtinOrder` is the old declaration order and one saved list
  (`Prefs["sections"]`) reorders it — dragging any panel header moves that
  section, live, and a right-click on a header offers the way back. Three rules
  it is built on:
    - **One order serves all three modes.** A section a mode does not have is
      hidden, and a `Column` skips an invisible child — which is exactly what
      produced the per-mode orders before, so nothing had to be per-mode.
    - **`sectionVisible(key)` on the pane owns the gate, not a `visible:` on the
      panel.** An item\'s `visible` reads back its EFFECTIVE visibility, so
      `Loader.visible: item.visible` latches false the moment it is false once
      and empties the whole column. Measured exactly that way.
    - **A `ListModel`, not a JS array.** `move()` moves a delegate; reassigning
      an array rebuilds every one of them, which would destroy the header being
      dragged mid-drag.
  A key the saved order does not name is re-inserted at its BUILT-IN position,
  so a new panel can never be buried at the bottom or lost.
- **Pins are the ROWS THEMSELVES, and collapsing hides what is not pinned.** A
  folded panel is its header plus the rows he pinned, laid out where they always
  were and still live — a pinned Spin steps, a pinned Toggle toggles, the pinned
  preset row still switches presets (his call, 2026-08-22). Nothing pinned means
  header only, as before. Right-click a row's label and take
  `pin <name> to the header` — a MENU, because a bare right-click that pins
  outright is an action with no name and no way to find out it exists
  (docs/DESIGN.md §10). Four things this needed, each a bug first:
    - **Unpinned rows are PARKED in `stash`, not hidden.** Their `visible` is
      often bound by the caller (`visible: !panel.fromImage`) and assigning it
      would destroy that binding for good.
    - **Order comes back by re-seating, and re-seating needs a bounce.**
      Assigning a row the parent it already has does not move it, so a row
      returning from the stash landed after the ones that never left; from the
      first row whose home changed, every row is bounced through `stash` and
      back in declared order. Through the stash, never through `null` — half
      these rows are `width: parent.width`, and a null parent makes that a
      TypeError for the frame it lasts.
    - **A row with a `Repeater` in it cannot be reparented at all.** The preset
      switcher's four buttons stayed measured, laid out and counted by QML while
      nothing drew them. Such a row sets `selfHides: true`, is never parked, and
      binds its own `visible` to the panel's state instead (`ModeSwitcher.qml`).
      It has to be the FIRST row in its panel for the ordering above to hold.
    - **`rowOrder`** is captured once at completion; QML cannot insert a child
      at an index, so it is the only record of what the column should look like.
- **The single-output view is an image viewer.** The wheel ZOOMS (through the
  notch accumulator — the flickable's own wheel overlay stands down,
  `wheelEnabled: false`), the left button PANS, and an edit output opens with
  the before/after slider on: `qmlcommon/CompareView.qml`, the same file
  viewer's `--compare` uses, moved there rather than copied. `App.compareSource`
  answers what to compare against; anything that is not an edit gets "" and
  shows normally. The toolbar's `compare` button (icon + the word, via
  kdeshell's `barText`) is the switch; it is remembered — and it is **offered
  only where it can do something**, i.e. in View, on an edit, with a before that
  this machine can find ([his] *"the compare button should only show when the
  output viewed is an edit"*). That is `hidden:` on the row plus the `actions`
  filter in `Root.qml`; kdeshell rebuilds its chrome when the SET of rows
  changes, since a state flip alone cannot remove a button (apps/AGENTS.md).
- **The before-image is filed beside the output, because a recorded path was
  not enough.** [his] *"the compare mode just doesnt work in general"* —
  measured 2026-08-22: the slider itself is fine (the harness drives it end to
  end), what failed was finding the BEFORE. `input_image_local` names a path on
  the machine that ran the edit, and painter reads two histories: its own
  outputs, and — on book — top's over the sshfs peer mount, where a path like
  `/run/media/lam/bak/…` means nothing. A source that has since been moved or
  deleted is the same failure locally. So `_keep_before` copies the source into
  `<out root>/.before/<output stem>.<ext>` as the output lands (hidden, and
  outside the two globs the gallery scans, so it is never itself an output), and
  `_compare_source` looks there FIRST, then at the recorded path, then for the
  same file NAME in any output root — an edit of an earlier generation, which is
  the common case. Outputs made before this exists still resolve through the
  last two.
- **The status bar's right-hand end names what you are looking at.** In View it
  leads with the output's pixels — and a clip's running time after them — then
  the tally of outputs, the selection and the queue depth ([his] *"in individual
  output view it should display the resolution of the output and, if video, the
  duration - to the left of the number of outputs"*). `OutputView.infoText`
  measures it off the decode that is already happening (the `Image`'s implicit
  size, the `MediaPlayer`'s metadata), so there is one answer and it costs
  nothing; it is empty until something has decoded rather than saying `0x0`.
- **The grid's column count is a choice, defaulting to automatic.** View →
  Columns (a `group:` radio set, `cols0`..`cols6`, remembered as `gridColumns`).
  0 keeps the width-driven layout — whole columns of a cell near 210px — and a
  chosen count is still clamped by the 60px cell floor, because honouring a
  number the pane cannot fit is how the grid goes empty (the note in
  `GalleryView.qml`).
- **Generate stays live while a job runs, so a second one can be QUEUED** ([his]
  *"allow the user to queue generations, currently they are unable to"*).
  ComfyUI has a queue and `_start_jobs` adds to it; what stopped him was the
  chrome — the row greyed out on `App.busy`, which also swallowed Ctrl+Return,
  since a disabled `QAction` eats its own shortcut. The word changes instead
  (`Queue another generation`, `[ queue ]` in the Hyprland strip) and `queued N`
  beside it is where the extra job shows up.
- **Back leaves the output, Forward returns to it.** `@Back`/`@Forward` are the
  Browse↔View pair, not the output walk — the grid keeps its place because the
  selection never moves. Walking outputs is PgUp/PgDown (QML shortcuts, gated on
  being in View so they do not take paging from a text box) and the Go menu's
  two rows, which carry no shortcut of their own.
- **Browse ↔ View.** `inView` plus `OutputView.qml` — one output filling the
  pane, entered by Return or a double-click (which no longer launches `viewer`;
  that is still File → Open in Viewer), left by Escape, walked with Alt+Left/
  Right and PgUp/PgDown. **The selection is the cursor**: View shows `selOne`,
  so there are never two places that disagree about which output is current.
  Zoom belongs to a still; a clip\'s zoom rows are disabled.

## The look is the desktop's, and painter is where it was worst

painter used to break eight of `~/nix/docs/DESIGN.md`'s rules at once; §19.1 there
records each one and what it became. What that leaves you with, mechanically:

- **`TextButton.qml` is the only clickable label.** Every action in this app
  goes through it — hover tint, `PointingHandCursor`, `enabled` (0.4 opacity,
  click refused), `lit`, `winActive` greying to `Theme.inactive` (the §3.1.1
  fade — RETIRED 2026-08-09, so the window pins `winActive` true and the grey
  never fires; the property survives for a re-arm), and `flipY` for a mirrored
  paired glyph. Do not drop a bare `MouseArea` on a `PixelText`.
- **No `radius:` anywhere, and no `QtQuick.Controls` `ToolTip`.** `ToolTipArea`
  is ours now: it reparents its chip into the window `contentItem`, because the
  left column is `clip: true` panels inside a Flickable.
- **`Spin` is a DISCRETE STEPPER**, so its wheel goes through
  `qmlcommon/WheelNotch.qml`, not `WheelScroll`. Content scrollers take
  `WheelScroll`; anything that steps a value takes the notch accumulator.
- **`NO lineHeight/lineHeightMode` on the prompt `TextEdit`.** They are
  `Text`-only; assigning them is a component-creation error that made
  `PromptBox` unavailable and stopped the whole app loading for a while. The
  comment in `PromptBox.qml` is load-bearing.
- **Backend controls report `systemctl`, not intent** — `App.backendRunning` /
  `App.unitState` are polled, and `startBackend`/`stopBackend`/`unloadModels`
  all check their result before they claim one.

**Every scrollable surface here is a `Kinetic*` view from `../qmlcommon/`** — the gallery grid, the model/LoRA/dropdown lists, the left parameter column and the prompt boxes. painter used to carry its own copy of `WheelScroll.qml` that nothing imported, so every one of those was a bare Flickable adding Qt's flick on top of the compositor's momentum. Never write a bare `ListView`/`GridView`/`Flickable` here; see [`../AGENTS.md`](../AGENTS.md).

## `gen` is a `property var` — NEVER mutate it in place

`Main.qml`'s `gen` holds every generation setting, and this is the trap that
made most of the UI silently wrong until 2026-08-04:

```qml
var g = root.gen; g.steps = v; root.gen = g   // WRONG: emits no change signal
root.set("steps", v)                          // right: hands out a NEW object
```

Assigning a `property var` the object it already holds notifies nothing — proved
directly, not inferred: the same edit through a fresh object updates its
bindings, through the same object does not. Every panel used the first form, so
the values still reached `submit()` (which reads `gen` at click time, which is
why this looked like it worked) while **everything displayed from `gen` was
stale**: the resolution badge, a `Spin` showing a family's default, the seed
box's grey-out, and the entire ModelSampling block, bound to
`root.gen.modelSampling` and therefore never revealed by its own toggle.

`root.set(key, value)`, `root.setMs(key, value)` and `root.clone(o)` are the
only sanctioned writers. Two corollaries, both the same rule one level down:

- **A control must not assign its own bound property.** `Spin.commit()` used to
  write `value`, and `Picker` used to write `value` — writing a bound property
  in QML *destroys the binding*, so one edit permanently disconnected that box
  from the model and no later family default or reused image could move it
  again. Both now only emit (`edited` / `picked`) and let the value come back.
- **A two-way text binding is a loop.** `PromptBox` takes `value` (model in) and
  emits `edited` (user out), with the model→editor write flagged (`syncing`) so
  an echo is not re-reported as a keystroke. Binding `text:` straight to
  `root.gen.positive` is a live binding loop the moment `gen` notifies properly.

`tools/ui-test.py` covers all of this — see below.

## The four modes are shortcuts to four models

Above the model list, [his] *"there should be a switcher for anime (selects
anima base model), real (selects krea 2), edition (…Klein…), and then one for
video (selects minimax h3)"*. `ModeSwitcher.qml` draws them; **the table of
which file each one means is `registry.MODES`**, painter answers it through
`App.modes()`, and nothing in QML decides it.

- **A mode is a selection, not a fifth kind of model.** Turning one on selects
  its file and greys the list (`enabled: false` *and* dimmed — docs/DESIGN.md
  §10.1); turning it off hands the list back with that model still selected.
- **`prefer` is exact-name, then substring, then any model of the family**, so
  a re-quantised or renamed file lands on its sibling instead of the button
  going dark. Which file each mode means is HIS choice — `real` is krea 2 raw
  fp8 (2026-08-06), not whatever looks newest.
- **A mode with nothing to select stays in the row, disabled.** `App.modes()`
  reports availability per button and `setMode` refuses rather than lighting up
  over an unchanged selection; a mode whose model disappears on a rescan clears
  itself rather than greying a list it no longer overrides.
- The mode is remembered (`Prefs` key `mode`) and applied when the rows land —
  after the remembered model name, which it outranks.

## Editing is a different pipeline, not a flag on the image one

`edit` is the one mode that changes more than the selection: a family may
declare an `edit` block (`families/flux2.json` — Flux 2 Klein, the only one) and
`registry.build()` then branches to `_build_edit()` on `graphs/edit_flux2.json`,
**transcribed from the workflow behind the `Flux2-Klein_0000*.png` outputs**
(their embedded `prompt` chunk is where to look if a node contract moves).

What is genuinely different, and therefore what the left column stops offering
— [his] *"the left side of the program when edit is selected should really just
be a box to drop the image in and a prompt box"*:

- **The image decides the size, and one control scales it.** The dropped
  image's own dimensions size the output — the primary `scale_image` node's
  output `GetImageSize` reads to feed both the latent (`EmptyFlux2LatentImage`)
  and `Flux2Scheduler`, so there is no aspect and no width/height.
  `EditScalePanel.qml` (shown only in edit mode) is the one control: a
  **no-scaling** toggle (`gen.editNoScale`, default on → `_build_edit` swaps
  `scale_image` to `ImageScaleBy` at `scale_by` 1.0, output = original
  dimensions) and, when it is off, a **megapixel budget** field
  (`gen.editMegapixels`, clamped 0.1–8.0) applied through the base graph's
  `ImageScaleToTotalPixels` — the same MP control the image and video paths
  offer, so the image is scaled to that many pixels with its own aspect kept,
  NOT multiplied by a scale factor. The reference latent (the primary's
  `VAEEncode`) reads the SAME scaled node, so it and the output latent stay the
  same size by construction. The additional reference images keep the family's
  pixel budget (`ImageScaleToTotalPixels`) since they never size the output.
  `submit()` sends `editNoScale`/`editMegapixels` for the edit path.
- **One prompt.** The negative conditioning is the positive one zeroed out
  (`ConditioningZeroOut` -> `ReferenceLatent`), which is what CFG 1.0 wants —
  so the negative box is hidden rather than typed into nothing, exactly as for
  video. A second `CLIPTextEncode` in that template is a bug, and
  `validate-graphs.py`'s `check_edit` fails on one.
- **The numbers come from the family**, not from `gen`: steps 15, cfg 1.0,
  shift 6.0 (and the reference budget, 1.5MP). Their controls are off screen, so
  `submit()` sends only the prompt, the seed and the output-scale choice — sending
  `gen`'s values would run the job at whatever the last image family left behind.
  `_build_edit` also strips
  `scheduler`/`denoise`/`add_noise`/`width`/`height` from the recorded
  parameters, since Flux2Scheduler reads none of them and a PNG must not claim
  settings that were not used.
- **The seed IS one of them, so edit has its own seed control.** `_build_edit`
  feeds `gen.seed` into the noise node, so an edit is as reproducible as any
  other generation — but the sampling panel that normally carries the seed is
  one of the ones `visible: !App.isEdit` hides. `SeedPanel.qml` (edit-only)
  brings just that one row back, using the shared `SeedField.qml` the sampling
  panel also uses, so the seed behaves identically in every preset.
  `SeedField` also carries **reuse last**: `_start_jobs` remembers the base seed
  each batch actually ran at (`App.lastSeed`, persisted as the `lastSeed` pref),
  and `gen.reuseSeed` re-runs at exactly it — overriding a random/negative seed —
  so a result can be reproduced without hunting for the number. The toggle is
  dead until there IS a prior seed (§10 honesty).
- **The PRIMARY image is the same slot as the video first frame**
  (`App.inputImage`), uploaded the same way, and required: with nothing dropped
  `generate()` refuses before uploading anything.
- **N images, not one.** Flux 2 Klein takes multiple reference images —
  `comfy/model_base.py`'s `Flux.extra_conds` collects `reference_latents` into a
  `CONDList`, and `ReferenceLatent`'s own schema says *"chain multiple to set
  multiple reference images"*. So `_build_edit` chains one `ReferenceLatent` per
  image (each its own `LoadImage → ImageScaleToTotalPixels → VAEEncode`) onto
  BOTH conditioning tails, and repoints the guider to the tail. **Only the
  primary sizes the output** (`GetImageSize` still feeds the latent and the
  scheduler off image #1); the rest are references. The extras are their own
  list (`App.editExtraImages`, kept separate from `inputImage` so the video path
  is untouched); the UI is a stack of wells under the primary plus an empty "add
  another" well. `submit()` passes `input_images` (primary first);
  `input_image` stays as `input_images[0]` for the single-image case.
- **LoRAs work here too.** The one panel edit mode keeps below the prompt (the
  drop wells and prompt box aside) is the LoRA stack: an edit model takes a LoRA
  exactly as an image one does. `_build_edit` chains the `LoraLoader` onto the
  loader→`ModelSampling` seam with the same `insert_lora_chain` the image path
  uses, `_start_jobs` sends `loras.active()` for all three pipelines, and the
  picker's choices come from the same `compatible_loras` match — so the edit
  family shows only its own compatible LoRAs (a Klein LoRA on Flux 2 Klein). No
  new matching: the alias map is the family's `lora` block like any other.
- A family with no `edit` block **refuses** an edit build. That refusal is what
  the mode button relies on.

## A clip tile plays on hover

Hovering a video in the gallery plays it, muted and looped, over its own poster
frame (docs/DESIGN.md §5 — the desktop rule, not a painter widget). The player
lives in a `Loader` gated on `tileMa.containsMouse`, so it is **created on
arrival and destroyed on leaving**: at most one decoder exists at a time, and
none survives the pointer moving on. The play marker stands down while it
plays. `test_hover_play` builds a two-second clip with ffmpeg and asserts all of
that, including the muting — an `AudioOutput` is a plain QObject rather than an
Item, so nothing walking the scene can find it and the holder aliases `muted` /
`volume` for the harness.

Bindings inside that delegate use `isVideo === true`, not a bare role: a tile
torn down while the pointer is on it evaluates them once with its model context
already gone, and `undefined` assigned to a bool is a QML warning — which fails
`ui-test.py`.

## Several outputs are selected, and drag as ONE collage

Click, ctrl-click and shift-click select in the gallery exactly as they do in a
file manager ([his] *"make it so i can shift / cntrl shift a selection of
outputs"*), and dragging a set out hands over **one picture with all of them in
it, under 4MB** — *"what gets put down where the cursor lies is a collage of
them in the highest quality under 4mb"*. Five files land five different ways
depending on what catches them; one picture lands the same way everywhere.

- **The selection is kept as PATHS, never indices.** A finished job inserts a
  row at 0, which would renumber a set of indices under him mid-selection; the
  same `Connections` drops a path whose row has gone.
- **A press inside an existing multi-selection does not collapse it** — the drag
  that may follow has to carry the whole set, so that click is deferred to the
  release and applied only if no drag happened (filer's rule, docs/DESIGN.md §13).
- **Shift is the RANGE key here, so it cannot also mean "with the sound"**: a
  lone clip still drags muted-unless-shift, but once a selection is in play the
  original-audio drag is ctrl+shift.
- **The layout is `collage.py`; the budget is `pylib/imgfit.py`** — the same
  search filer's "copy under 4MB" uses. What is painter's is the arrangement: a
  grid whose cell takes the mean SHAPE of its contents (a set of 2:3 portraits
  in square cells is mostly background), each image fitted and never cropped,
  row-major in the gallery's own order. **It never upscales into a cell** — the
  budget buys real pixels or interpolated ones at the same price, and the
  interpolated ones carry nothing. Measured on six real Klein outputs: 2.0MB,
  3776x2072, quality 92, 0.3s.
- **It is built when the SELECTION changes, on a thread**, and the press joins
  that thread (bounded, 25s) rather than starting the work. A payload has to be
  ready in the same event as the press, and decoding six PNGs plus half a dozen
  JPEG encodes is not. Cached under `~/.cache/painter/collage/<key>/`, keyed by
  every source's path+mtime+size, so a re-generated output cannot be served from
  the old picture, and written through a `.part` rename so a drag can never
  catch a half-written file.
- A selection of ONE is not a collage: it drags as the file itself, clip muting
  included.

## An output is dragged out of the window

The gallery's tiles are a drag SOURCE (docs/DESIGN.md §13), in filer's idiom and
for its reasons: `Drag.active` bound to a MouseArea dragging an invisible proxy
(a bare `Drag.startDrag()` does not start a cross-app drag on Wayland), the
payload built on PRESS, a chip grabbed into `Drag.imageSource`.

**A clip goes out MUTED**, with Shift at the press for the original ([his],
2026-08-06): the model generates sound with the picture and the case he named is
dropping one into surfer, which plays it. `App.dragUriList()` decides that at
the press, because Wayland cannot tell what is under the cursor and the file has
to exist before the drop lands — which is why it holds **the one synchronous
subprocess in this app**. A `-c copy` remux is tens of milliseconds; it is
bounded, and a failure hands over the original with a toast rather than a drag
that quietly does nothing.

Where that copy goes differs from the clipboard's on purpose: a fresh
`<name>-muted.mp4` sitting beside the original is reused, but a new one is made
under `~/.cache/painter/muted/<mtime>-<size>/` — same filename, so the receiving
app shows a sensible one, without leaving a second file in the gallery folder
for every clip he happens to drag.

## One dropdown, at the top of the scene

`Picker` is the box; **the list is `pickerOverlay`** (`PickerOverlay.qml`), a
single instance in `Main.qml` beside `CtxMenu` and for the same reason. A popup
parented to its own picker cannot rise above what follows it — `z` orders
siblings, not strangers — so it was clipped by the left column's Flickable and
drawn under the panels below it, worse the deeper the picker sat. The overlay
positions itself in scene coordinates, clamps into the window (flipping above
the box near the bottom edge), and closes on an outside click, Escape or a
wheel, since a list pinned to the scene would otherwise float away from a
scrolling column.

## Results left, controls right

The two panes swapped on 2026-08-05 [his] *"switch the left and right sections
with eachother"*, so `paneLeadW` sizes the RESULTS pane and the floors went with
it (`minLead` 200 for the gallery, `minTrail` 300 for the controls). A
`splitRatio` saved before the swap describes the other pane, so `restoreState`
inverts it once and records that under `splitSwapped` — without that the divider
comes back mirrored on the first launch after the change.

## The preview viewport

Above the history, off by default, toggled from the titlebar's `pv` cell
(`PreviewPane.qml`, height dragged by the same grip a prompt box has, remembered
as `preview.h`). **It is the RUNNING JOB, not a browser** — [his] *"it should
only show the preview frames of the generating image or video and when complete
should just show that image or video, no clicking on other outputs or
anything"*. Two states, no controls:

1. **the sampler's own preview frames** while a job runs — `main.py`'s
   `LivePreview` (a `QQuickImageProvider`) fed from `ComfyClient.jobPreview`,
   addressed as `image://livepreview/<tick>` because an `Image` whose URL never
   changes never reloads.
2. **what it made**, once it lands: the newest gallery row, full stop. A clip
   plays looped and **muted** — a preview beside a music player, not playback.
   Playback is viewer, on a double-click in the grid. A single click in the grid
   does nothing at all, deliberately.

**A video job WALKS the clip, and that walk is a local backend patch.** [his]
*"why will sampling previews only show the first frame from the generation"* —
measured 2026-08-06: painter's side was never the problem. Three synthetic
frames pushed through `_on_preview` were each grabbed off the real pane
offscreen, so the `image://livepreview/<tick>` URL does reload per frame.
Upstream ComfyUI slices the temporal axis to index 0 in every video previewer
(`Latent2RGBPreviewer` `x0[0, :, 0]`, `TAEHVPreviewerImpl` `x0[:1, :, :1]`) and
hands back exactly ONE image per sampler step, so no client — its own web UI
included — can be shown more. He ruled a patch out once (*"just remove that
stuff for previewing, i think doing it how i want would kill inference
speeds"*), then asked for *"frame X of Y"* in the tag, which is what made the
slice index worth moving: the cost is nil, because the slice happens either way
and only the index changes.

So `/home/lam/comfy/latent_preview.py` carries a local commit (a fourth, on a
checkout maintained by rebasing onto upstream tags) that makes the slice a
cursor and carries the position out with the image as a fourth element of the
preview tuple, merged into the event-4 metadata by a matching patch to
`comfy_execution/progress.py`. `comfy.py`'s `_on_binary` handles BOTH shapes and
`_on_connected` announces `supports_preview_metadata`, because that is the only
channel that can say which frame a preview is; `PreviewPane`'s tag reads
`sampling · frame X of Y`.

**The cursor is paced by the STEP COUNT, not incremented by one.** [his] *"itll
only show like half the frames preview and then the gen will be finished"*
(2026-08-22) — one preview arrives per sampler step, so a one-frame-per-preview
cursor walks exactly `steps` frames and a 20-step job over a 41-frame clip ends
at frame 20. `prepare_callback` now hands the previewer its `steps` and
`_pick_frame` maps the cursor onto the whole clip: frame 1 on the first preview,
the last frame on the last, evenly spaced in between, whatever the ratio. Fewer
steps than frames means a sparser sweep — one image per step is the API's
ceiling, not something painter can raise.

If previews ever appear to stop rather than merely repeat a frame, the place to
look is `comfy.py`'s `_on_binary`: it keeps only `BinaryEventTypes.PREVIEW_IMAGE`
(event 1), and ComfyUI sends the newer `PREVIEW_IMAGE_WITH_METADATA` (event 4)
shape instead to any client that announced `supports_preview_metadata` in the
websocket handshake. painter announces nothing, which is exactly what keeps the
backend on the old shape.

Two things about the backend, both worth knowing before debugging an empty pane:

- **ComfyUI sends nothing without `--preview-method`** (its default is
  `NoPreviews`), which `home/prog/painter.nix` now passes — but the unit is
  `X-RestartIfChanged=false`, so a backend that was already up keeps running
  without it until it is restarted. That is why the pane says so once a job has
  been going 45s with no frame, rather than "waiting" forever.
- **A video preview is one still frame per step, not a moving clip.** The local
  patch chooses WHICH frame each step shows (above); it cannot make the backend
  send two. `MiniMaxH3AV` carries the RGB factors, so `auto` works with no extra
  files; the `taehv` route (a real decode rather than the RGB approximation)
  needs `models/vae_approx/taehv*`, which is not installed.

That pane is why `painter.nix` carries `qtmultimedia` — and with it viewer's
NVDEC pin, for the reason measured there.

## A muted copy is a derivative, not an output

The model generates sound with the picture, so the gallery's right-click menu
offers **copy muted copy** on a clip: `<name>-muted.mp4` beside the original,
made with `-map 0 -map -0:a -c copy` (no re-encode, IO speed), **reused when it
is already there and not older than its source** so asking twice cannot leave
three files behind, and hidden from the history — `is_muted_copy()` filters both
the initial scan and anything that lands while running, or every clip would be
listed twice.

**COPYING OUT goes through `pylib/clipfile.py`, never `QClipboard`** (reading
the clipboard, which is what the frame wells' paste does, is ordinary
`QClipboard` — see "A frame well takes a PASTE" below). A
Wayland selection dies with the process that offered it, so the copy is owned by
a forked holder that outlives painter; and `QClipboard.setMimeData` takes a
Python-built `QMimeData` whose wrapper Qt's global-static clipboard frees AFTER
the interpreter is gone — a SIGSEGV in `__run_exit_handlers` on the way out of
any run that had copied something, which the harness caught as exit 139 with
every check passing.

It was `wl-copy --type text/uri-list` until 2026-08-05, and that pasted the
copy as TEXT rather than as the file into anything GTK-flavoured: wl-copy offers
exactly ONE mime type, and a file paste in GTK (so also Chromium/Electron — a
browser, a chat client) is recognised by `x-special/gnome-copied-files`.
clipfile owns the selection itself and offers both. The whole argument, and the
headless-sway harness that proves it, is in `apps/AGENTS.md` → `pylib/`.

**`copy prompt` is the one clipboard action that is TEXT, so it is `wl-copy -n`
and not clipfile** — one mime type is all a string needs, and `-n` because
wl-copy appends a newline to argv content otherwise. Same Wayland rule though:
the holder wl-copy forks is what makes the prompt still pasteable after painter
closes. It reads the words out of the FILE, not out of the boxes, so an output
from three sessions ago hands back what IT was asked for — a clip included
(see "A clip carries its job too"). It is still offered only where there is a
prompt to take (`GalleryView.commonItems`, gated on the params the menu already
read — docs/DESIGN.md §10, an action with nothing to act on is not offered
greyed, it is not offered).

## A clip carries its job too

[his] *"give the user the ability to copy and inject prompts / settings of
videos like they can images"* (2026-08-21). A still has always carried the
generation that made it in its PNG `painter` chunk; the gallery's inject menu
and `copy prompt` read it. A clip carried only ComfyUI's graph, so both were
refused in front of one.

**`outmeta.params_for(path)` is now the ONE way anything here asks a file what
made it**, and it answers from three places so nothing else has to know which:

1. a still — the PNG chunk (`pylib/pngmeta.py`), unchanged;
2. a clip painter saved from 2026-08-21 — the same JSON as an `mdta` tag in the
   MP4's own metadata box (`pylib/mp4meta.py`), written in the download
   callback beside the graph `SaveVideo` already put there;
3. **an older clip — read back out of that graph** (`params_from_graph`).
   Without it the feature would do nothing for the 288 clips already on top and
   only start working on the next generation. Measured over them: 245 hand back
   their prompt and numbers, the rest are muted derivatives, a truncated file,
   or jobs whose prompt really was empty.

Three things worth knowing before touching it:

- **No ffmpeg.** The tag is written in pure Python because that code runs in the
  download callback, on the GUI thread, for every finished clip; a subprocess
  there would be a second way for a finished generation not to reach the disk.
  A file that cannot take the tag is written VERBATIM and still lands.
- **Writing it MOVES the media data.** ComfyUI emits faststart files, so `moov`
  sits ahead of `mdat` and growing it slides every byte after it down the file;
  `upsert_tags` patches each `stco`/`co64` entry by the same delta. The harness
  pins it the only way that means anything — an ffmpeg-written clip, tagged,
  and the decoded video hashed before and after.
- **The graph reading recovers only what the graph holds.** The prompt, the
  sampling numbers, the seed, the frame count (as seconds) and the pixel budget
  — not the frames' local paths, which is why an old clip's first-frame toggle
  injects as OFF. A clip painter tagged itself DOES carry
  `input_image_local` / `last_image_local`, and `injectParams` puts the picture
  back with the toggle — or leaves the toggle off when that file has since
  moved, rather than arming a generate that could only refuse (§10 again).

`injectParams` branches on `kind === "video"` for the controls a clip has and an
image does not: seconds and a frame rate instead of a batch, and the megapixel
budget taken from the job rather than backed out of a width and height an
image-to-video clip never had.


## A frame well takes a PASTE as well as a drop

`FrameWell.qml` is the drop target for the video's first/last frame and for
edit mode's image, and the clipboard reaches all three. Two routes, because
they fail differently:

- **`[ paste ]`, in the well.** Needs no keyboard and cannot be aimed at the
  wrong well. Always offered, never greyed: whether there is anything to paste
  is only knowable once the compositor has handed the offer to a focused
  window, so a disabled state would grey a button that is about to work — and a
  paste with nothing behind it toasts (docs/DESIGN.md §10).
- **Ctrl+V, with the pointer wherever it happens to be.** A window-level
  `Shortcut` sees a key before the focused item does, so the guard is
  `!textFocused` — the active focus item having a `selectedText` — and nothing
  else. It was *also* gated on hovering a well for a few hours on 2026-08-07,
  and that made the shortcut do nothing at all for anyone pressing Ctrl+V the
  way people press Ctrl+V, **silently**, because a disabled shortcut has no
  failure to report. Discoverability beat the tidier rule.
  `root.pasteWell()` picks the target: the hovered well, else the only one on
  screen, else the empty one, else the first frame; no well on screen (plain
  text-to-video, or an image family) means the shortcut is not enabled at all.
  **A focused text box still wins** — a `QQuickTextEdit` accepts the
  ShortcutOverride for Ctrl+V — which is deliberate, and is why the button
  exists. `ui-test.py`'s `test_paste` pins every branch of it.

**Reading the clipboard IS `QClipboard`** — only *owning* a selection needs
`pylib/clipfile.py`, for the reasons above. `App._clipboard_offer()` answers
what a paste means without writing anything: **files** first (`text/uri-list`,
what clipfile and every file manager put there — the picture is already on disk
under its own name, so nothing is copied), then **pixels** (a screenshot, a
browser's "copy image"), then **text that names an image** (filer's "copy
path"). `_usable_image()` is the one rule the drop and the paste share, so the
two cannot come to disagree about what an image is.

Pixels have no file, so `_paste_target()` writes one into
`~/.cache/painter/pasted` **named by content** (`pasted-<sha1[:12]>.png`):
pasting the same screenshot twice is one file, and — since the upload cache is
keyed on the path — one upload to the backend. They are pruned to the newest 20,
and cannot simply be temporary: the backend uploads the file at generate time,
and prefs remember it across a launch.

## The history is BOTH machines', with nothing shown twice

**top's backend files every result on top, whichever machine asked for it** —
book generates through the tunnel and keeps only the copy it downloads
afterwards. So top's gallery has always been the whole history and book's was
the tail of it.

`comfy-tunnel.sh` therefore mounts `top:~/Pictures/painter/out` read-only beside
the models (0.14s, and a failure is a stderr line rather than a notification:
it costs the older half of a list, not the ability to generate) and exports
`PAINTER_PEER_OUT`. `main.py`'s `PEER_OUTS` is that, colon-separated like a
PATH; `Gallery.load_existing` globs every root in turn and `Gallery.add` drops a
peer row for the local file that replaces it. **On top it is unset and nothing
changes** — there is no second root to add, because top already holds
everything. Measured on book 2026-08-06: 132 rows, 31 local, 101 from top, no
duplicates.

Two rules, both load-bearing, both regression-tested by `tools/ui-test.py`'s
`test_peer_history`:

- **The dedupe key is the NAME, never the size.** book injects painter's
  parameter chunk into the PNG it downloads and top's copy has none, so the same
  still is ~600 bytes bigger on book (a clip, downloaded verbatim, does match to
  the byte — but half a rule is no rule). Names cannot collide: the backend that
  numbers an output is top's whoever asked for it.
- **The local root is scanned FIRST and its copy wins.** Not tidiness: that
  chunk is only in the local copy, so `inject` reads a file that has parameters
  in it instead of one that does not.

The asymmetry that leaves: on TOP, a still book generated shows up but says *no
parameters stored in this file*, because nothing ever wrote painter's chunk into
top's copy of it. Fixing that means writing back over the tunnel, i.e. an `rw`
sshfs mount of his `Pictures` — not taken.

A remote row is not marked as remote in the grid, on purpose: it is an output of
his either way, and the tile says what it is. It does go away when the tunnel
does, which is the same thing the model picker already does.

## The layout holds at every width

Both panes used to vanish below 900px unless selected, so in the parameters view
a narrower window had **no results pane at all**. `root.split` (≥`splitFloor`,
560) keeps the two-pane layout at every usable width; the controls take
`max(300, min(520, …))` and the gallery takes the rest, adapting to a single
column if that is what fits — its cell can never be wider than its pane, which
is what made a narrow pane look empty. Below the floor it is one pane at a time
on the `p`/`g` buttons.

## Text boxes take a click anywhere in them, and he sets how tall

A `TextEdit` is only as tall as its content, so a 130px prompt box holding one
line accepted clicks in a 16px strip and ignored the rest. The editor now fills
the viewport (`height: Math.max(implicitHeight, flick.height)`), which hands the
empty space to Qt itself — caret at the nearest position, drag-select from
nowhere — rather than to a MouseArea imitating it. `Spin` covers its own padding
strips with an I-beam MouseArea under the input.

**A panel follows its content DOWN as well as up.** `Panel.qml` sizes itself
from the inner Column's `implicitHeight`, never from `childrenRect.height`: an
invisible child keeps the y the Column last laid it out at and `childrenRect`
still spans to it, so with the negative prompt box hidden (any video or edit
family) a panel could only ever GROW — dragging the prompt box smaller left a
blank the height of the drag ([his], 2026-08-06; measured offscreen against his
own prefs, box 392 -> 242 with the panel stuck at 435). `test_video` checks the
shrink in the state that was broken, with the box hidden by its real binding.

**The bottom 5px of a prompt box is a RESIZE GRIP**, not text — dragged, clamped
to 40-600px, and remembered per box (`prompt.posH` / `prompt.negH` in `Prefs`,
written on release). A prompt here runs from four words to the multi-paragraph
shot description a video model wants, and a fixed 130px box meant scrolling a
window through the second kind. The drag writes `boxHeight`, never `height`:
`height` is bound to `visible ? boxHeight : 0`, and writing it directly would
destroy that binding — which is what folds the negative box to nothing for a
video family. Hidden is not enough on its own: a `Column` skips an invisible
child when it POSITIONS, but `Panel` sizes itself from `childrenRect`, so the
box that was not there still left a hand-sized blank under the prompt.

## The size is derived, never typed

Aspect is **two integers you type** (any ratio, not a fixed list) plus MP;
`recomputeDims()` is the one place width and height are computed, so the header
badge, the `= WxH` readout and the submitted job are the same numbers by
construction. The width/height boxes are gone — they were a second, contradicting
source of truth. Injecting an image's parameters therefore restores its *ratio
and MP* (reduced by gcd), not raw pixels, which the next recompute would have
overwritten.

## Escape is for letting go of a text box

It used to cancel every queued job — a destructive action on the key people
press to back out of one — while there was no way to leave a text box at all.
Now `Escape` moves focus to `Main.qml`'s `focusSink` (focus has to LAND
somewhere; clearing it outright leaves the window with no focus item and the
next keystroke going nowhere), handled on the editors themselves as well as at
the window, because a focused text item is where a window-level `Shortcut` is
least reliable. Cancelling is the titlebar's `x`: a click, not a reflex.

**That Shortcut decides what Escape means for the whole window**, innermost
thing first: open dropdown → context menu → settings drawer → release the text
box. A window-level `Shortcut` sees a key before any focused item's `Keys`
handler, so adding one for the text boxes alone silently took Escape away from
the dropdown and the menu, which had been closing on it perfectly well — caught
by the harness, not by looking.

## An output is LEFT-clicked to open, right-clicked to choose

Left-click hands the file to `viewer`; right-click opens the shared `CtxMenu`
with **inject all / inject prompt / inject params**, plus `open in viewer`. Both
buttons used to raise the menu, which put a question between him and the thing
he had just made. An output carries the whole job that made it — a still and a
clip alike — and which part you want is a decision (§7.1: everything is still right-clickable). The three
actions live on the window (`injectPrompt` / `injectParams` / `injectAll`), so
the menu has no logic of its own; `injectParams` restores size as **aspect +
MP**, never raw pixels (see above).

Because a left-click LAUNCHES something, `tools/ui-test.py` replaces
`main.subprocess` with a recorder — it spawned two real `viewer` windows on his
desktop the first time that click was exercised, which is the one thing a
harness here may never do.

## The window comes back the way it was left

Persisted through `Prefs` (`~/.local/state/painter/prefs.json`): window size,
which view, the split ratio, the prompts and every number in `gen` (so every
sampling setting, including the video preset's — steps, sampler, `ms`'s shift
curve — comes back too), the selected model, the LoRA chain, and each panel's
collapsed state (`Panel.persistKey`). Three traps:

- **Writes are debounced** (700ms) — `gen` changes on every keystroke — but
  `onClosing` flushes a still-pending write immediately, so a setting changed
  right before closing (typical of video: tweak, hit generate, close while the
  long job runs) is not lost to a timer the process does not live to see fire.
- **`applyDefaults()` is guarded by `defaultsFor`.** The startup selection fires
  `modelChanged`, and without that guard a family's defaults would overwrite the
  session that had just been restored, every launch. It holds the name of the
  model whose defaults `gen` reflects; a restore sets it to the remembered one.
- **The LoRA chain needs the same guard, on `lorasRestored`.** `selectModel`
  (Python) always clears the stack on every switch — a model's LoRAs are not
  generally valid for another one — so a plain restore-on-launch would be wiped
  the instant the startup selection lands. `Main.qml`'s `onModelChanged` applies
  the remembered chain (`App.restoreLoras`, names not on disk anymore dropped)
  exactly once, when `App.selectedName` first matches the remembered `model`;
  a later in-session switch clears same as always. `App.lorasSnapshot()` is the
  save side — the WHOLE stack, unlike `loras.active()` (enabled-only, what a
  submit sends).

The divider between the panes is dragged (`splitRatio`, saved on release,
double-click to reset), clamped so neither side starves — the same shape as
filer's splitter.

## A batch he cannot see finishes as a TOAST, with the picture on it

A generation is a wait long enough to walk away from, so painter says so
itself rather than leaving the result to be discovered: when a batch finishes
behind a window he is not looking at, one desktop toast — `completed in 1:23`
(the queue bar's own m:ss clock), the output's name, and a **48px thumbnail of
what it made**, which clicking opens (docs/DESIGN.md §8.1, the same
`x-download-image` hint surfer's downloads and the screenshots wear).

Four rules hold it together, and each is a way of not being noise:

- **"He cannot see it" is `isActive() and isExposed()`, on the window** —
  unfocused, or not on screen at all. `isExposed()` is false for a window
  rolled up, minimised or on another workspace, because a compositor sends no
  frame callbacks to a surface nobody can see: it is the same test viewer
  refuses a handoff on (`pylib/handoff.py`), and **the only way a rolled-up
  window is visible to the app at all** — hyprvtb tells a client when it is
  UN-hidden (vtbclient's `WAKE`), never when it is rolled away. `main()` hands
  the window to the controller; **no window means no toast**, which is what
  keeps every harness off his screen.
- **One toast per BATCH, not per image**, timed from the press rather than
  from the last job's own start (`_batch_start`) — four images asked for in
  one click are one wait. Four outputs read as `4 outputs, newest <name>`.
- **It waits for the file.** The toast carries a path, so it cannot go out
  until every download has landed; `_maybe_notify` is called from both ends
  (the last download, and the last job to finish) because either can be the
  one that completes the batch. A clip additionally waits up to
  `POSTER_WAIT_MS` for the poster frame the gallery is already extracting —
  QML cannot decode an mp4, so a clip thumbnails the poster and `x-open-path`
  points the click at the video. Whichever arrives first, the timeout or the
  frame, takes the pending toast with it, so it is sent exactly once.
- **A failure gets that one toast instead**, at critical urgency — the outputs
  that did land are still in the gallery, but the thing worth coming back for
  is that it stopped.

The in-window `done in 4.0s` still fires either way; it is simply invisible
when he is elsewhere, which is the whole reason this exists. `notify-send`
comes from `libnotify` on the wrapper's PATH (`home/prog/painter.nix`) because
painter is launched from a .desktop entry / the runner, whose PATH need not
carry the profile dirs; book takes Fedora's, and a missing one degrades to no
toast rather than to an error.

## Starting fast is a property of the launch path

~0.45s from click to window on book (0.23s launcher + 0.22s app), against a
window that used to wait for ComfyUI to finish loading. Four things keep it
there, and each was worth measuring:

- **`top` before `top.local`.** Resolving the mDNS name takes ~5s on book
  (measured) against 0.04s for `top`. It was the single largest cost in the
  whole path — and the same ordering bug was in player's `air-launch.sh`.
- **The launcher waits for the PORT, not the backend.** ComfyUI can take minutes
  cold; the window opens as soon as the forward binds and says what it is
  waiting for.
- **Nothing blocks the GUI thread.** `systemctl` is an ssh round trip on book,
  so `startBackend`/`stopBackend`/`is-active` all go through `QProcess`
  (`_run_async`), never `subprocess.run`.
- **The model list does not need the backend.** The registry scan runs on the
  first tick and retries while it comes up empty, because the sshfs mount may
  still be landing.

## `tools/smoke.py` — the app without the window, and chatter's generator

The registry/graph/client path with the GUI taken off, so a failure in it is a
failure in painter proper rather than in the interface. It is also **the
generator chatter shells out to** (`make_image`/`make_video` in
`apps/oracle/main.py`), which is why it carries painter's WHOLE surface rather
than just text-to-image:

- `--mode anime|real|edit|video` is painter's own shortcut table
  (`registry.MODES`) — it resolves to HIS canonical file for that mode, so a
  caller naming "anima" or "klein" lands on exactly what the button would have.
  `--model` is a substring of a filename and still wins over it.
- `--image PATH` (repeatable) is the edit subject and its references, or a
  clip's first frame; `--last-frame PATH` is the other end of one. Each is
  UPLOADED to the backend (`ComfyClient.upload_image`) rather than passed by
  path, because ComfyUI loads only out of its own input directory and the
  backend is not necessarily on this filesystem.
- `--aspect W:H` + `--megapixels N` go through the registry's own `calc_dims`,
  so the shorthand and the sliders produce the same numbers. Neither applies to
  an edit or to a clip with a frame in hand — the picture decides the size —
  and `--megapixels` on an edit means RESIZE to that budget (given none, the
  original's exact pixels are kept, which is painter's own default).
- `--seconds` is a duration; `registry.video_frames` turns it into the frame
  count the model will accept.
- `--dry-run` builds the graph, prints the plan and submits nothing — no
  backend, no upload, no weights. That is how the parameter surface is checked
  without a render.
- `--progress` adds two MACHINE-READABLE lines to the prose: `::progress FRAC
  LABEL` as it runs, and one `::result JSON` at the end naming the model, seed,
  size, steps and sampler the graph ACTUALLY ran with. chatter draws the first
  as a bar and writes the second under the picture as its caption, and neither
  may be read only at the end (`readyReadStandardOutput`, not `finished`). The
  bar is a **high-water mark**: ComfyUI reports a `0/1 … 1/1` for every node,
  not just the sampler, and does not walk the graph in the order a bar is drawn
  in, so an unguarded mapping runs backwards several times a render. Only the
  sampler's own steps move it (10%–85%); everything else is a fixed station.

**HIS OWN SETTINGS ARE THE FLOOR** (`userprefs.py`, his 2026-08-24 rule: use
what he set in painter as the reference, and something else only when he says
so). painter remembers a whole block per model under `genByModel` in
`~/.local/state/painter/prefs.json` — steps, cfg, sampler, scheduler, his
negative prompt, the resolution, the clip length, the toggles and the shift
block — and restores it when that model is selected again. So a generation
started anywhere else lays those UNDER whatever it was told, and a caller only
has to name what differs. `--no-prefs` opts out.

- **It mirrors what painter itself would SEND**, mode by mode (`Root.qml`'s
  `submit()`), not the whole saved block: an edit takes only the scale keys
  because the family's edit block supplies steps/cfg/shift, and a video job has
  no CFG at all. Sending the image fields into either would claim settings that
  graph never reads.
- **The positive prompt is never carried over** — it is the last thing he typed
  into the window, not a default.
- **The seed is a policy, not a value.** `randomSeed` means a fresh one every
  time, `reuseSeed` re-runs the last batch's base seed, otherwise it is the seed
  in the box (`_start_jobs`' own rule). An explicit `--seed` beats all three;
  with no prefs at all it falls back to 12345, so a bare run is still
  reproducible.
- **An aspect or a budget named on the command line REPLACES the remembered
  width/height** — he asked for that shape, not the last one.
- The LoRA stack is one list, not one per model, so it is carried only through
  the same filter painter's own restore uses (applicable to this model, and
  `lora_compat`).
- The file is the window's; nothing here writes to it, and a missing, corrupt
  or model-less prefs document is simply no defaults. Harness:
  `tools/prefs-test.py` (pure, fabricated document, no backend).

Outputs are saved under their own subfolder (a clip lands in `video/`) and
tagged the way the app tags them — a PNG in a tEXt chunk, an MP4 as an `mdta`
tag — with a file that cannot take the tag written verbatim rather than not
written.

## `tools/tunnel-test.sh` — the LAUNCHER's harness

`ui-test.py` can see nothing outside the window, and **both bugs that left
painter unusable on book were in the launcher**, not the QML: the readiness
probe's unset variable killing the script a second after it started the backend,
and the reuse check reading OUR OWN forward as somebody else's and killing it —
after which the app talked to a closed port for ever and said *backend is not
ready yet*. That second one is why the reuse test now comes BEFORE the forward
is started, and why this file exists.

```bash
apps/painter/tools/tunnel-test.sh      # on book; uses the real top, no GUI
```

It asserts the one thing that matters — **when the launcher hands over, the app
can GET /system_stats through the port** — in both the fresh and the
already-forwarded case, that a borrowed forward is not killed, that the model
mount is visible to the app, and that neither the mount nor a forward is left
behind. Re-run it after touching `comfy-tunnel.sh`.

## `tools/ui-test.py` — the offscreen UI harness

257 checks over the real `qml/Main.qml` under `QT_QPA_PLATFORM=offscreen`, with a
synthetic model root and no backend (`unit_cmd` neutered, client stubbed), so it
can never start ComfyUI on top or open a window on his screen:

```bash
/usr/bin/python3 apps/painter/tools/ui-test.py     # on book
```

It covers the mode switcher (which file each of the four lands on, the greyed
list, the mode that has no model staying disabled rather than vanishing), the
edit column and what an edit job submits, dragging an output out (the payload
for a still, a clip muted, Shift for the original, and the copy reused rather
than remade),
click-anywhere text boxes, the collapsible model panel, the pane split
at seven widths, aspect+MP → pixels → header → submitted job, the dropdown
overlay (opens, stays inside the window, picks, and the binding SURVIVES the
pick), the live-binding regressions above, Escape (releases the box, cancels
NOTHING), the inject menu and its three subsets, the draggable divider and its
clamps, the furniture (an elided panel badge, the splitter stopping above the
status bar, the one scrollbar being on the results side, a prompt box taking a
dragged height), `copy prompt` (offered wherever there are words — a still, a
tagged clip — and not on a file with none, and what reaches `wl-copy`), a
clip's parameters (its own tag written without disturbing a byte of the
pictures, read back through `paramsAt`, injected as seconds/fps/budget, the
first frame restored only when it is still on disk, and an untagged clip read
out of ComfyUI's graph), the merged history (`PAINTER_PEER_OUT` globbed
beside the local root, the file both machines hold shown once and shown as the
LOCAL copy, an unmountable peer root costing the local scan nothing), the video
column (a synthetic video family written into the scratch
root and removed again — a fully paired model sorts to the top of the list and
would otherwise be every later test's selection), pasting into a frame well
(each of the three clipboard shapes, both refusals, the content-named file for
pixels, and that Ctrl+V reaches a well only under the pointer and never out of
a focused prompt box — the offscreen platform's clipboard is in-process, so it
cannot touch his), save-and-restore through a
SECOND window on the same prefs file, the completion toast (silent while the
window is focused, sent when it is unfocused OR unexposed, one per batch
whatever it made, a clip waiting for its poster frame, a failure taking that
one toast — all against a stand-in window and the harness's recorded
`subprocess`, so nothing reaches a real notification server), that
`startBackend` returns immediately, and a wiring audit that submits a job and
compares every field. **A QML warning fails the run** — a binding loop shows
as nothing at all on screen.

## The prompt boxes are spellchecked

A prompt is prose, so both `PromptBox`es carry a `SpellMarks` overlay
(`apps/AGENTS.md` → `SpellMarks.qml`; the mark itself is docs/DESIGN.md §3.7) and
right-clicking a marked word offers hunspell's corrections. Two things about the
wiring are deliberate:

- **The menu is Main.qml's, not the box's.** A `PromptBox` is 64-130px tall and
  `CtxMenu` clamps itself into its own root, so a menu parented inside one would
  be trimmed to a couple of rows. `PromptBox` emits `menuRequested(sx, sy,
  items)` in **scene** coordinates (`mapToItem(null, ...)`), `PromptEditor`
  forwards it, and the one `CtxMenu` at the bottom of `Main.qml` opens it.
- **`qml/CtxMenu.qml` is a verbatim sixth copy** of the file filer, player,
  reader, editor and board each have. painter had no context menu at all before
  this; folding the six into `qmlcommon/` is docs/DESIGN.md Open question 3 and is
  blocked on `PixelText`, which a shared component cannot reach. Do not "improve"
  this copy — retune all six or none.
- **A row acts on a box that still has the keyboard.** The menu takes the active
  focus while it is open, so the box takes it on the right-press and the menu
  hands it back on close, and `persistentSelection` keeps the selection alive
  across that — otherwise `select all` selected text nothing could then delete,
  and `cut`/`copy` ran against an emptied selection. The contract is
  `apps/AGENTS.md` → `CtxMenu.qml`; the regression is `ui-test.py`'s
  `menu_pick`, which picks the ROW rather than calling the editor's method (the
  check that did the latter passed throughout the bug).

The numeric `Spin`/`Field` controls are not spellchecked and must not be.

## The backend is NOT packaged

ComfyUI stays the venv+`nix-shell` checkout at `/home/lam/comfy` (symlink →
`Downloads/git/ComfyUI`, v0.30.0); its `shell.nix` already pins nixpkgs-24.11,
installs torch cu128 and patchelfs Triton's `ptxas` for NixOS, which is the
hard-won part. `home/prog/painter.nix` only adds a `systemd --user` unit
`comfy-painter.service` (no `[Install]`, never starts at boot) that painter
starts on demand and deliberately does **not** stop on exit, so 8-16G of weights
stay warm between launches. Logs: `journalctl --user -u comfy-painter -f`.

**Upgrading it** is a rebase, not a pull — the checkout carries three local
`shell.nix` commits that must stay on top: `git fetch && git rebase v<tag>`.
Two things bite:

- **The venv does not follow the rebase.** `shell.nix` installs deps once and
  guards on `.venv/.comfy_deps_installed`; delete that marker and re-enter
  `nix-shell` or the new `requirements.txt` pins never land. torch is unpinned
  there, so this does *not* disturb the cu128 build.
- **`models/` on disk is a symlink to `/home/lam/models`**, so upstream's
  placeholder files under it read as 36 deletions and any checkout would write
  into the real 246G root. They are `--skip-worktree` as of 2026-08-05; leave
  them that way.

Then gate it on the three harnesses in this order, each of which catches a
different kind of breakage: `tools/validate-graphs.py` (node contracts, every
family × all four toggles), `tools/coverage-test.py` (every base model actually
loads and decodes — 19/19 on v0.30.0), and the custom-node import block in the
startup log, since a bump silently disables a node that fails to import rather
than refusing to start. `coverage-test.py` writes its PNGs into the real
gallery (`~/Pictures/painter/out`, prefix `painter_cov_`) — delete them after,
and note that since the history merged they show up in BOOK's gallery too,
because that root is top's.

The unit passes `--listen 127.0.0.1`, and that is a **security boundary, not a
default**: ComfyUI has no authentication and a workflow graph is arbitrary code
with filesystem access. Never rebind it to `0.0.0.0`, and never add 8188 to the
tailnet allowlist in `sys/net/tailscale.nix`. To drive top's backend from book,
tunnel it behind ssh's key auth:

```bash
apps/painter/tools/comfy-tunnel.sh            # start it on top, forward 8188
apps/painter/tools/comfy-tunnel.sh -- painter # ...and run painter over it
```

**On book that is not a manual step: it IS painter's launcher.** `painter.nix`'s
`air` branch execs `comfy-tunnel.sh -- python3 main.py`, so opening painter
there probes top (`top.local`, then the tailnet name `top`), starts
`comfy-painter.service` over ssh if it is not already active, forwards 8188,
waits until the backend actually serves `/system_stats`, and only then opens the
window; the forward dies with the app. An unreachable top is **fatal with a
notification** rather than a window that can only fail on the first Generate —
same rule as player's `air-launch.sh`. `PAINTER_NO_TUNNEL=1` launches plainly
against whatever is on the local port, for UI work with no top;
`COMFY_HOST`/`COMFY_PORT`/`COMFY_READY_TIMEOUT`/`COMFY_CONNECT_TIMEOUT` pin the
rest.

**The app's own start/stop/status controls follow the tunnel.** `main.py` drives
`systemctl --user` on `comfy-painter.service`, including once unconditionally at
startup — and on book that unit does not exist, so every one of those calls
failed with "unit not found" and painter opened saying *backend failed to start*
while the backend it was tunnelled to sat there serving. `unit_cmd()` sends them
over ssh to the host the launcher resolved, via `PAINTER_BACKEND_SSH` /
`_SSH_BIN` / `_SSH_CTL` (the launcher's own control socket, because `is-active`
polls every 3s and a fresh handshake each time is ~0.2s of network). Unset — on
top, or under `PAINTER_NO_TUNNEL=1` — it stays a plain local `systemctl`.

Two traps that cost a debugging session and must not be reintroduced into the
readiness probe: while the backend warms, ssh **accepts** the local connection
and only then learns the far end refuses — so a port check is not a readiness
check (hence the HTTP probe), and the read that fails with ECONNRESET leaves
`line` unset, which under `set -u` killed the launcher one second after it had
started the backend, silently. Hence `local line=""` and `trap '' PIPE`.

`comfy.py`'s `DEFAULT_URL` stays `http://127.0.0.1:8188` so the app needs no
configuration — it talks to the local end of the forward. `PAINTER_COMFY_URL`
overrides it, for a forward parked on another *local* port; pointing it at a
remote host would put the unauthenticated API on the wire.

## Models live at `/home/lam/models`

~246G — consolidated 2026-07-25 from the two former roots,
`Downloads/git/ComfyUI/models` and `Projects/cte/app/models`, both of which are
now **symlinks** to it; that keeps cte working without editing its `config.py`,
which regenerates its own `extra_model_paths.yaml` on every import. Never in
git. Reached only via `/home/lam/models/extra_model_paths.yaml`.

**On top. book has no copy, and cannot fake one from a file list** — the
registry *reads* every model (tensor headers, then a second read per file for
LoRA target matching), so painter there mounts top's model root read-only over
sshfs at `~/.cache/painter/models-top` and points `PAINTER_MODELS` at it;
`comfy-tunnel.sh` does the mount and unmounts on exit. Only headers cross the
wire — 57 files, ~2.6s for a cold scan, near-free afterwards from
`fingerprint.py`'s size+mtime cache — never the 249G. Verified identical
identification to top's for all 57 files (role, family, loader, quant).
`PAINTER_NO_MODELS_MOUNT=1` skips it. An unmountable root is **not** fatal (the
backend is the precondition, not the picker), but it says so in a toast rather
than leaving an empty list that reads as "top has no models". Generated images
still land locally: the app downloads each result over the tunnel's `/view` and
writes it to book's own `OUT_DIR` — and since 2026-08-06 the same script mounts
top's OUTPUT root beside the model one, so book's gallery shows what BOTH
machines made rather than only what book downloaded. See "The history is both
machines'" above; `mount_ro`/`unmount_ours` are shared by the two mounts and
only ever give back what this run took, so a second painter's mount survives.
`PAINTER_NO_PEER_OUT=1` skips the output one.

## Model identification is by tensor header, not filename

`fingerprint.py`, pure stdlib, whole 246G collection in ~0.2s: safetensors' JSON
header and GGUF's KV block give tensor names and shapes, and the rules mirror
`comfy/model_detection.py` — which is the authority to re-check when a Comfy
bump moves a signal. Consequences worth remembering:

- GGUF `general.architecture` **lies** (both Krea 2 GGUFs claim `qwen_image`),
  so never key on it.
- `qwen_image_vae` and `wan21-vae` are structurally identical, so VAE identity
  needs a hash/name fallback.
- LoRA compatibility is scored by recovering the target key namespace and
  intersecting it with the base model's, which needs a per-family **alias map**
  (Krea 2 LoRAs say `text_fusion`/`to_k`/`to_gate` where the base says
  `txtfusion`/`wk`/`gate`; Z-Image LoRAs address `to_q`/`to_k`/`to_v` that the
  base keeps fused as `attention.qkv`).

Unrecognised files stay visible in the picker with a family dropdown;
assignments persist in `~/.local/state/painter/overrides.json`.

## Video is a different pipeline, not a flag on the image one

A family may declare `"kind": "video"` (`families/minimax_h3.json`, the MiniMax
H3 model that generates picture and sound together). That is one branch in
`registry.build()` — `_build_video()` — and one extra template,
`graphs/video_minimax.json`, transcribed from the workflow that produced the
first outputs (its API graph is embedded in every `MiniMax_H3_*.mp4`, which is
where to look if the node contract ever moves).

What is genuinely different, and therefore what the left column stops offering:

- **One prompt.** `MiniMaxH3ImageToVideo` takes the text itself and emits
  conditioning *and* latent, so there is no `CLIPTextEncode` and **no negative
  prompt** — the box is hidden rather than typed into nothing. `BasicGuider`
  takes **no CFG** for the same reason, and the frame count replaces the batch.
- **Two VAEs.** Video and audio latents decode separately and `CreateVideo`
  muxes them, so `pair()` resolves a `vae_audio` as well and a missing one is a
  problem reported up front.
- **Four modes, one template.** `first_frame` and `last_frame` are both
  **optional** inputs on the node and `VideoPanel` offers them as two
  independent toggles, each with its own well: first only, last only, both (the
  same file in both is what looping is — there is no loop toggle), or neither.
  With either frame the size comes **out of the image** — `ImageScaleToTotalPixels
  -> GetImageSize`, which is why `ResolutionPanel` drops to the MP box alone —
  and the measuring chain runs off the FIRST frame when there is one, off the
  last when there is not (`_build_video` repoints `scale_image`). With neither,
  it drops that chain (`Graph.drop`, which refuses while anything still reads
  the node) and feeds painter's own aspect + MP. **Each `LoadImage` is dropped
  when its end was not dropped on**: an unwired one with an empty filename fails
  Comfy's own validation.
- **Each frame is uploaded, not read.** `ComfyClient.upload_image` PUTs it
  under the input directory's `painter/` subfolder and the graph names
  `painter/<file>` — on book the backend is top's and the socket is all they
  share. Once per file, not once per job. `LoadImage`'s `image` enum is a live
  directory listing, so it is in `graph.LIVE_ENUMS` and not validated against the
  `/object_info` painter fetched at startup.
- **Frame counts are quantised.** `registry.video_frames()`: seconds × fps,
  rounded up to the next length congruent to 5 mod 17 — 5s at 24fps is 124
  frames, matching the source workflow's `ComfyMathExpression`. Done in python so
  the graph needs no custom math node.
- **Outputs are clips.** `SaveVideo` writes them under `video/` in the output
  directory (which IS `~/Pictures/painter/out` — the backend is launched with
  `--output-directory`), the gallery globs that too, and each tile wears a
  poster frame extracted once by ffmpeg into `~/.cache/painter/posters` plus the
  drawn play marker (docs/DESIGN.md §2.3). A video carries ComfyUI's graph in its
  container metadata, **not** painter's parameters, so "inject" has nothing to
  offer for one and says so.

`tools/ui-test.py`'s `test_video` covers the whole column reshaping and what
`submit()` sends; `tools/validate-graphs.py` builds all four modes (`i2v`,
`l2v`, `fl2v`, `t2v`) against the live `/object_info`, and its `=== edit ===`
section does the same for the Klein edit graph plus the refusal every other
family owes it.

## One graph, not one per model

`graphs/universal.json`; the exceptions are `universal_ckpt.json` for bundled
checkpoints, which need `CheckpointLoaderSimple` instead of the loader/clip/vae
trio, and `video_minimax.json` above. Per-family difference is expressed three ways only: a value, an optional
node spliced in/out, or a node-class swap at one role
(`UNETLoader`/`UnetLoaderGGUF`/`OTUNetLoaderW8A8` — a GGUF physically cannot
load on the plain loader).

Nodes are addressed by `_meta.painter_role`, **never by node id**, and
`_meta.painter_bypass` maps an output back to the input that replaces it when a
node is removed.

Two optional nodes are user toggles: `CLIPNegPip` (from `ComfyUI-ppm` — it is
what makes `(tag:-1.0)` work *inside* the positive prompt, and note the positive
encode reads the patched CLIP while the negative reads the raw one) and
`ModelSamplingSD3Advanced` with its full parameter set. **Chroma must keep
NegPip off**: ppm patches Flux's forward, which expects a `time_in` layer Chroma
replaces with `distilled_guidance_layer`, and enabling it aborts the sampler.

## Per-family prompt transforms

Anima's prompts are flattened to a single line on the way out and **spelled the
way Danbooru spells them** (`prompt_transform: danbooru`) while the editor keeps
your line breaks; everything else is passed through verbatim (Krea 2's
`<think>…</think>` prose must not be touched). The string actually sent is what
gets recorded in the PNG.

`danbooru` is `single_line` plus the two things a model writing the prompt gets
wrong most often, both mechanical [his, 2026-08-24]: **underscores become
spaces**, and an artist becomes **`@name`** (`artist:x`, and `by x` when x is
one token — "by the window" is a sentence, and this transform must never
rewrite his prose). It normalises SPELLING and edits nothing else. Three things
keep their underscores because they are not word separators: `score_*`, the
emoticon tags (`^_^`, `>_<` — one character either side and nothing else), and
whatever is inside a weight group, which is normalised tag by tag with the
weight untouched, so `(lowres, low_quality:-1.0)` stays a weight group.

## NegPip: the negative goes IN the positive

`CLIPNegPip` is what makes a NEGATIVE weight work inside the positive prompt,
and on a family that has it on that is the stronger control — it rides the same
patched CLIP the positive does, while the negative box is encoded through the
raw one. So `smoke.py` **folds** the negative into the positive as
`(…:-1.0)` and leaves the negative box empty, for image jobs on a NegPip
family, unless `--no-negpip-fold`. The caller writes a prompt and a negative
like anywhere else; the syntax — and the SIGN, since a positive weight there
emphasises the very thing it was meant to remove — is done here rather than
asked for. **painter's own window is unchanged**: the fold is the headless
path's, so the two boxes on screen still mean what they always did.

## Adding a family

Drop a `families/<id>.json`. No code, no new graph — unless it is a `kind`
the app does not have yet, which is what video cost (see above). Verify with
`tools/validate-graphs.py` (every family × all four toggle combinations, plus
both video modes, checked against live `/object_info`), `registry.py --pair-all`,
`registry.py --lora-matrix`, and `tools/coverage-test.py`, which actually runs
**every** base model for one step — 19/19 as of 2026-07-25, including the
int8-convrot loader, three GGUFs, both bundled checkpoints, and the pixel-space
`zeta-chroma`, which needs the generated `vae/pixel_space_vae_stub.safetensors`
(a 220-byte file whose only tensor is named `pixel_space_vae`; `comfy/sd.py`
matches on that key alone). `tools/consolidate.py` did the model move and writes
an inverse-`mv` rollback script before touching anything.

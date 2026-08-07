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

## The look is the desktop's, and painter is where it was worst

painter used to break eight of `~/nix/docs/DESIGN.md`'s rules at once; §19.1 there
records each one and what it became. What that leaves you with, mechanically:

- **`TextButton.qml` is the only clickable label.** Every action in this app
  goes through it — hover tint, `PointingHandCursor`, `enabled` (0.4 opacity,
  click refused), `lit`, `winActive` greying to `Theme.inactive`, and `flipY`
  for a mirrored paired glyph. Do not drop a bare `MouseArea` on a `PixelText`.
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

- **The image decides the size.** `ImageScaleToTotalPixels -> GetImageSize`
  feeds both the latent (`EmptyFlux2LatentImage`) and `Flux2Scheduler`, so there
  is no aspect, no width/height and no resolution panel.
- **One prompt.** The negative conditioning is the positive one zeroed out
  (`ConditioningZeroOut` -> `ReferenceLatent`), which is what CFG 1.0 wants —
  so the negative box is hidden rather than typed into nothing, exactly as for
  video. A second `CLIPTextEncode` in that template is a bug, and
  `validate-graphs.py`'s `check_edit` fails on one.
- **The numbers come from the family**, not from `gen`: steps 15, cfg 1.0,
  shift 6.0, 1.5MP. Their controls are off screen, so `submit()` sends only the
  prompt and the seed — sending `gen`'s values would run the job at whatever
  the last image family left behind. `_build_edit` also strips
  `scheduler`/`denoise`/`add_noise`/`width`/`height` from the recorded
  parameters, since Flux2Scheduler reads none of them and a PNG must not claim
  settings that were not used.
- **The image is the same slot as the video first frame** (`App.inputImage`),
  uploaded the same way, and required: with nothing dropped `generate()`
  refuses before uploading anything.
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

**A video job previews as ONE frame, and that is the backend, not this pane.**
[his] *"why will sampling previews only show the first frame from the
generation"* — measured 2026-08-06: painter's side is fine. Three synthetic
frames pushed through `_on_preview` (red, green, blue) were each grabbed off the
real pane offscreen, so the `image://livepreview/<tick>` URL does reload per
frame and the newest one is what is drawn. What arrives is the same picture:
`latent_preview.Latent2RGBPreviewer.decode_latent_to_preview` does
`x0 = x0[0, :, 0]` for a 5-D latent — the clip's first frame — and the previewer
API hands back exactly ONE image per step, so no client can be shown more (its
own web UI included). `--preview-method auto` resolves to Latent2RGB, and the
`taesd`/`taehv` route is not a way out: `TAEHVPreviewerImpl` slices
`x0[:1, :, :1]`, one frame again, and needs a `models/vae_approx/taehv*` that is
not installed. **Anything more would be a local patch to
`/home/lam/comfy/latent_preview.py`**, i.e. a fourth local commit on a checkout
that is maintained by rebasing onto upstream tags.

So the pane says `sampling - frame 1 of the clip, N updates`. The COUNT is the
observation beside the claim (docs/DESIGN.md §10.6): the frames all look like
the same picture, so the number is the only thing that distinguishes a live
stream from a dead one. If it climbs, previews are arriving and you are
watching frame 1 denoise; **if it sticks at 1, that is a different bug** — the
place to look is `comfy.py`'s `_on_binary` (it drops anything that is not
BinaryEventTypes.PREVIEW_IMAGE = 1, and ComfyUI sends the newer
PREVIEW_IMAGE_WITH_METADATA = 4 shape instead to any client that announced
`supports_preview_metadata` in the websocket handshake; painter announces
nothing, which is what keeps it on the old shape).

Two things about the backend, both worth knowing before debugging an empty pane:

- **ComfyUI sends nothing without `--preview-method`** (its default is
  `NoPreviews`), which `home/prog/painter.nix` now passes — but the unit is
  `X-RestartIfChanged=false`, so a backend that was already up keeps running
  without it until it is restarted. That is why the pane says so once a job has
  been going 45s with no frame, rather than "waiting" forever.
- **A video preview is a STILL FRAME PER STEP, not a moving clip.**
  `Latent2RGBPreviewer` takes `x0[0, :, 0]` out of a 5-D latent — the first
  frame — and Comfy's own web UI shows the same thing. `MiniMaxH3AV` carries the
  RGB factors, so `auto` works with no extra files; the `taehv` route (a real
  decode rather than the RGB approximation) needs `models/vae_approx/taehv*`,
  which is not installed, and is still one frame at a time.

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

**The clipboard goes through `pylib/clipfile.py`, never `QClipboard`.** A
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
he had just made. A PNG carries the whole job that made it, and which part you
want is a decision (§7.1: everything is still right-clickable). The three
actions live on the window (`injectPrompt` / `injectParams` / `injectAll`), so
the menu has no logic of its own; `injectParams` restores size as **aspect +
MP**, never raw pixels (see above).

Because a left-click LAUNCHES something, `tools/ui-test.py` replaces
`main.subprocess` with a recorder — it spawned two real `viewer` windows on his
desktop the first time that click was exercised, which is the one thing a
harness here may never do.

## The window comes back the way it was left

Persisted through `Prefs` (`~/.local/state/painter/prefs.json`): window size,
which view, the split ratio, the prompts and every number in `gen`, the selected
model, and each panel's collapsed state (`Panel.persistKey`). Two traps:

- **Writes are debounced** (700ms) — `gen` changes on every keystroke.
- **`applyDefaults()` is guarded by `defaultsFor`.** The startup selection fires
  `modelChanged`, and without that guard a family's defaults would overwrite the
  session that had just been restored, every launch. It holds the name of the
  model whose defaults `gen` reflects; a restore sets it to the remembered one.

The divider between the panes is dragged (`splitRatio`, saved on release,
double-click to reset), clamped so neither side starves — the same shape as
filer's splitter.

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

141 checks over the real `qml/Main.qml` under `QT_QPA_PLATFORM=offscreen`, with a
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
dragged height), the video column (a synthetic video family written into the scratch
root and removed again — a fully paired model sorts to the top of the list and
would otherwise be every later test's selection), save-and-restore through a
SECOND window on the same prefs file, that
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
gallery (`~/Pictures/painter/out`, prefix `painter_cov_`) — delete them after.

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
writes it to book's own `OUT_DIR`, so book's gallery shows what book made.

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

Anima's prompts are flattened to a single line on the way out
(`prompt_transform: single_line`) while the editor keeps your line breaks;
everything else is passed through verbatim (Krea 2's `<think>…</think>` prose
must not be touched). The string actually sent is what gets recorded in the PNG.

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

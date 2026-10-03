# painter — ComfyUI desktop client

Read [the shared app guide](../AGENTS.md) for desktop detection, native controls,
live-source packaging, and isolation. `home/prog/painter.nix` owns the wrapper
and backend service integration; `main.py`, `qml/`, `families/`, `graphs/`,
and `tools/` are live app source on both hosts.

The private [historical reference](../../docs/agents/painter-legacy-reference.md)
has an indexed record of detailed implementation rationale and older findings.
It is not a current runbook: backend versions, model counts, performance figures,
and some launcher descriptions are historical. Check source and current
read-only state before using them.

## Owners and test routing

| Area | Owner | Focused harnesses under `tools/` |
| --- | --- | --- |
| Window/actions/settings | `qml/Root.qml`, `main.py` | `ui-test.py` |
| Gallery, filtering, thumbnails | `gallery.py` | `ui-test.py`, `gallery-bench.py` |
| Model identification/pairing | `fingerprint.py`, `registry.py`, `families/` | family-specific tests |
| Graph construction | `graph.py`, `registry.py`, `graphs/` | family-specific tests, `validate-graphs.py` |
| Saved generation settings | `userprefs.py` | `prefs-test.py` |
| Wildcards/prompt representation | `main.py`, QML prompt controls | `wildcards-test.py`, `promptdoc-test.py` |
| Tag completion | shared `pylib/boorutags.py`, QML prompt controls | `anima-test.py` |
| Backend transport | `comfy.py` | inspect matching client/UI stubs |
| Book launcher/forward/mounts | `tools/comfy-tunnel.sh` | `tunnel-test.sh` is a live integration test |
| Retained resources | `tools/resource-fixture.py` | synthetic offscreen fixture |

Read each harness before running it. `validate-graphs.py` contacts a backend;
`coverage-test.py` actually loads models, generates outputs, and writes a real
gallery by default. `tunnel-test.sh` can start services and create forwards or
mounts. They are not routine isolated smoke tests. Use stubbed/offscreen tests
for local app changes and obtain any required authorization for live effects.

## Session shells and controls

Verify the desktop using the root guide. `Root.qml` is an Item shared by
Hyprland's `Main.qml` Window and Plasma's native QMainWindow/QQuickWidget shell.
Keep Window-only operations in wrapper signals, a window Connection, or
`root.Window.*`. Native backgrounds and controls follow the shared app guide.

One actions table owns menus/toolbars; `tbButtons` filters rows marked `tb:`
for Hyprland. Missing targets disable actions. Plasma QAction shortcuts disable
duplicate QML shortcuts with `!root.plasma`. ResultsPane/ParamsPane explicitly
forward child properties; extend the forwarding blocks with new properties.
Parameters and results share a scene/splitter, not a QDockWidget. F7/showParams
must switch view when the width cannot hold both panes.

Keep the content background MouseArea at `z: -1000`: unclaimed presses must not
turn into Oxygen window drags. Native chrome retains its own dragging. Under
Plasma, QueueBar has zero height and statusLine/statusProgress carry its state.

Use `root.set`, `root.setMs`, and `root.clone` to replace generation objects;
mutating and reassigning the same object does not notify bindings. Controls
emit edited/picked rather than assigning bound values. PromptBox's syncing flag
separates programmatic updates from edits. TextEdit does not support Text-only
lineHeight properties. Escape releases a text box without cancelling a job.

Shared TextButton, ToolTipArea, WheelNotch, Kinetic views, spelling, context
menus, and scrollbar contracts apply. Native Plasma controls follow the native
style; custom Hyprland controls do not impose that style on Plasma.

## Gallery, output, and layout

`gallery.py` owns discovery, deduplication, filtering, and bounded workers;
`main.py` re-exports public names. `_all` and `_rows` share row dictionaries,
and QML indexes refer to filtered rows. Filter all words against cached filename
and prompt metadata. Peer outputs merge with local outputs without duplicate
rows; prefer the local copy. An unavailable peer cannot block local discovery.

Tiles use cached JPEGs, not full outputs. Still thumbnails have a bounded LIFO
worker queue; video posters are requested after delegate dwell. Use scan-time
mtime/size cache keys and never stat sshfs paths on selection/scroll paths.
Gate hidden PreviewPane media sources on `pane.open` to stop decoders.

`ParamsPane.builtinOrder` and saved sections define one order across modes.
Move ListModel rows without replacing dragged delegates. `sectionVisible` owns
visibility gates; deriving visibility from an effectively hidden child can latch
it false. Collapsed sections retain pinned interactive rows. Park others in
stash without overwriting their visibility bindings or using a null parent.
Repeater-containing rows use `selfHides` and remain first in their section.

Selection is the single current-output cursor (`selOne`). Return/double-click
enters View; Escape leaves it; Back/Forward switch Browse/View without changing
selection. PgUp/PgDown walk outputs only in View. Open in Viewer is separate.
Stills zoom/pan; clips disable zoom. Generate stays enabled while busy so jobs
can be queued. Actual decoded dimensions/duration drive output information.

Shared CompareView is available for an edit with a resolvable source. Preserve
before-images under `.before/` outside gallery globs; resolve the saved copy,
recorded path, then output-root filename. Changed action IDs require native
chrome rebuilding. Completed stills may copy pixels through `clipfile.py
--image-only`; sampler frames and videos do not.

Keep native drag payloads valid for stills, clips, and multi-output collages.
Muted video copies are cached derivatives; never overwrite the original or
insert the derivative into generation history. Output PNG/MP4 metadata uses
the shared `pngmeta.py`/`mp4meta.py` implementations. Metadata failure must not
discard an otherwise valid downloaded output.

## Models, prompts, and graphs

`registry.MODES` owns anime/real/edit/video shortcut choices; QML does not choose
model files. A mode selects a model, disables manual selection while active,
and stays visible but disabled if unavailable. Restore mode after model rows
arrive; do not replace the user's preference with the newest model.

`fingerprint.py` identifies tensors/headers instead of trusting filenames or
GGUF architecture strings. Use current ComfyUI detection code when signals
change. Structurally identical VAEs may need a hash/name fallback; LoRA matching
uses namespace aliases and base-model compatibility. Unknown files remain
visible and user assignments persist separately.

Families are declarative under `families/`; shared graph kinds live in `graphs/`.
Adding a family normally extends data, while a new pipeline kind can require
code. Validate node contracts against `/object_info` and report unavailable
family reasons explicitly. Image, edit, and video are separate pipelines;
do not claim a setting applies when that graph never consumes it.

Edit dimensions come from the source image unless the user requests a scale
budget. Upload input/reference frames to the backend rather than assuming its
filesystem matches the client. Video duration must go through the registry's
valid frame-count conversion. Use per-family prompt transforms and keep tag
storage underscore conventions distinct from displayed prompt spaces.

Wildcards expand from app-local `wildcards/*.txt` after assigning the concrete
per-job seed. Selection is deterministic for `<seed>:<name>` across both boxes;
missing/empty files leave tokens literal. Store expanded conditioning in output
parameters and literal text in `prompt_boxes` for lossless injection. Prompt
pills/completion must not reformat arbitrary user text.

## Headless generation and saved preferences

`tools/smoke.py` is a real generation client used by Chatter, not automatically
a harmless test. Its `--dry-run` builds a plan without submission/uploads.
Mode/model selection, aspect/budget, frames, and arbitrary `--set KEY=VALUE`
parameters must use the same registry/graph semantics as the GUI.

`userprefs.py` reads saved per-model defaults beneath explicit caller overrides.
The last positive prompt is not a default. Seeds follow random/reuse/fixed
policy unless explicitly overridden. Explicit aspect/budget replaces remembered
dimensions; only compatible LoRAs carry. Mirror what each mode actually submits
rather than forwarding an entire remembered image block into edit/video.
Never write the window's preferences from the headless client.

Machine-readable progress/result lines describe the graph actually run. Stream
them while the process runs, not only at exit; progress is a high-water mark
rather than node-order progress that can move backwards.

## Backend, hosts, and ownership

ComfyUI is an external checkout/venv, not bundled app source. Inspect that
checkout's current status and instructions before any upgrade; do not execute
historical rebase/dependency-cleanup recipes. Its model symlink can target real
user data, so upstream placeholder changes need an ownership review.

Keep ComfyUI loopback-only. Book reaches top through the authenticated forward
in `tools/comfy-tunnel.sh`; do not expose port 8188 on the tailnet. The normal
GUI launcher tries `top` before `top.local` and waits for the local forward to
bind, while the app reports backend warm-up asynchronously. The separate
`COMFY_ENSURE_BACKEND` headless path waits for a serving backend. A bound port
alone is not evidence that ComfyUI serves requests.

Backend lifecycle uses renewable warden client leases shared across windows
and hosts. Closing one window must not stop another client's work. Preserve
reservation/refusal/status reporting and asynchronous unit commands. On book,
backend commands follow the resolved SSH/control route; do not target a
nonexistent local top-only service.

Book uses read-only model/peer-output mounts where available. Model discovery
reads tensor headers off the GUI thread and retries while mounts settle.
Only release mounts/forwards owned by the current launcher. Missing model or
peer roots must be reported without turning local history into a failure.
Current roots, overrides, and lifecycle details belong to the launcher/module
source, not copied inventory numbers.

## Isolated verification and applying changes

`tools/ui-test.py` uses offscreen Qt, synthetic models, a stubbed client, and
neutered backend commands. Preserve those isolation seams; QML warnings fail
its run. Use scratch preferences, output/cache roots, and stub clipboard,
notifications, warden, transport, and unit control. `tools/resource-fixture.py`
uses a synthetic gallery and never acquires those live seams.

Apply the root/shared session guards and remove inherited display/compositor
sockets. Never source an app wrapper, launch the user's Painter, or run a real
generation merely to verify documentation/UI plumbing. Dependency or packaging
changes require the appropriate host rebuild; Python/QML changes wait for the
user's next launch.

When inference verification is required, use a separate loopback Comfy process
with scratch input/output/user directories and an explicit `--database-url`,
a warden lease, and a memory cap. Never submit smoke jobs to the user's active
Painter queue; follow the root rules for running inference alongside user work.

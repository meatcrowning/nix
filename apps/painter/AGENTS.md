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
| Gallery, filtering, thumbnails | `gallery.py` | `ui-test.py` (`PAINTER_UI_ONLY=gallery`), `gallery-bench.py` |
| Model identification/pairing | `fingerprint.py`, `registry.py`, `families/` | family-specific tests |
| Graph construction | `graph.py`, `registry.py`, `graphs/` | family-specific tests, `validate-graphs.py` |
| Saved generation settings | `userprefs.py` | `prefs-test.py` |
| Wildcards/prompt representation | `main.py`, QML prompt controls | `wildcards-test.py`, `promptdoc-test.py` |
| Tag completion | shared `pylib/boorutags.py`, QML prompt controls | `anima-test.py` |
| Backend transport | `comfy.py` | inspect matching client/UI stubs |
| Submission lifecycle/output saves | `submission.py`, `output_save.py`, `media_work.py` | `submission-test.py`, UI `drag`/`notifications` |
| Recovery/ownership | `comfy.py`, `job_journal.py` | `transport-test.py` |
| Remote catalogue | `catalogue.py`, `catalogue_index.py`, backend node | `catalogue-test.py`, `catalogue-gallery-test.py` |
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
Parameters and results share a scene/splitter, not a QDockWidget.
Compare Settings reuses the normal parameter form in a sibling overlay matching
its width, including the layout editor. GTK shares `unity_params.ParameterForm`;
Qt mounts `ParamsPane` in an isolated context through `comparison_qt.py`. Keep
settings, layout state, LoRAs and preference writes separate from the live panel.
Comparison edits are temporary; model/asset selection and generation remain in
the current panel. Never resize the viewport or apply settings when comparing.
`parameter_compare.snapshot` projects metadata with the saved model’s defaults
for unrecorded fields, labelled in the panel; never substitute current settings. Cancel uses stop-and-save; its Hard stop
context action interrupts without decoding. F7/showParams must switch view when
the width cannot hold both panes.

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

## Unity frontend

On top's native Unity session, `main.py` selects `unity_engine.py`: an offscreen
Qt controller with one private, per-window Unix socket. `unity_frontend.py` and `unity_widgets.py`
run with Python 2.7 / GTK 3.6 through `unity-quantal-runtime`; keep it compatible
with that runtime. No modern Qt/Python libraries enter the historical process.
Book retains its existing desktop faces; the original Unity runtime is x86-only.

The controller still owns generation, model discovery, gallery caches, metadata,
and backend leases. The GTK adapter translates image/edit/video controls to the
same contracts as `Root.qml.submit`; keep them in sync. Both faces use Painter's
per-model preferences. GTK must merge unrelated preference keys, retain seed
policy, and finish its final save before closing. Desktop opens use the saved
launch environment, never the engine's offscreen environment.

Aspect integers plus the MP budget use the controller's family-specific `dims`;
never derive the saved ratio back from rounded pixels. Prompt bottom handles
share `prompt.posH`/`prompt.negH` with QML; GTK's system editor uses
`unity.systemH` with the Qt system editor. Layout canvas height uses
`layout.canvasHeight`, and its region list uses `layout.regionListHeight` (zero
means fit the rows). Region prompt height uses `layout.regionPromptHeight`.
Unity's sidebar width uses `unity.sidebarWidth`. Save
handle sizes on release. Browse and View share one image
widget and selection. Unity places history to the right of the preview, with
its width saved as `unity.historyWidth`; `unity.previewWidth` is the fallback
for older preferences. Still zoom renders a viewport-bounded crop with a surrounding pan margin; transient sampler/video
frames cross the socket as bounded images. Clip decoding stays
in the modern engine, with no audio output attached; clear the media source
on selection changes and window close. Keep frame polling separate from
gallery/settings snapshots. Unity history scrolls through a maximum 180-row
window, requesting previews near the visible rows; the GTK decoder queue and
image cache each cap at 64 entries. Keep paging independent of the selected
preview and preserve scroll position when replacing the window.

GTK 3.6 text history lives in `text_history_gtk.py`, with a separate bounded
stack per focused editable widget. Global Edit Undo/Redo and Ctrl+Z /
Ctrl+Shift+Z target that widget; model/region loads must not carry text history
into a different document. Qt uses the focused editor’s native history.

Use real GTK widgets, Ambiance, server decorations and the original appmenu
exporter. `lib/unity-quantal/assemble.py` owns that runtime dependency. Verify with
`tools/unity-test.sh UNITY_PACKAGE` (under this app): a private PID/mount/network
namespace, Xvfb and D-Bus, scratch home and synthetic controller data. It checks
GTK controls, socket submission, output restore, persistence and global-menu
registration without a live backend. `PAINTER_UNITY_SHOT=/tmp/file.png` retains
an isolated fixture image. Never run its inner Python scripts on the host.

## Gallery, output, and layout

`gallery.py` owns discovery, deduplication, filtering, and bounded workers;
`main.py` re-exports public names. `_all` and `_rows` share row dictionaries,
and QML indexes refer to filtered rows. Filter all words against cached filename
and prompt metadata. Peer outputs merge with local outputs without duplicate
rows; prefer the local copy. An unavailable peer cannot block local discovery.
Startup scans run on a worker and publish local history before waiting for
peers; merge outputs that complete during the scan and retain the live
generation row.

Tiles use cached JPEGs, not full outputs. Still thumbnails have a bounded LIFO
worker queue; video posters are requested after delegate dwell. Use scan-time
mtime/size cache keys and never stat sshfs paths on selection/scroll paths.
Gate hidden PreviewPane media sources on `pane.open` to stop decoders.

`ParamsPane.builtinOrder` and saved `sections.v2` define one order across modes.
Prompt, Latent, Model, Sampling and Regions are separate sections on Qt and GTK.
Prompt owns wildcards, positive/negative text and MOSS scene medium/palette.
Latent puts aspect/megapixels on its first row and seed controls on its second;
Regions owns the spatial editor.
The v2 order starts with Prompt and Latent; optional model/input panels keep their
family gates.
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

`submission.py` freezes form/model/LoRA state before asynchronous work and validates
the whole batch before submission. GUI and headless paths share `build_job`.
Warden reservation tokens belong to submissions; cancellation invalidates delayed
callbacks. `output_save.py` bounds transfers and metadata workers, publishes by
atomic rename, and acknowledges transport jobs only after saves finish. Failed
saves remain in the recovery journal. Derivative preparation never waits on the
UI thread; drag payloads activate when ready. Preview decoding retains only the
active and newest frame.

## MOSS token inspection

`moss_inspect.py` owns asynchronous token requests and selected-output maps;
`moss_data.py` owns the bounded versioned `paHm` PNG chunk. Keep that chunk
through metadata rewrites. Prompt probes debounce 350 ms, reject stale replies,
and paint alternating token backgrounds without vertical dividers or changing
text or undo; native selection stays above the backgrounds. `token_style.py`
shares the decoration colours across Qt/GTK. Counts use the unweighted
MOSS tokenizer before wildcard/layout compilation and exclude template tokens.
The tokenizer endpoint uses the existing backend connection; it never loads GPU
weights or starts a backend on its own.

`comfy_nodes/painter_moss.py` captures sparse layer-4/8 image-to-text attention-weight
maps from the last positive evaluation before actual sampler callbacks in the
quarter-start window, retaining the middle-third capture count and stride of three,
with capture provenance saved alongside the maps. Image-query rows softmax over
all image and text keys before retaining text columns, averaged across heads.
Chunked queries bound temporary logits; capture allocations pause Comfy’s memory
compiler when available. Maps average raw layer probabilities, apply one separable
binomial smoothing pass before token normalization, and retain native resolution up to 128 per axis. Long prompts
reduce map dimensions to keep planes within 20 MiB and the packet within 24 MiB;
the reader still accepts version 1/2 maps. Capture v5 marks attention weights;
older feature-similarity maps retain their recorded method. Version 3 packets also
save word planes formed by summing raw token-piece probabilities before
normalization, and per-token
mean pairwise spatial correlation across captured layers/steps on at most 16×16
pooled maps. This agreement is consistency, not correctness or confidence. Capture runs
during ordinary MOSS generation when both nodes are advertised. PPM keeps
its existing sampler because it changes tokenization/attention. Existing files
without maps cannot display a heatmap. The toolbar token picker and matching
positive-prompt hovers share the selected token. Entry defaults to All tokens:
mean the saved descriptive prompt-token scores (excluding layout structure)
before a single 5–95% contrast stretch and
thermal colour mapping; stored per-token normalization cannot recover raw model
activity. Hover temporarily shows one token, then restores the dropdown choice.
Grid comparison arms two prompt/region clicks, validates each against saved tokens,
and exports a labeled five-panel PNG to the platform Pictures directory in a worker.
The original spans the left side with its aspect ratio preserved; the right 2×2
contains All tokens and Hottest/coldest above the two picked maps. Heatmap panels
retain source resolution; the original is enlarged to match both rows.
A title row uses the saved output’s model name and “token attention heatmaps”
for saved attention-weight captures, or “token association heatmaps” for older maps,
with equal small gaps above its ink and below it to the first column-header ink.
The Original output header includes two smaller truncated lines of the saved scene
prompt; its full text is retained in `PainterComparisonPrompt` PNG metadata.
Other headers fit two small lines of scored eligible words. Ranked headers omit
words annotated on their panel; selected-map headers rank positive Pearson spatial
correlation, and All tokens ranks word-map means weighted by its displayed aggregate.
Area neighborhoods scale with each map axis (radius 3/64, center separation
12/64 in normalized coordinates). Hot labels show local association percentages; cold labels show regional means. Over-image percentages use half
the word-label font size. `PainterExpandedLists` records displayed entries and score
definitions; these are relative map measurements, not probabilities or semantic similarity.
Exports use saved raw-grouped word planes for picked maps and the area panel;
legacy files fall back to averaging saved normalized token planes. Picked headers list the word and its pieces with singular “token”
or plural “tokens”; `PainterWordGrouping` preserves source indices and offsets.
The all-token reference and interactive viewer retain their token-based maps.
The area panel ranks up to four hot and two cold neighborhoods. Cold labels
use the local winning word; their percentages are mean eligible-word scores.
Red/blue area labels have separate ranks.
The all-token export stacks scene-prompt words at the top left with circular links
to their saved word-map peaks, breaking ties by local mean then proximity to
the tied-cell centroid. Words use tight dark backings matching the ranked labels,
with no glyph outline. All prompts use a 20 px font and a fixed 26.5 px row
pitch, continuing down then right in columns sized to their widest word. Words
align to each column’s left edge. Selected-map header
lists begin with a bold “is most closely associated with”.
`moss_rank.py` excludes punctuation and English function words using saved word
spans (retaining content-word subpieces, labeled with their containing word).
For compiled layouts, eligible maps must overlap descriptive string values:
summary caption/meta/palette and item caption/text/tags/palette. JSON field names,
region types, coordinates and other structural values are excluded from automatic
rankings and nearby-token lists; ordinary prose retains meaningful numeric text.
Area labels maximize eligible-token
mean within each neighborhood and deduplicate containing words, plurals and close spelling variants;
duplicate hot-area winners are skipped, never relabeled with weaker tokens. These are
relative saved-map scores, not absolute activity. Ranking methods and full token
identities live in PNG metadata; panels show titles and token labels only.
Output changes or leaving heatmap mode cancel unfinished picks. `moss_grid.py`
uses the viewer's mask renderer; exports never alter the source or run inference.
Compiled layouts map scene-caption
positions through JSON escaping to saved token offsets. Mismatched drafts never drive
saved maps. Heatmap mode leaves history accessible and survives output changes.
Qt paints transparent masks over the existing image, preserving fit/zoom and
keeping it visible while maps load. `moss_inspect.py` caches at most 64 small RGBA
masks; token changes never decode or save the full output.
Map loading has its own worker, independent of grid exports, and caches up to
three files/24 MiB of saved planes by path, modification time and size.
Word grouping and full rankings are reused for repeat exports; summed-area
tables compute neighborhood means without repeatedly scanning each box. Caption-offset
mapping is cached and resolved in one pass; nearby-list notifications are separate
from mask changes so individual previews do not rebuild lists or prompt highlights.
Image-hover exploration in both preview/view maps the pointer through fit/zoom/pan
and samples at most every 40 ms. Rank eligible tokens by neighborhood means,
with radii scaled as 1/64 per axis. Show the top six in an interactive tooltip
and their mean thermal map. Reuse
combined masks by token set within the same 64-entry cache. Tooltip clicks select
one token; leaving restores the dropdown choice. Clicking the image holds its
area/list until a token is chosen or Resume hover is pressed. During grid selection,
a held-list hover previews that individual token and leaving restores the combined
map. A click fills the next comparison slot, then releases the hold; prompt
clicks remain an alternative. Leaving heatmap mode or changing outputs clears holds. Prompt/region highlights use
saved offsets (UTF-16 in Qt), reject mismatched drafts, and never alter text/undo. Toolbar tooltips distinguish loading, missing maps,
capture failure and saved format/layers; selected tokens include capture agreement
when available. GTK receives small
mask PNGs in immediate socket replies and composites them over its decoded image.
Region prompt boxes share the debounce, count and decorations. Region hover uses
IDs in saved `painter.moss_layout` metadata, skipping disabled regions when mapping
to compiled `items`; duplicate captions and current reordering never choose a map
by text alone. Old outputs without saved region IDs retain the dropdown picker.
Displayed maps are normalized experimental associations, not causal
word attribution; never infer maps for old images from a current prompt.
Verify capture/scoring with the CPU-only `tools/moss-capture-test.py` and
`tools/moss-capture-tensor-test.py` (Comfy Python, CUDA hidden), and
`tools/moss-attention-probe.py --comfy /path/to/ComfyUI` (random-weight CPU
model, no semantic accuracy claim), plus
`tools/moss-inspection-test.py` offscreen, `tools/moss-test.py`, and
the Unity harness. Backend node installation is in `home/prog/painter.nix`. Both the MOSS node
and its partial-stop sampler callback link to live repository source; changing
those links requires a host rebuild. The sampler advertises its observer contract
so an outdated backend fails clearly instead of silently dropping maps.
For accuracy experiments, `tools/moss_quality_experiment.py` is an isolated-only
node requiring `PainterSamplerCustom`. It retains raw 64×64 captures by layer
and sampler step; `tools/moss-quality-analyze.py` scores image-only polygon
annotations with separate selection/held-out scenes. Never load that node into
the user’s backend or infer semantic accuracy from plumbing tests.

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
per-job seed. Selection is deterministic for `<seed>:<name>` across both boxes and region prompts;
missing/empty files leave tokens literal. Store expanded conditioning in output
parameters and literal text in `prompt_boxes` for lossless injection. Expand
region captions in a copy before layout compilation; saved `moss_layout` retains
the original tokens for restore/comparison. Exact wording stays literal.
Wildcard buttons open hover cards with per-line checks. The controller owns
`wildcards.json` under Painter’s state directory, independently of UI preferences.
Line text and occurrence preserve checks through file reorders; new lines default
on. Each job freezes full `wildcard_options` (texts and checks) into metadata;
Use Settings restores that snapshot, while comparison only displays it. Referencing
an all-disabled wildcard fails clearly; missing wildcard names remain literal. Prompt
pills/completion must not reformat arbitrary user text.

MOSS layout documents live in the per-model `moss_layout` setting. `moss_layout.py`
owns normalized geometry and compilation to centered pixel coordinates;
its prompt importer recovers pixel drafts and compiled bbox conditioning into
scene text and editable regions for paste, output restore and comparison.
`layout_ui.py` owns editor actions, with native GTK and Qt adapters in
`layout_gtk.py` and `layout_qt.py`. Only `registry.build` compiles conditioning,
using the actual output dimensions and current positive prompt as scene caption.
Scene medium/genre and palette enter the structured prompt even with regions
disabled or absent. The region toggle gates region captions/geometry and layout
composition only; with no scene values and regions off, send the plain prompt.
Keep reference underlays, groups, locks and guides out of model-facing JSON.
The Regions section contains the spatial editor. Its Region tab contains its
list, canvas and region fields; Scene and Canvas retain their remaining settings.
Shared layout toolkits expose a separate scene root for Prompt’s medium/palette
controls, with one document and undo history across both sections.
GTK embeds `layout_gtk.py`; Qt Quick renders the `layout_qt.py` descriptor tree
through `LayoutNode.qml`.
The Add toolbar ends with layout-generation and preview toggles, each with
distinct on/off icons. Preview visibility never changes generation settings.
Add arms one box-drawing gesture, then returns to selection. The toolbar type
selector changes selected regions, or the next added type when none are selected.
Drag on empty canvas to box-select; moving a selection keeps its spacing.
Region rows update in place so prompt edits preserve list scroll position.
List dragging reorders unlocked rows; locked rows cannot move or be crossed.
Locks prevent canvas selection and geometry edits, including list-selected
regions. Clicking a selected locked region on the canvas deselects it on press
before any drag or resize can begin. Locked preview layers are grey and clipped
beneath unlocked regions; keep occlusion in compositor clips so moving a foreground region does
not rerasterize the locked background.
Draft edits persist immediately, including incomplete regions; generation validates required captions.
Region tags use the inline count and Auto controls. Region, positive and negative
prompts have a token limit, Write and prompt-only Undo. Positive and negative
writers use separate instructions; MOSS adds concise prompting guidance rather
than loading the entire user guide. Prompt output is capped in llama, with
any incomplete trailing sentence (or negative-list item) removed. Undo restores only the last generated
prompt when its text is still unchanged; it must not roll back other fields.
`tagger.py` always runs inference on top: locally there, or over Book’s
existing backend SSH route using `painter --prompt-worker`. That headless entry
point loads no GUI or image backend and uses top’s packaged CPU-only llama/model
paths from `home/prog/painter.nix`. There is no local fallback on Book. Empty
prompt boxes request a fresh idea (or general negative exclusions). Stop after
N complete unique tags; retain manual edits if the region/model changes during inference. The CPU worker has
its own single-job lock, RAM check and resource/deadline limits; it must not
acquire or release GPU backend leases. It exits after each request.
The canvas caches independently positioned raster layers with a bounded byte
budget; pointer motion must not rebuild text or reference images for a move.
Use `tools/tagger-test.py` offscreen for streaming/cancellation and worker tests.
Verify geometry/compiler and Qt controls with `tools/layout-test.py --qt`
offscreen; `tools/unity-test.sh` includes the native GTK layout checks.

## Agent control of a running Qt window

Plasma and Hyprland windows on both hosts expose `agent_control.py` through a
private, per-window Unix socket. `tools/control.py` is the stdlib-only client;
it never launches Painter or the backend. New source takes effect on the next
Painter launch. Unity retains its existing GTK/controller socket.

Run from the repository root:

```sh
python3 apps/painter/tools/control.py list
python3 apps/painter/tools/control.py state
python3 apps/painter/tools/control.py describe
python3 apps/painter/tools/control.py select --model MODEL_FILENAME
python3 apps/painter/tools/control.py apply /tmp/painter-setup.json
```

With several windows, pass `--socket PATH` before the command, using a path from
`list`. `describe` reports model/mode/LoRA choices, editable setting names and
bounds, and sampler options. `select --mode MODE` is the mode-button equivalent;
selecting a model directly clears the mode. Select first, then read its state.

An apply document merges only supplied settings; image and LoRA lists replace
those slots. For example:

```json
{"settings":{"positive":"A red fox in snow","negative":"blur","seed":42,
 "steps":20,"aspectW":3,"aspectH":2,"megapixels":1},
 "input":"/absolute/path/reference.png","references":[],"loras":[]}
```

Settings use the visible form's names from `describe`. Width/height are derived:
use `aspectW`, `aspectH`, and `megapixels`. `ms` merges nested sampling controls;
`moss_layout` accepts a layout document. `input` is the primary/edit/first-frame
image; `last` is the final video frame; `references` contains additional images.
Paths must exist on the host running Painter. Empty strings clear image slots;
empty arrays clear additional references or LoRAs. LoRA rows take `name`,
`strength`, and optional `enabled`. Relevant reference/frame toggles are enabled
when attaching images unless explicitly overridden in `settings`.

`apply -` reads stdin. An optional top-level `model` asserts the expected current
model; the client reads it immediately before applying when omitted. Unknown
fields, invalid settings/assets, and stale models fail before changing the form.
Apply does not generate, focus/raise the window, or use the clipboard.
`generate` is a separate explicit command using the visible form's submission
path; its response acknowledges the request, not completed generation.

Protocol v1 uses newline-delimited JSON: `op` is `state`, `describe`, `select`,
`apply`, or `generate`. Raw apply/generate requests require `model`. Replies are
`{"ok":true,"state":...}` or `{"ok":false,"error":"..."}`. Discovery scans
`$XDG_RUNTIME_DIR/painter-agent-UID-*/control.sock` (private temporary directories
under `/tmp` if no runtime directory exists), ignores stale endpoints, and never
chooses arbitrarily between windows. Closing a window removes its endpoint.
Verify with `PAINTER_UI_ONLY=agent` in the isolated UI harness; add
`PAINTER_UI_NATIVE=1` for the native Plasma shell. Tests use scratch sockets and
stub submission; never send verification requests to a user's live window.

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

GUI jobs journal beneath the Painter state directory's `jobs/`; advisory locks
exclude live windows from recovery. Reconnect reconciles queue/history; uncertain
submissions are never blindly retried. Stop requests require the backend's
`/painter/control` ownership capability; an old backend refuses safely. Backend
PNG saves receive Painter metadata directly, with frontend enrichment retained.

Book defaults to the versioned loopback catalogue for model fingerprints, output
metadata and thumbnails. Cached catalogues remain available offline; full-size
output access still uses the peer mount. `PAINTER_CATALOGUE=0` selects legacy
model SSHFS discovery. Backend node installation requires a Top rebuild and
takes effect on its next start. `tools/backend-manifest.py` records environment
revisions and checks package/node availability without importing GPU libraries.
`tools/capture-bench.py` requires a separately identified, memory-capped backend
with scratch input/output/user/database paths and its own warden reservation.
The `moss_capture` graph option defaults true; benchmarks never change defaults.

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

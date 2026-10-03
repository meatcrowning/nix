# filer — Qt/QML file browser

Read [the shared app guide](../AGENTS.md) for desktop detection, controls,
packaging, and isolation. `home/prog/filer.nix` wraps the live `main.py` source
for both hosts. Python/QML edits need no rebuild or agent-driven app restart.
Its standalone flake is used by `run.sh` for a development shell; do not assume
`nix run` packages all sibling/shared imports.

The private [historical reference](../../docs/agents/filer-legacy-reference.md)
retains detailed rationale, old measurements, and incident notes with a topic
index. It is not a current operating runbook. In particular, its old book
portal/session failure is an observation, not a permanent host property.

## Source and verification routing

| Area | Owner | Focused harnesses under `tools/` |
| --- | --- | --- |
| Window/split/chrome | `qml/Main.qml` | `split-test.py`, `nav-test.py` |
| Browser selection, tree/grid, drops | `qml/BrowserPane.qml`, `qml/PreviewTile.qml` | `drop-test.py`, `dragsource-test.py` |
| File operations/reporting | `main.py` | `fileop-test.py`, `action-menu-test.py` |
| Metadata search | `MetaSearch` in `main.py` | `find-test.py` |
| Thumbnails and video posters | `main.py` | `thumb-test.py` |
| Viewer return selection | `main.py`, shared `pylib/handoff.py` | `viewer-select-test.py` |
| Picker and portal | `pick.py`, `portal.py`, `qml/PickerBar.qml` | `portal-tests.sh`, `pick-test.py` |
| Remote paths | `main.py` | `remote-test.py` |
| Conversion/clipboard derivatives | `videoconv.py`, `imgconv.py` | `imgconv-test.py`, `strip-audio-test.py` |
| KDE Connect | `phone.py` | `phone-test.py` |

Read each harness's setup before use; isolate all writable roots and stub
notifications, clipboard, SSH, file operations, and external launchers. A test
name alone does not prove isolation. Do not open a live file dialog to test a
portal response; use its private-bus harness.

## Panes, selection, and navigation

`BrowserPane.qml` owns the browser; `Main.qml` owns its chrome and split layout.
The trailing pane is a Loader. Reorienting a split keeps both panes alive and
retains their directories. Use the same split ratio on either axis, preserve
per-axis minimums, and never send a zero-size rectangle to hyprvtb.

`win.pane` is the focused pane: all address/sort/action/footer chrome follows
it. Clicking a pane claims focus. Operations and external changes refresh every
pane; `DirWatch.setDirs` holds a keyed union and releases each destroyed pane's
key. Only the leading pane persists normal directory/sort/hidden preferences;
the trailing pane persists its split directory. A restored split focuses the
leading pane; a newly opened split focuses the new pane.

Pickers never split. Preserve F3/Shift+F3/F6 routing and the restored default
orientation for older state. Narrow columns must release width, not merely
become invisible. Shared Kinetic views and navigation helpers own scrolling
and Back/Forward behavior.

Viewer opens receive a launch-time `--order` snapshot and a separate live
`--select-back <socket>:<pane>` token. The listener is per process and the token
uses the pane's watch key. Echoes move selection only when the pane already
contains that path; never navigate a hidden pane to find it. Use `Contain`
scrolling so an already visible selection does not jump. Closed-pane tokens
fall back to the focused pane. Pickers never register a return socket.

## Metadata and previews

Ctrl+F filters the current directory by case-folded substring AND terms, with
quoted phrases. PNG metadata joins the filename through shared `pngmeta.py`;
other files and directories contribute their names only. No recursive content
walk or field syntax. `null` means no filter; an empty Set means no matches.

Build metadata off the GUI thread, cache by path/mtime/size, debounce input,
and discard stale generations. Route results by pane key. Navigation clears
the query; external refresh reruns it. Do not rerun from rows-changed signals,
which would loop. One Ctrl+F shortcut owns the key; it is disabled in picker
mode.

Thumbnails share a path-keyed image provider and the freedesktop cache.
Videos use ffmpeg poster extraction with fast seek and blank-frame rejection;
a truly blank clip still gets its frame. Still-image decode caps do not apply
to video file sizes. Missing ffmpeg/ffprobe produces an unavailable preview,
not a crash. Keep `VIDEO_EXTS` equal to viewer's and draw the play marker as
geometry when the selected font lacks the glyph.

## Drag, drop, operations, and clipboard

Build drag payloads on press from the whole selection. Pressing within a
multi-selection defers collapse until release without a drag. Encode/decode
file URLs through `QUrl`/the Python helpers, not hand-written URI escaping.

Never rebuild a pane model while a drag-out is in flight: Qt's nested drag
loop can otherwise destroy its own source delegate. Defer watcher/model
refreshes until drag completion. Keep the drag guard in both rows and tiles.

A drop asks move/copy/link rather than guessing from modifiers that may not
reach the destination process. Reject same-directory entries, self-drops, and
directory drops into their own subtree. Reuse paste's no-clobber behavior and
overwrite confirmation. Report every file-operation outcome, batching multi-file
failures into one result rather than one notification per child process.

Copy populates filer's internal buffer and shared `pylib/clipfile.py`; a single
image may also offer pixels with `--image`. Cut remains internal. Do not use
QClipboard as a replacement for the persistent file clipboard owner. Harnesses
must substitute `CLIPFILE` and notification/process seams.

Conversion/compression actions keep originals and report unsupported formats or
missing tools. Byte-budget still conversion belongs to shared `imgfit.py`;
video/audio stripping is a derivative, not an in-place rewrite. Use the relevant
conversion harness with synthetic files and scratch output/cache paths.

KDE Connect lists reachable devices when constructing the menu. Distinguish no
reachable device from an unsendable directory selection. Filter directories
before counting/sending, use one operation per file inside a batch, and keep
send actions away from destructive actions. The phone harness must never call
the real device transport.

## Picker and portal contracts

`home/prog/filer-portal.nix` packages a separately opt-in FileChooser backend.
MIME defaults do not activate it. Read `filer-portal-switch status` and the
verified session's portal configuration before making claims about selection.
The switch's Hyprland configuration is not evidence of Plasma's active backend.
Do not toggle portal routing as a test.

FileChooser selection is per interface: implement OpenFile, SaveFile, and
SaveFiles. `portal.py` handles open and proxies save methods to the configured
delegate. The backend returns a method reply; the frontend owns Response
signals. Every exit path replies exactly once, including spawn failure,
cancellation, and missing result files. A picker is a subprocess so Close can
terminate that request without wedging future dialogs.

`pick.py` owns the spec/result protocol. Picker modes are open, dir, and save;
Surfer can use save directly even though portal saves delegate. Resolve typed
paths in Python, relative to the visible directory. A typed folder navigates
unless directory selection is the requested answer. Missing files disable open
acceptance; save permits a missing leaf only under a writable folder and asks
before overwrite. Synchronize editable filename text imperatively behind its
guard. Picker persistence is disabled and opening a file returns the selection
instead of launching viewer or xdg-open.

Any portal activation/startup repair must follow the root guide's permission
rules. An old failure on book's Hyprland session cannot justify changing the
current session's user-manager environment or login behavior.

## Isolated verification

Harnesses loading `Main.qml` must provide all `startSplit*` context properties
and redirect Settings to a temporary store. Offscreen Qt alone does not isolate
subprocesses or writable stores. Apply the shared/root guard rules and remove
inherited display/compositor sockets before construction.

`tools/resource-fixture.py` starts on scratch HOME/XDG directories under
verified offscreen Qt. Its stdin protocol accepts `stress`, `clear`, and `quit`
after `READY normal`. Stress retains two panes on generated files; clear
returns to the empty single-pane state without restarting. Keep it state-only,
with no synthetic live input or path into the user's files.

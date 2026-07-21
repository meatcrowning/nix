# filer roadmap

Where filer is and where it's going. Each item notes **which layer** it touches
— `qml/` (UI/interaction) vs `main.py` (`FileOps` backend) — so it's clear what
the work actually is. Ordered by priority within each phase.

## Done

- Standalone PySide6 process, decoupled from Quickshell hot-reloads.
- Real Wayland window, framed by hyprvtb; retro pixel-font look preserved.
- Navigate (up / double-click / editable location bar), open files (xdg-open).
- File ops: new folder, rename, copy/cut/paste, trash, permanent delete — async
  via `QProcess`, argv-safe.
- **Inline directory tree**: `+/−` toggles expand dirs in place (lazy, via
  `FileOps.listDir`), expansion survives refreshes, with vertical guide lines.
- Editable, aligned location bar with **Tab-completion** (`FileOps.completePath`)
  and a greyed ghost preview.
- **Live theming**: `WalPalette` (main.py) parses + watches the panel's Theme.qml;
  colours track the wallpaper in real time.
- **Instant cold start**: a wrapped store binary (`filer`) that runs the live
  source with no `nix develop` eval — see `~/nix/home/prog/filer.nix`.
- Launchable from the Quickshell runner, and the **default directory handler**.
- Opens at a directory argument (`filer /path`); the Quickshell disk widget's
  per-drive "open" button launches it there.
- **Detail columns**: size · created · modified, right of each name.
- **Always shows hidden**, ordered hidden → dirs → files.
- **Sort controls** in the header (name / created / size, bidirectional).

---

## Phase 1 — file-manager basics (do next)

The gaps that make it still feel like a toy vs. a real manager.

1. **Keyboard navigation** *(qml)* — the biggest gap. Arrow up/down to move a
   focus cursor, Enter to open/cd, Backspace = up, `→`/`←` to expand/collapse the
   focused tree row, Home/End, type-to-select (jump to first row matching typed
   prefix). Needs a `focusIndex` on the view and key handling on the ListView.
2. **Context menu (right-click)** *(qml)* — a popup mirroring the toolbar (open,
   rename, copy/cut/paste, trash, delete) plus "open with…" and "copy path".
   Reuses the existing `FileOps` calls; just a new `Menu`/popup component.
3. **Selection follows the tree** *(qml)* — keep the current `selected` path
   valid across expand/collapse/refresh; clear it if the path disappears.
4. **Hidden-files toggle** *(qml)* — hidden are always shown now; add a toggle
   (`Ctrl+H`) to hide them, and a `modified` sort option, if wanted.

## Phase 2 — selection & bulk operations

1. **Multi-select** *(qml)* — Ctrl+click toggles, Shift+click ranges. Change
   `selected: string` → a `Set` of paths; update ops to loop over the set.
2. **Bulk ops** *(qml)* — copy/cut/paste/trash/delete operate on the whole
   selection. `FileOps.run` already takes argv; batch or iterate.
3. **Progress + errors** *(backend)* — surface `QProcess` stderr and non-zero
   exits (e.g. permission denied) as a toast instead of silently refreshing.
4. **Drag-and-drop** *(qml)* — internal move/copy between tree rows; later,
   DnD to/from other apps via `Drag`/`DropArea` with `text/uri-list`.

## Phase 3 — views & information

1. **Detail columns** — *done* (size / created / modified). Could add permissions
   / owner (mode + uid from `listDir`) and toggleable column visibility.
2. **Thumbnails** *(backend + qml)* — image previews. Backend generates/reads
   thumbnails (respect the freedesktop thumbnail cache); QML shows them in an
   icon/grid view mode. Needs a view-mode switch (list ⇄ grid).
3. **Breadcrumb bar** *(qml)* — clickable path segments as an alternative to the
   editable text field (toggle between the two).
4. **Status bar** *(qml)* — item count, total size of selection, free space on
   the current filesystem (`FileOps.statfs`).

## Phase 4 — navigation aids

1. **Places / bookmarks sidebar** *(qml + backend)* — home, root, and
   user-pinned dirs; read XDG user dirs and GTK bookmarks. Persist pins to a
   small JSON in `~/.config/filer/`.
2. **Back / forward history** *(qml)* — nav stack with mouse back/forward
   buttons and `Alt+←/→`.
3. **Tabs** *(qml)* — multiple roots in one window; later, split/dual-pane.

## Next up — file picker portal (own turn)

Make filer the system **file chooser** for programs. This is an
`org.freedesktop.impl.portal.FileChooser` backend (D-Bus) that spawns filer in a
pick mode and returns the selection; plus a `filer --pick` mode, a `filer.portal`
file, and `portals.conf` routing in `~/nix`. Riskier than the UI work — a portal
misconfig can hang file dialogs system-wide — so it's a dedicated, separately
tested step. Only portal-aware apps (GTK/Qt via portals) can be redirected.

## Phase 5 — integration & polish

1. **Mounts / removable media** *(backend)* — list and (un)mount volumes via
   `gio`/`udisks2`; show them in the places sidebar.
3. **Open-with** *(backend)* — enumerate `.desktop` handlers for a MIME type and
   let the user pick (mirrors what the Quickshell runner already does).
4. **Packaging** — once the UI settles, flip the runner's desktop entry from the
   `run.sh` dev launcher to the packaged binary (`nix run`), and wire filer's
   flake into `~/nix` so it's a first-class installed app.
5. **Config file** *(backend)* — persist window size, sort, hidden toggle, view
   mode, bookmarks under `~/.config/filer/`.

---

## Cross-cutting / tech debt

- **Large directories**: `listDir` is synchronous `os.scandir`. Fine for typical
  dirs; a 100k-entry dir would briefly block the UI. If it bites, move `listDir`
  to a worker thread and return results via a signal.
- **Tree rebuild cost**: every op re-lists all expanded dirs. Fine now; if trees
  get deep, switch to incremental row splicing instead of full rebuild.
- **Singleton refactor**: `Theme` is a pragma-singleton; if more shared state
  appears, consider a proper QML module (`qmldir` with a module name) over the
  current directory-local singleton.

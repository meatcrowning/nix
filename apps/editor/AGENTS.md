# `apps/editor` — the text editor

Kate's **core text editing**, in the desktop's own idiom. The ninth vendored app.
Packaged by `home/prog/editor.nix`; runs the live source at
`/home/lam/nix/apps/editor/main.py`, so `.py`/`.qml` edits need **no rebuild** —
relaunch the app.

Read `~/nix/docs/DESIGN.md` before you change anything it draws, and
`apps/AGENTS.md` for the mechanics every app here shares.

```bash
# the harness — offscreen, four layers, nothing on his screen
W=$(readlink -f "$(which editor)"); sed '$d' "$W" > /tmp/edenv.sh
( . /tmp/edenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \
    apps/editor/tools/editor-test.py )
```

For retained resource sampling, `tools/resource-fixture.py` launches the real
window offscreen with scratch HOME/XDG roots and generated Python documents.
It reports `READY normal`, accepts `stress`, `clear`, and `quit` as newline
commands on stdin, and never opens or saves a user file. Run it through the
packaged interpreter/environment on `top`; `/usr/bin/python3` is the `book`
branch. The narrow fd protocol is shared in `apps/pylib/resourcefixture.py`;
do not turn it into input automation.

---

## The three-way split, and why it is not negotiable

| owns | where | why |
|---|---|---|
| the VIEW and the CURSOR | `qml/CodeView.qml` — one `TextEdit` per document | Qt keeps the undo stack, the selection and the caret per `TextEdit`, so switching documents is showing a different item |
| the DOCUMENT | `main.py` `Buffers` + `textops.py` | a `QTextCursor` inside `beginEditBlock()` is the ONLY way indent-four-lines is one Ctrl+Z |
| the COLOUR | `highlight.py`, one `QSyntaxHighlighter` per document | per-block regex, and the find bar's all-matches highlight rides the same pass |

**Python moves the text; QML moves the caret.** Every `textops` function returns
the selection to apply and `CodeView.applySel()` applies it. A `QTextCursor`
position set in Python does not reach the `TextEdit`, which keeps its own.

**`Buffers` keeps the `QQuickTextDocument`, never the `QTextDocument`.** Measured
here: the Python wrapper for the inner document reports *"Internal C++ object
already deleted"* while the document itself is alive and well, because the
`TextEdit` owns it. `Buffers._doc()` re-asks every time — one virtual call, and
the difference between this working and this crashing.

**Never touch `ed` from outside `CodeView.qml`.** PySide6 wraps no
`QQuickTextEdit` (`Can't find converter for 'QQuickTextEdit*'`), so the harness
physically cannot reach it. `CodeView` exposes `content`, `selectedText`,
`canUndo/canRedo`, `cursorPos`, `selStart/selEnd` and the `undo()`/`cut()`/… 
functions, and Main.qml goes through those too.

**Assigning `content` is not an edit.** It goes through
`QTextDocument::setPlainText`, which clears the modified flag *and* the undo
stack. Reading it is fine; a real edit is a keystroke or a `Buffers.*` call, and
a reload is `Buffers.replaceAllText` (one edit block, one Ctrl+Z). A harness that
tests dirtiness by assigning `content` "proves" the dirty flag broken.

---

## What is here

- **Documents in tabs** — surfer's idiom: they are **buttons in the hyprvtb
  titlebar**, draggable, and re-clicking the current one closes it. A dirty
  document's cell reads `f*` rather than `fi`, because a cell has no third state
  and *which one is unsaved* is the more useful two characters. Every document
  keeps a live `CodeView`; nothing is a `Loader`.
- **open / save / save-as / close**, with the unsaved-changes guard
  (`Confirm.qml`) on close, on quit (one document at a time — a single
  "discard all" over several files is exactly the clobber §10.2 forbids) and on
  overwriting an existing file from save-as.
- **Reload on external change** — a `QFileSystemWatcher` per open path. A clean
  buffer reloads **in place** (§6.1: caret, selection and scroll all restored); a
  dirty one asks. Every editor here writes atomically, so the watched inode is
  replaced and the path has to be re-added or the *second* change never fires.
- **Line numbers** from the document's own layout (`Buffers.gutter`), not
  `n * lineH` — with wrap on, a document line is several rows tall and an
  arithmetic gutter drifts a line per wrapped paragraph, silently.
- **Current-line band**, positioned from `Buffers.blockRect`. Not a binding:
  `positionToRectangle` is not a notifying property, so a binding on it evaluates
  once, before layout exists — measured, it returned `y = 0` forever.
- **Tabs vs spaces and indent width**, persisted, plus `Buffers.guessIndent`:
  the GCD of the leading widths in the first 200 indented lines, with the
  language's default as the tie-break. This repo is nix at 2, python at 4, lua at
  2 and C++ at 4, so one global setting applied blindly corrupts the shape of
  whatever it touches.
- **Auto-indent** on Return, per language, as ONE undo step with the newline
  (two steps is the classic "undo left me a line of whitespace"), and Backspace
  eats a whole indent unit inside leading whitespace.
- **Syntax highlighting** for nix, python, qml/js/ts, lua, c++, shell, json,
  markdown, conf/ini/toml/yaml, and `text` (which highlights nothing and is never
  wrong). Detection is basename → extension → `#!`.
- **find / find-next / find-previous / replace / replace-all** with regex, case
  and whole-word toggles, every match lit at once, and `bad regex` reported as a
  DIFFERENT answer from `no matches`.
- **Kate's keys**: Ctrl+N/O/S/Shift+S/W/Q, Ctrl+F/R/G, F3 / Shift+F3,
  Tab / Shift+Tab and Ctrl+I / Ctrl+Shift+I, Ctrl+D (comment toggle), Ctrl+K
  (delete line), Ctrl+Alt+Down (duplicate), Ctrl+Shift+Up/Down (move lines),
  Ctrl+PgUp/PgDn and Alt+Left/Right (documents), Ctrl+Z / Ctrl+Shift+Z.
  App-wide keys are window `Shortcut`s; editing keys are the `TextEdit`'s
  `Keys.onPressed` — and `Keys.priority: Keys.BeforeItem` there is load-bearing
  for exactly one key, Tab, which focus navigation eats otherwise.
- **Spellchecking, in PROSE documents only** —
  `qmlcommon/SpellMarks.qml` over the `TextEdit`, `pylib/spellcheck.py` behind
  it, docs/DESIGN.md §3.7 for the mark. `CodeView.prose` is true only for the
  `text` and `md` language KEYS (`highlight.py`'s, not their display names —
  markdown's key is `md`), so a source file is not checked: nothing here can tell
  a comment from an identifier, since the highlighter is regex-per-line and not a
  parser. Switching a file's language to `text` from the context menu turns it on
  by hand, which is why `refreshSpell()` is called from `loadText`,
  `reloadText`, the language menu and save-as. A correction goes through
  `Buffers.replaceOne`, so it is ONE Ctrl+Z like every other multi-character
  edit here. Widening it to comments and strings means teaching `highlight.py`
  to publish the spans it painted; nothing else would need to change.
- **The open / save-as / go-to-line prompt** is `PathBar.qml`, one chip with
  readline-style completion. **Not a `FileDialog`**: a stock platform dialog is
  the one thing this desktop could draw that would look like nothing else on it
  (§7.2). filer's FileChooser portal is the other route and is not used because
  it ships dormant.

## What is deliberately NOT here

He is being asked separately about each of these. **Do not start one without
him saying so:** LSP or completion, split views, an embedded terminal, a
project/file-tree sidebar, sessions, a plugin system, vi mode.

Two more, with reasons rather than a pending question:

- **Block/column selection.** It does not fall out of `TextEdit` cheaply at all —
  Qt's selection is one contiguous range and a rectangular one means drawing and
  editing N ranges by hand. It was scoped as "if it is cheap", and it is not.
- **A horizontal scrollbar.** `qmlcommon/VScroll.qml` is the desktop's one
  scrollbar and it is vertical-only. This does not bite here: wrap is
  **unconditional** (his call — long lines always wrap, no toggle), so the code
  area never pans horizontally and there is nothing for a horizontal bar to
  scroll. The general question "should `qmlcommon` grow an `HScroll`" is still
  open in `docs/DESIGN.md`, but editor no longer drives it.
- **No undo/redo cells in the titlebar.** §12.1 has no glyph for either and a
  glyph is never invented locally. They are Ctrl+Z / Ctrl+Shift+Z and rows in the
  context menu.
- **No `NavButtons`.** §11.1 gives the mouse's side buttons to *history*, and an
  editor has none — tab switching is not history. Recorded in §11.1's table.

## Traps this app has already paid for

- **`Settings.set` must convert a `QJSValue`.** A JS array reaches Python as one
  and `json.dumps` raises `TypeError` — which propagates back out through the QML
  call that made it and **aborts whatever QML was doing**. Storing the list of
  open files that way silently stopped `Component.onCompleted` after the first
  file, so editor opened one document out of two with no error anywhere.
- **Never hand `Buffers.attach` a language it did not detect.** It honours any
  key it is given and `text` is a valid key, so a "helpful" `lang: "text"`
  fallback in the delegate pinned every file to no highlighting at all. `""`
  means detect.
- **The delegate is a wrapper `Item`, not a bare `CodeView`.** A `Repeater` over
  a `ListModel` injects the model's roles into the delegate, and a role named
  `path`/`lang`/`tid` is shadowed by `CodeView`'s own property of that name and
  silently never assigned.
- **`TextEdit` has `lineHeight` but no `lineHeightMode`**, so the body cannot use
  `PixelText`'s FixedHeight packing. Measured with this font the line box comes
  out at exactly `Theme.fontSize` anyway — kitty's cell — which is why the gutter
  lines up. If that ever stops being true, the gutter is still right (it asks the
  layout) and only the *chrome* beside it would need re-checking.
- **A `QTextCharFormat` read off `block.layout().formats()` dies with the range
  list.** Read the colours inside the loop that owns it, or you get "Internal C++
  object already deleted" — the harness's `fmt_at` does.
- **Selection loses the syntax colours.** Qt gives a selection exactly one
  foreground; there is no way to keep per-token colour under it. It takes the
  brightest legible one. Do not "fix" this by dropping `selectedTextColor` — then
  it takes Qt's own palette, which is not this desktop's.

## Verifying

`tools/editor-test.py`, offscreen, and it **fails on any QML warning** — a
binding loop or a missing property here shows as nothing at all on screen. Layer
1 is the language table, layer 2 is every editing command against a bare
`QTextDocument` (no view at all), layer 3 is the highlighter, layer 4 is the real
`Main.qml`. The stub `Titlebar` carries `clicked`/`reordered` **signals** as well
as its slots, or the real `Connections` element warns for the stub's omission.

Never open a window on his screen, and never drive the editor he is using.

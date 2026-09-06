# `slsk` — the Soulseek search & download client for the local slskd daemon

Vendored source of the tenth app: `main.py`, `slskapi.py` and `qml/`. Built and
installed by `home/prog/slsk.nix`, which mirrors `reader.nix` exactly (including
the `air` system-python split) and runs the **live** source at
`/home/lam/nix/apps/slsk/main.py`, so `.py`/`.qml` edits need no rebuild. See
[`../AGENTS.md`](../AGENTS.md) for the rules shared by all the apps, and
`~/nix/docs/DESIGN.md` before you draw anything.

```bash
slsk    # search Soulseek, queue files, watch downloads land
```

It is a **client over the already-running slskd daemon**, not a connection of its
own: everything is an HTTP call to the loopback API slskd.nix exposes
(`home/prog/slskd.nix`, base `http://127.0.0.1:5030`, key
`~/.secrets/slskd-api-key`). That is what makes it stdlib-only for the network —
no Soulseek protocol code, no new dependency, and on `book` (Fedora) only the
system PySide6 is needed. The same default URL/key are what
`apps/player/tools/soulseek-missing.py` already uses; keep them in step.

## Where the slskd surface lives: `slskapi.py`

Every capability of the API bridge is a Qt `Slot` the QML calls and a `Signal`
the QML binds to. **The GUI thread never touches the network** — each request runs
on its own daemon worker thread and returns through a queued Qt signal. The
routes it uses (confirmed against the installed 0.24.5, and for the cancel route
against slskd's own `Transfers/API/Controllers/TransfersController.cs`):

| action | call |
| --- | --- |
| status | `GET /api/v0/application` |
| search | `POST /api/v0/searches` `{searchText}` → poll `GET /searches/{id}` → `GET /searches/{id}/responses` |
| queue | `POST /transfers/downloads/{username}` `[{filename,size}]` |
| list downloads | `GET /transfers/downloads` (nests username → directories → files) |
| cancel one | `DELETE /transfers/downloads/{username}/{id}` (the file's GUID `id`) |

Two invariants worth keeping when you touch it:

- **Drawn fields are glyph-mapped, wire fields are not.** Filenames, usernames
  and directories are passed through `pylib/glyphs.px()` HERE, at the ingest
  point (docs/DESIGN.md 2.3 — once per result, not per delegate per scroll), and
  each row carries both: `username`/`filename` (drawn) and `userraw`/`path`
  (raw, what the API needs). Feeding a mapped string to the enqueue/cancel call
  would corrupt the request.
- **Soulseek paths use `\` separators even on Linux.** `_leaf()`/`_parent()` in
  `slskapi.py` split on it; a naive `os.path.basename` shows the whole path in
  the file column. Retain that when you reformat.

## The window: `qml/Main.qml`

Two modes, swapped with the two tabs in the top bar — **search** (a query field
+ the result list; double-click or press-and-hold on a row queues it) and
**downloads** (the flattened transfer list, a live progress bar, and an `x` to
cancel an in-flight download). There is no separate chrome strip: the only
titlebar content is a `Titlebar.setFooter()` carrying the live connection
status, exactly like reader ships with no app-button column (docs/DESIGN.md 12).

The search is **not polled** here — `startSearch` owns a worker that polls
slskd's own search state (slskd terminates every search by itself) and then
emits the full result list. The transfers list, by contrast, is a poll: `Slsk`
re-fetches `/transfers/downloads` on mode switch, on every queue/cancel, and you
may add a `Timer` in `Main.qml` if you want it live-refreshing (nothing has so
far; a queue/cancel-refresh covers the common path, and ended states are the
only things that change by themselves). A refresh touches nothing the user is
watching — it is a read-only GET.

## Verifying

- The user does all visual checks — never screenshot or drive the GUI.
- `slskapi.py` talks to the LIVE daemon; a harmless read-only smoke test is to
  hit status + transfers (see `tools/` below if you add one) — never a live
  search or queue unless you mean it as the app would.
- QML loads are validated offscreen with the reader wrapper's PySide6
  interpreter (`W="$(readlink -f "$(command -v reader)")"; PY="$(tail -1 "$W" |
  grep -o '/nix/store/[^" ]*/bin/python3')"` + `QT_QPA_PLATFORM=offscreen`), not
  on his screen.

Hermetic harnesses may set `SLSK_API_URL` and `SLSK_API_KEY_FILE` to a fake
loopback server and scratch key. Non-loopback endpoints are rejected. Never
point a resource fixture at the live 5030 daemon: even a mistaken transition
must be incapable of searching, queueing, or cancelling there.

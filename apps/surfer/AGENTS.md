# `surfer` — QtWebEngine browser

Vendored source of the standalone browser, same live-source pattern as the rest
of [`apps/`](../AGENTS.md); built/installed by `home/prog/surfer.nix`. Titlebar
chrome via hyprvtb like the others.

**QtWebEngine spellcheck is imperative-only**: the declarative QML
`WebEngineProfile` `spellCheck*` properties are silently dropped — set
`setSpellCheckEnabled`/`setSpellCheckLanguages` imperatively in `_wire_profile`.

**Wheel events in this window are rescaled, and QML must undo it.** `ZoomFilter` divides every touchpad wheel event by `pylib/kinetic.py`'s `WHEEL_GAIN` (1/6) so QtWebEngine pages track the finger at the same rate the QML apps do; that is window-wide, so any scrollable QML surface here takes `wheelGain: WheelGain` (the reciprocal, published by `main.py` from the same constant) — the file picker does. Real mouse detents are passed through untouched (`is_wheel_detent`); applying the gain to them made top's wheel scroll pages at 1/6 speed twice already. The page itself is Chromium's own scroller and cannot use `WheelScroll`: parity there is the gain plus the compositor's >=300 ms withheld stop, which zeroes Chromium's 200 ms fling estimator so it adds no fling of its own. See [`../AGENTS.md`](../AGENTS.md).

## Single instance — `surfer <url>` opens a TAB in the running browser

surfer is the system default browser, so every link clicked anywhere runs
`surfer <url>`. `Main.qml`'s `WebEngineProfile` is **persistent**
(`storageName: "surfer"`, `offTheRecord: false`) and a Chromium profile
directory may only be owned by one process — a second surfer means a
ProcessSingleton failure, cookies/history that silently don't persist, and on
book a second `sync.py` bracket interleaving with the live session.

So a launch that finds a surfer already running hands it the URL over a Unix
socket and exits 0. The running instance opens it via the *existing*
`normalize()` → `newTab()` path (a bare launch with no URL gets a home tab, so
clicking the menu entry always does something visible).

- **Client half: [`singleton.py`](singleton.py) — stdlib only, deliberately Qt
  free.** `main.py` imports it and calls `try_handoff()` **before** `import
  PySide6`, so a link click costs ~50 ms instead of the seconds a PySide6 import
  plus `QtWebEngineQuick.initialize()` would. Runnable standalone as a pure probe
  (`python3 singleton.py [url]`; exit 0 = handed off, 10 = no server).
- **Server half: `SingleInstance` in `main.py`** — a `QLocalServer` (an ordinary
  `AF_UNIX` listener, which is why the stdlib client can talk to it) exposed to
  QML as the `Instance` context property; `Main.qml`'s `Connections` on
  `Instance.openUrl` adds the tab.
- Socket is `$XDG_RUNTIME_DIR/surfer-<uid>.sock` (per-user, per-machine), `/tmp`
  fallback at 0600. `SURFER_SOCKET` overrides it; `SURFER_NO_SINGLETON=1`
  disables the whole thing and always starts a fresh process.
- **A stale socket is unlinked only after a connect has actually FAILED**, never
  unconditionally — an unconditional `removeServer()` would evict a healthy
  running instance from its own address. Correspondingly, a `listen()` that
  fails is NOT retried by stealing: it means another surfer won the startup
  race, and we just run without a server.
- **The fallback stays intact.** Every failure inside the handoff means "carry
  on and launch normally". A default browser that refuses to start is worse than
  a duplicated process.
- **The window is not raised.** Wayland gives a client no way to raise or focus
  itself without an xdg-activation token from the launcher, so the
  `raise()`/`requestActivate()` in the handler are very likely no-ops under
  Hyprland; the tab appears but the window does not come forward. Do **not**
  "fix" that with `hyprctl dispatch` — under this Lua config it evaluates its
  argument as Lua and would act on the *user's* active window.

Verified headlessly end-to-end by making the harness the hyprvtb app-button
server (scratch `HOME` + `XDG_RUNTIME_DIR`, `QT_QPA_PLATFORM=offscreen`,
`SURFER_NO_SYNC=1`) and counting `tab:<tid>` buttons in the `REGISTER` lines:
1 tab → second launch exits 0 in 0.07 s → 2 tabs → bare launch → 3 tabs (the
third being `homeUrl`), with the first process still alive throughout.

## Profile handoff between `top` and `book` (2026-07-26)

`tools/sync.py` merges the two machines' browser state; `home/prog/surfer.nix`'s
**air** wrapper brackets the run with it (`pull` before the window opens, `push`
after it closes; `SURFER_NO_SYNC=1` opts out, and the sync is timeout-bounded +
`|| true` so an absent `top` never blocks the browser — log at
`~/.cache/surfer-sync.log`). Only air brackets it because Fedora runs no sshd:
**book is the only machine that can initiate**, and it still converges both ways
by pulling at its launch and pushing at its exit.

Scope is deliberately just the two things that MERGE losslessly — **Cookies**
(SQLite, merged row-by-row on Chromium's unique index, newer `last_update_utc`
wins) and **userscripts** (`rsync --update` both ways). Everything else is
excluded on purpose: `Local Storage`/`IndexedDB`/`WebStorage` are **LevelDB,
which cannot be merged** (syncing them means whole-dir last-writer-wins, i.e.
silently dropping a session — the cost is that a site keeping auth in
localStorage won't carry over), and `Service Worker` (150 MB+) and the various
caches are regenerable.

Three things this rests on:

- Cookies are stored **plaintext** here (QtWebEngine found no keyring, so
  there's no machine-bound key — if `encrypted_value` ever fills, copied rows
  become undecryptable garbage and `status` warns).
- Both profiles are at **Cookies schema v24** with the same unique index (a Qt
  bump that moves one side makes `sync.py` refuse).
- A Chromium profile must never be touched while the browser owns it, so **every
  command refuses if surfer is alive on either end** (a `/proc` scan, not
  `pgrep`, which would match its own ssh command line).

It never deletes — clearing cookies for real means clearing on both. Use `top`,
never `top.local`, in anything nix-built — nix binaries on book can't resolve
mDNS, while plain DNS gives `top` → 192.168.40.202.

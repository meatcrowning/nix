# `surfer` — QtWebEngine browser

Vendored source of the standalone browser, same live-source pattern as the rest
of [`apps/`](../AGENTS.md); built/installed by `home/prog/surfer.nix`. Titlebar
chrome via hyprvtb like the others.

**QtWebEngine spellcheck is imperative-only**: the declarative QML
`WebEngineProfile` `spellCheck*` properties are silently dropped — set
`setSpellCheckEnabled`/`setSpellCheckLanguages` imperatively in `_wire_profile`.

**Wheel events in this window are rescaled, and QML must undo it.** `ZoomFilter` divides every touchpad wheel event by `pylib/kinetic.py`'s `WHEEL_GAIN` (1/6) so QtWebEngine pages track the finger at the same rate the QML apps do; that is window-wide, so any scrollable QML surface here takes `wheelGain: WheelGain` (the reciprocal, published by `main.py` from the same constant) — the file picker does. Real mouse detents are passed through untouched (`is_wheel_detent`); applying the gain to them made top's wheel scroll pages at 1/6 speed twice already. The page itself is Chromium's own scroller and cannot use `WheelScroll`: parity there is the gain plus the compositor's >=300 ms withheld stop, which zeroes Chromium's 200 ms fling estimator so it adds no fling of its own. See [`../AGENTS.md`](../AGENTS.md).

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

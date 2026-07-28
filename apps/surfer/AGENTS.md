# `surfer` — QtWebEngine browser

Vendored source of the standalone browser, same live-source pattern as the rest
of [`apps/`](../AGENTS.md); built/installed by `home/prog/surfer.nix`. Titlebar
chrome via hyprvtb like the others.

**QtWebEngine spellcheck is imperative-only**: the declarative QML
`WebEngineProfile` `spellCheck*` properties are silently dropped — set
`setSpellCheckEnabled`/`setSpellCheckLanguages` imperatively in `_wire_profile`.

**Wheel events in this window are rescaled, and QML must undo it.** `ZoomFilter` divides every touchpad wheel event by `pylib/kinetic.py`'s `WHEEL_GAIN` (1/6) so QtWebEngine pages track the finger at the same rate the QML apps do; that is window-wide, so any scrollable QML surface here takes `wheelGain: WheelGain` (the reciprocal, published by `main.py` from the same constant) — the file picker does. Real mouse detents are passed through untouched (`is_wheel_detent`); applying the gain to them made top's wheel scroll pages at 1/6 speed twice already. The page itself is Chromium's own scroller and cannot use `WheelScroll`: parity there is the gain plus the compositor's >=300 ms withheld stop, which zeroes Chromium's 200 ms fling estimator so it adds no fling of its own. See [`../AGENTS.md`](../AGENTS.md).

## Split view — two tabs in one window, kitty's two buttons

**`|` splits right (side by side) and `_` splits down (stacked)** — kitty's own
titlebar pair (`pylib/kitty-vtb.py`'s `ACTIONS`), same labels, same wording.
`_` and not kitty's `-` because **a bare `-` is the SPACER token** in the vtb
button-array protocol and would be ambiguous there.

`splitVertical` is the orientation and the only thing that differs between the
two: **pane A** (always `currentTab`) takes the LEADING slice of the active axis,
**pane B** (`splitTab`, while `splitOn`) the trailing one, with the draggable
splitter between them. `focusPane` says which of the two the CHROME acts on.
Everything pane-agnostic keeps working because `current` now means *the focused
pane's view* (`focusTab`), not *the current tab's view* — the address bar,
back/fwd/reload, dark mode, the JS dialogs and the file picker all read it and
needed no change.

- **Each button is a toggle, and the pair adds re-orienting.** Split off → the
  button opens it in *its* orientation; split on and you click the **lit** one →
  it closes; click the **other** one → the split *re-orients in place*, keeping
  both panes and the divider's proportion. State 1 is on whichever orientation
  is live, and the tip says what a click will do from here (`split right` /
  `split down` / `close split`). All of it goes through one
  `toggleSplit(vertical)`, so opening still adopts the tab to the right of the
  current one (or the one to its left) and still makes a home tab when that is
  the only tab there is.
- **One `splitRatio`, reused on whichever axis is active**, so re-orienting keeps
  the proportion rather than resetting to even. The geometry is expressed once
  along the axis (`splitAxisLen`/`paneALen`/`paneBOff`/`paneBLen`) and resolved
  into `paneA{X,Y,W,H}` / `paneB{X,Y,W,H}`; nothing downstream — the view
  delegate, the focus frame, the splitter — knows about the axis. The splitter
  drags in X or Y accordingly, with `Qt.SplitHCursor`/`Qt.SplitVCursor`.
- **Every one of those rects is clamped away from zero**, including the
  minimum-pane length, which shrinks with the window: a window narrower (or
  shorter) than two minimum panes is otherwise exactly how you hand the
  compositor a degenerate box, and `renderRect` aborts the session on one.
- The per-tab tooltips name the panes by orientation — `left`/`right` when
  vertical, `top`/`bottom` when stacked.
- **No keyboard shortcut**, deliberately: the page has the keyboard and a QML
  `Shortcut` here would race Chromium for it. The chrome is the titlebar.

- **The two panes always hold different tabs.** One `WebEngineView` can only be
  in one place, so `showInPane()` swaps rather than duplicates, and closing a
  pane's tab hands that pane another one — or folds the split when there is no
  other tab left.
- Both panes' tabs are **lit** in the titlebar. There is no third state to say
  which one has the chrome, so the tooltip does (`close · left · …` for the
  focused pane, `focus · right · …` for the other) and the window draws a 1px
  accent frame round the focused pane. Clicking a lit tab that is *not* focused
  moves the focus rather than swapping the panes.
- `newTab()` opens in the **focused** pane; `splitTab` is tracked by tid across
  a drag-reorder exactly as `currentTab` is.
- **`focusPane` cannot be driven by active focus alone.** Swapping a pane's tab
  hides one view, and Qt gives the hidden view's active focus to the only other
  thing that will take it — the other pane — which is indistinguishable from a
  click over there. Left unguarded, clicking any off-screen tab put it in the
  left pane and then jumped the chrome to the right one. Focus we move ourselves
  is therefore flagged (`win.retargeting`) and ignored on the way back in, and
  applied through `Qt.callLater` so the visibility bindings have settled first.
  This is measured, not theorised — see the harness note below.
- **A view no longer spans the window, so view-relative coordinates are not
  window coordinates.** The context menu and the page tooltip both add the
  view's own `x`/`y`; anything else reading a `request.position` must too.
- Persisted: the divider position and the orientation in `prefs.json`
  (`splitRatio`, written on release of the drag, clamped 0.08–0.92;
  `splitVertical`, written only when it changes) and pane B's tab in
  `session.json` (`split`, `-1` for none). **Every one of them is read with a
  default**, so a session written before split view existed restores as one
  pane and a `prefs.json` written before the split had an orientation restores
  side by side.
- Known limitation: a JS dialog or file picker raised by the **unfocused** pane
  waits until you focus that pane. It is queued per view, and the tab's `asks ·`
  tooltip already says so — the same behaviour a background tab has always had.

Verified headlessly the same way the single-instance work was, by **two** kept
harnesses — run both after touching the split-view block:

- **[`tools/split-test.py`](tools/split-test.py)** — behaviour. It plays the
  hyprvtb button server (scratch `HOME` + `XDG_RUNTIME_DIR`,
  `QT_QPA_PLATFORM=offscreen`, about:blank tabs), reads the REGISTER lines and
  sends CLICKs. The per-tab tooltips name each pane, which is what makes pane
  assignment, focus, the close-fold, both toggles, re-orienting and the
  orientation's persistence assertable without a screen — 24 checks, all
  passing; it is what caught the focus bug above. Its scratch `prefs.json`
  deliberately has **no** `splitVertical` key, so the backward-compatible
  default is checked on every run.
- **[`tools/split-geom-test.py`](tools/split-geom-test.py)** — the rects, which
  the button socket cannot see. It **lifts the split-view property block
  straight out of `Main.qml`** and instantiates just that in a bare `Item`
  offscreen, so it cannot drift into testing a copy: pane A full-size when off,
  side by side under `|`, stacked under `_`, no overlap, the axis exactly
  filled, the ratio clamped at both ends on each axis, and **no zero-size rect
  at any window size down to 0×0**.

The *appearance* (divider, focus frame, page layout) is the user's visual check.

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

# `surfer` — QtWebEngine browser

Vendored source of the standalone browser, same live-source pattern as the rest
of [`apps/`](../AGENTS.md); built/installed by `home/prog/surfer.nix`. Titlebar
chrome via hyprvtb like the others.

**The titlebar REGISTER is seeded before the window maps.** surfer's chrome is
the plugin's *default* flipped twice — it turns the title region into an address
bar (`TITLEEDIT`) and fills the button column — so a window that maps before its
first REGISTER surfaces at the bare default bar for a few frames (the startup
flash). `Titlebar.__init__` (`main.py`) hands `VtbClient` a static
`_SEED_BUTTONS` set + `title_edit=True` at construction, staged BEFORE the I/O
thread starts, so the first connect's REGISTER carries surfer's real chrome in
one write — flushed within a millisecond of process start, long before
QtWebEngine builds the window. `qml/Main.qml`'s `tbButtons` stays the source of
truth and refines the seed (real tab buttons, live states) on the same load;
`_SEED_BUTTONS` is only the frame-0 copy. Regression: the `case_seed` in
`apps/pylib/tools/vtb-register-test.py`.

The seed is only the *client* half. Getting the REGISTER into the plugin's
`g_regs` before the window maps did not fully close the flash on its own,
because a freshly-mapped `CVtbDeco` only picked its registration up on the
plugin's 150ms heartbeat — so the default bar still showed for up to one
heartbeat after map even with the seed present. `hyprvtb 2.99` takes the
initial snapshot in the deco constructor, so a window mapping with its
registration already present draws its real chrome on the first frame. Both
halves are `docs/hyprvtb-titlebar-flash.md`.

**The address bar shows the page TITLE but edits the URL.** The bar the plugin
draws is the window title (`TITLEEDIT`), so at rest it reads as the page's
title, like any browser's address field when unfocused. The real URL reaches
the plugin on a separate channel: `Window.title` is bound to the page title
(falling back to the URL for a cold/titleless page), and `Main.qml` pushes the
live URL with `Titlebar.setEditSeed(curUrl)` on every `curUrl` change. The
plugin stores that per-registration (`EDITSEED` verb, `SVtbAppReg::editSeed`)
and `CVtbDeco::enterEdit()` opens the editor on it instead of the title;
submitting still returns `ADDR <url>`, and blur reverts the bar to the title.
An empty seed makes the editor open on the title as before — the pre-3.34
behaviour for any app that never sends `EDITSEED`. Needs hyprvtb ≥ 3.34.

**QtWebEngine spellcheck is imperative-only**: the declarative QML
`WebEngineProfile` `spellCheck*` properties are silently dropped — set
`setSpellCheckEnabled`/`setSpellCheckLanguages` imperatively in `_wire_profile`.

**And the language tag is a FILENAME, not a locale.** Chromium opens
`<tag>.bdic` under the dictionaries directory and does no locale matching at
all, so the tag must be resolved against what is installed: `top` has
`en-US.bdic`, compiled by `qwebengine_convert_dict` in `surfer.nix` and pointed
at with `QTWEBENGINE_DICTIONARIES_PATH`; `book` has Fedora's
`/usr/share/qt6/qtwebengine_dictionaries/en_US.bdic` and no env var. A
hardcoded `"en-US"` therefore checked nothing at all on `book` — and said
nothing, because `isSpellCheckEnabled()` is True either way. `main.py`'s
`_spell_language()` picks the tag whose `.bdic` exists; `tools/spell-test.py`
is the regression test (offscreen, right-clicks a misspelling and reads the
context-menu request — the only honest check).

That covers **web pages only** — Chromium's checker. surfer's own QML fields (the find bar,
the file picker) are queries and paths and are deliberately NOT checked; the
apps' checker for ordinary QML inputs is `pylib/spellcheck.py`
(`../AGENTS.md`), which reads the same `hunspellDicts.en_US` this `.bdic` is
built from, so the two never disagree about a word.

**Wheel events in this window are rescaled, and QML must undo it.** `ZoomFilter` divides every touchpad wheel event by `pylib/kinetic.py`'s `WHEEL_GAIN` (1/6) so QtWebEngine pages track the finger at the same rate the QML apps do; that is window-wide, so any scrollable QML surface here takes `wheelGain: WheelGain` (the reciprocal, published by `main.py` from the same constant) — the file picker does. Real mouse detents are passed through untouched (`is_wheel_detent`); applying the gain to them made top's wheel scroll pages at 1/6 speed twice already. The page itself is Chromium's own scroller and cannot use `WheelScroll`: parity there is the gain plus the compositor's >=300 ms withheld stop, which zeroes Chromium's 200 ms fling estimator so it adds no fling of its own. See [`../AGENTS.md`](../AGENTS.md).

## Find in page — `Ctrl+F`, and the key cannot be a QML `Shortcut`

`qml/FindBar.qml` + `HotkeyFilter` in `main.py`, wired in `Main.qml`. The desktop
rule is `docs/DESIGN.md` §11.2 (search is `Ctrl+F` in every program); **surfer is
the one program where §11.2's "bind it window-scoped with a QML `Shortcut`" does
not hold**, and that is recorded there as a divergence rather than left to be
rediscovered:

- **Chromium owns the keyboard whenever a `WebEngineView` has the focus** — i.e.
  almost always in this window. So the key is taken by a **window-scoped event
  filter**, exactly where Ctrl +/-/0 are taken (`ZoomFilter`'s docstring has the
  reasoning: the `QQuickWindow` sees platform input *before* the view item, and
  an app-wide filter segfaults this PySide6/Py3.14 build). `HotkeyFilter`
  consumes the event, so a page that binds `Ctrl+F` itself never sees it either.
- **Escape is NOT in that filter, deliberately.** It only has to close the bar
  while the bar's own field holds the keyboard, and Qt delivers it there;
  claiming Escape window-wide would take it from every page that uses it. The
  cost is that a bar left open while the *page* has the focus closes on its `x`,
  not on Escape.
- **The count comes back on `findTextFinished`, never on `findText`'s callback
  argument.** On PySide6/QtWebEngine 6.11 that third-argument callback is
  **never invoked at all** (measured: 0 calls, while the signal fired with the
  right `numberOfMatches` for the same find). A find bar built on the callback
  reads "no matches" on every query — silently, since the search itself works.
- It searches `win.current`, the **focused pane**, like every other control here;
  switching pane or tab clears the highlight off the view it was searching first.
  `findText("")` is what drops a highlight.
- Chromium **resumes** a re-issued query near the match it was last on, not at
  the first one — so an absolute `n/m` assertion after a re-search is a race.
- **The marks on the page are OURS, not Chromium's, and that is not a
  preference.** Chromium does light every match (`#ffff00`) and the one you are
  on (`#ff9632`) — and dark mode's whole-page invert filter runs over its
  markers too, so on a filtered page they land as `#252500` and `#b44b00`:
  measured offscreen, the first of those is invisible on a near-black page and
  reads exactly like a find that only scrolls. Dark mode is on globally with a
  per-site exception list, so that is nearly every page he opens. `FindBar.qml`
  therefore paints its own, via the **CSS Custom Highlight API** over ranges it
  walks itself: every match is `Theme.dim` with accent text, the current one
  inverts to `Theme.accent` with black text (docs/DESIGN.md §3.1's `dim` =
  inactive / `accent` = active, the ladder every list here uses). Chromium's
  `findText` still owns the count, the active index and the scrolling.
  - **The filter is cancelled, not avoided**: `DarkMode.compensate(url, hex)`
    returns the colour whose *image* under that page's filter is the palette
    colour — the same inverse trick `_dark_css` already plays on media, run
    backwards. It is the identity when the filter is off, so there is one code
    path, and the harness asserts the palette hex lands on the glass **exactly**
    in both states.
  - Our walk and Chromium's can disagree (shadow DOM, a match split across a
    block boundary). **A disagreement drops the current-match mark and leaves
    every match lit** — marking the wrong one as current is worse than marking
    none. Ranges with no client rects are dropped, which is what keeps the two
    counts equal in practice.

Verified offscreen by **[`tools/find-test.py`](tools/find-test.py)** (+ its
`find-test.qml` fixture): 40 checks over the real `FindBar.qml` and a real
off-the-record `WebEngineView` — which keys the filter claims, `Ctrl+F` opening
the bar and taking the keyboard from the view, the match count and both step
directions (buttons *and* `Enter`/`Shift+Enter`), "no matches", the empty query,
a second `Ctrl+F` re-selecting rather than appending, and Escape closing +
clearing + handing the focus back. The last block is **pixel-level**: it serves
the page over loopback (dark mode needs a host — `isSiteEnabled` is false for a
hostless `file://`), grabs the window and asserts the two palette hexes are on
the glass and differ, with the filter off *and* on. It also asserts `Main.qml` still instantiates
and connects the bar, so the fixture cannot end up testing a hotkey the browser
has lost. It borrows the packaged wrapper's *environment* (an offscreen
WebEngineView still needs `qtwebenginequickplugin` on the QML import path) but
never runs the wrapper — its third line would hand the arguments to the user's
live browser.

## Video: hardware decode loses the GL context on BOTH machines

Each host disables a different piece of Chromium's video path in `main()`, and
neither flag works on the other machine. On `top` (NVIDIA 595.84, RTX 5070) the
accelerated decoder publishes its frames as a **platform GpuMemoryBuffer in
multiplanar NV12**, and QtWebEngine has no shared-image backing factory for that
shape — `Could not find SharedImageBackingFactory … (Y_UV, 420, 8unorm) …
MailboxVideoFrameConverter`. That does not degrade to software: it **loses the
GL context on the first decoded frame**, so the whole page stops painting and
the log fills with `Context lost during MakeCurrent` and `non-existent mailbox`
at frame rate. That is the "embedded mp4s glitch out and won't play" report.

**Why webm looked hit-or-miss:** it is per codec, not per container. Measured on
`top` 2026-08-05, a real `WebEngineView` on the sandbox output, one clip per
codec — h264, vp9 and av1 all lose the context on frame one; **vp8 is clean**,
because it is the one codec this stack has no hardware decoder for and so never
enters the path. 4chan serves both, hence the coin flip.

`--disable-features=AcceleratedVideoDecodeLinuxGL` is the whole fix: 0 errors
against 234 in the same clip without it, with page compositing and rasterisation
still on the GPU and decode in software (free on this CPU). Two things that do
**not** work, both measured, so don't retry them: air's
`--disable-gpu-memory-buffer-video-frames`, and
`--disable-features=VaapiVideoDecodeLinuxGL,VaapiVideoDecoder` without the
`Accelerated…` name. `SURFER_GPU=hwvideo` puts the decoder back for a re-test
after an NVIDIA or Qt bump; `SURFER_GPU`'s other modes are air's.

## The file dialog IS filer

A page's `<input type=file>` opens **filer**, as `filer --pick <spec.json>` —
the same subprocess protocol the FileChooser portal backend speaks
(`apps/filer/pick.py`), the way KDE hands its file dialogs to Dolphin.
`qml/FilePicker.qml` is the queue and the plumbing; there is no UI in it, and
`Files.pick(token, spec)` / `Files.picked(token, paths)` (main.py) are the seam.

Until 2026-08-07 surfer drew its own picker, and it was a second, worse file
browser: no tree, no thumbnails, no preview grid, no sort, no `:top` remote
browsing, and a path line you could not even type into — which is what surfaced
it (*"really FilePicker.qml should just be a version of filer proper… like how
kde plasma does it with dolphin"*). Every fix had to be made twice; now there is
one file manager and one dialog.

- **Chromium's four modes map onto filer's three**: `FileModeOpen` /
  `OpenMultiple` → `open` (with `multiple`), `UploadFolder` → `dir`, `Save` →
  `save`. **`save` was added to filer's picker for this** — the portal backend
  never asks for it (it proxies SaveFile to the gtk/kde delegate), so the mode
  did not exist before. `defaultFileName` goes over as `current_name`.
- **A subprocess, not an embedded view**, for portal.py's reason: a crash or a
  wedge costs one dialog rather than the browser, and a tab closing under it has
  something to kill (`Files.cancelPick`, which leaves no result file — already
  a cancel in that protocol).
- **Every failure path answers.** No filer on PATH, an unwritable spec, a dead
  picker: all `dialogReject`. A page whose request never comes back leaves its
  `<input>` disabled for good.
- **Still queued per view, still only the current tab's.** A file request does
  not block a page's JS, so a page can have several outstanding — and a
  background tab must not throw a *window* in front of what you are reading.
- `Files.listDir`/`isDir`/`parentOf` are what is left of the old picker; only
  `startDir`/`rememberDir` still matter (where filer opens, and remembering it).

Verify with `tools/filepicker-test.py` (offscreen, 17 checks). **`FILER_BIN` is
pointed at a stub** that records the spec and answers on command, so no window
opens and the real filer never runs; the fixture mints stand-in
`FileDialogRequest`s, since only a live Chromium can make a real one. filer's
half — the bar, the editable name box, save mode, the overwrite confirm — is
`apps/filer/tools/pick-test.py`.

## Downloads — the progress toast gate is TIME, not size

Downloads land in `~/Downloads`. Every download gets a completion/failure toast;
a **slow or large** one also gets a live progress toast that updates in place
(`notify-send -p` then `-r <id>`, `-t 0` so it persists) with a CP437 block bar —
docs/DESIGN.md §10.4. The decision lives in the `Downloads` bridge in `main.py`
(`Downloads.progress`), not in QML: a toast appears when the download has run
`SLOW_MS` (1.5 s) **or** is bigger than `LARGE_BYTES` (3 MB). The size-only gate
that used to sit in `Main.qml` (`totalBytes > 3145728`) was the bug — a small
file on a slow connection never qualified, so the user waited on a silent screen
for a download that was slow only in *time* (§10.4 is explicitly about
"longer downloads"). `Main.qml` now feeds every byte change to
`Downloads.progress(key, name, received, total, elapsed_ms)` and the bridge
decides, throttling to whole-percent updates and leaving fast small downloads to
their single completion toast rather than a flash.

The **completion** toast is threaded with the downloaded file's full path
(`Main.qml` builds `downloadDir + "/" + downloadFileName` and passes it to
`Downloads.done(key, name, path)`); the bridge attaches it as an `x-download-image`
hint on the toast **only when the extension is in its `IMAGE_EXTS`** (mirrors
filer's set, so anything filer previews gets it) — the panel then shows a
thumbnail and click-to-open in the viewer. A progress toast (file still partial)
or a non-image download carries no path. See
`home/prog/quickshell-files/AGENTS.md` for the panel side.

### The save name comes from the URL path, so it can arrive with no extension

Chromium derives `downloadFileName` from the URL **path** alone and ignores the
`Content-Type` — so a host that serves images from an extensionless path with
the type in the query lands as a bare id with no extension at all. That is every
image saved from twitter (`pbs.twimg.com/media/<id>?format=jpg&name=large` →
`Gs9dkPXsAA1abc`), and an extensionless file is one nothing else on this desktop
will touch: not the viewer, not filer's thumbnailer, and not the completion
toast's own `IMAGE_EXTS` check above. Measured offscreen — `image/jpeg` on the
wire, still no suffix on disk.

`Downloads.fileName(suggested, mime)` repairs it from the type (`MIME_EXTS`,
falling back to `mimetypes`), and `Main.qml` calls it **before `accept()`** —
after accept the name is fixed. It only fills in a name that has no plausible
extension of its own (`_looks_like_ext`: ≤5 alphanumeric chars, so
`pbs.twimg.com-id` counts as untyped while `kitten.png` is left alone), and
`application/octet-stream` invents nothing.

Verified headlessly by **[`tools/download-test.py`](tools/download-test.py)**: a
real offscreen QtWebEngine download of a 320 KB file streamed slowly over
loopback — `--old` replays the pre-fix size gate and reproduces the missing
toast; the default path asserts the same slow small download now emits a
persisted, in-place-morphed progress toast, and drives the `Downloads` decision
gate directly (fast-small silent, slow-small toasts, same-percent throttled,
large-fast toasts on size, unknown total never toasts, an image `done()` threads
the path while a non-image one carries none), asserts the save-name repair
above, plus a drift-guard that `Main.qml` still calls the bridge with elapsed
time and still repairs the name before `accept()`. Run it after touching either
half.

## Ad blocking — the engine is only half of it

`AdBlocker` + `Cosmetic` in `main.py`. The engine is Brave's adblock-rust (the
`adblock` pip package, pinned by `home/prog/surfer.nix`), and **three things it
cannot do on its own are done here.** Each one was a silent no-op before, and
each has a measured before/after in `tools/adblock-test.py` — run that after
touching any of it (it drives the classes headlessly against a scratch
`$XDG_CACHE_HOME`, never the user's browser).

### Two engines, and every branch is feature-detected

**`top` runs the jampe fork (adblock-rust 0.12.5); `book` runs PyPI's `adblock`
0.6.0 (adblock-rust 0.5.6) in Fedora's system python and always will** — that
build is the last one on PyPI and the fork is a nix override. They differ in
ways that are silent, not loud, so **nothing here branches on a version
number.** Each branch logs which way it went.

| | top (0.12.5) | book (0.6.0) |
|---|---|---|
| resource format | modern, `dependencies` spliced | `{{1}}` templates |
| resource source | `brave-resources.json`, 208 entries, **100.0 % of scriptlet rules** (9551/9554) | uBO **1.48.6** tarball, 82 entries, **81.6 %** (2647/3245) |
| `##…:has()` | already in `hide_selectors` | dropped — recovered by `_scan_procedural()` |
| `procedural_actions` | live | absent |
| `style_selectors` | **gone**; `:style()` is a procedural action | present |
| `Engine.add_resource` | gone, `add_resources` batch only | singular only |
| `_sanitize()` | no-op (fixed upstream) | load-bearing |

`_resource_source()` picks the library from `hasattr(Engine, "add_resource")`,
and `Cosmetic._engine_procedural()` picks the procedural path from whether
`procedural_actions` exists at all — `None` (no such field) is deliberately not
the same as an empty set (no rules on this page). **Do not delete the legacy
side of either branch because top no longer takes it**: that is book's only
path, and it degrades rather than breaks.

**1. The RESOURCE LIBRARY, or no scriptlet ever fires.** adblock-rust only
materialises a `##+js(name, arg…)` body once its resource storage holds
`name`; with none loaded, `injected_script` is the empty string for every site,
forever. That is why first-party video/pre-roll ads went straight through:
YouTube and Twitch serve them same-origin from the same `/videoplayback`
endpoint as the real video, so there is no URL for a network rule to match and
uBO defeats them purely with scriptlets. On top the library is fetched
assembled; on book `_assemble_resources()` builds it from uBO's own tree, a
faithful Python port of adblock-rust's `resource_assembler.rs` (both halves:
`scriptlets.js` templates, and `redirect-resources.js` +
`web_accessible_resources/`). Either way it is cached as `resources.json` beside
the lists — **stamped with its source**, so switching engines discards it rather
than registering inert bodies — and refreshed on the same schedule.

Registering the wrong format is **not an error**; it just silently stops
substituting arguments, which is the exact failure this subsystem exists to
remove. Note `brave/adblock-rust`'s `data/brave/brave-resources.json` is the
right file — `brave/adblock-resources`'s `dist/resources.json` is Brave's own 17
custom scriptlets and carries no uBO library at all.

**2. PROCEDURAL cosmetics.** On top the engine hands back `procedural_actions`
as a set of JSON strings — `{"selector":[{"type":"css-selector","arg":"p"},
{"type":"has-text","arg":"Ad"}],"action":{"type":"remove"}}`, no `action` key
meaning hide — which `Cosmetic.proceduralJson` passes through **unmodified** for
`CosmeticInjector`'s runtime to apply. The engine does not apply them. **This is
the only route by which a `##…:style(…)` rule now arrives at all**, since
`style_selectors` is gone and such rules are absent from `hide_selectors`;
dropping procedural handling loses them outright. On book there is no such
field, so `_scan_procedural()` re-reads the raw lists and recovers the subset
Chromium evaluates natively — `:has()` with no uBO-only pseudo-class beside it,
1126 rules over 1027 domains, all domain-specific — and emits it as plain CSS
through `specificCss`. The two are mutually exclusive by construction:
`proceduralJson` is `[]` on book precisely because those rules already went out
as CSS, and the pre-scan never runs on top because `:has()` is already in
`hide_selectors` there.

**3. A PARSER BUG in the legacy engine.** `_sanitize()`. An element-hiding
exception whose `domain=` mixes positive and negated entries —
`@@*$ghide,domain=a.com|~www.a.com`, one line in uBO's `filters-2024.txt` — is
read as "everywhere except", turning `generichide` on for **every site** and
disabling generic cosmetic filtering wholesale (boards.4chan.org 539 hide
selectors → 1). Dropping the negations restores the narrow intent. Fixed
upstream by 0.12.5 — measured identical with and without on the fork — so on top
it is a no-op, and it stays for book.

**The escape hatch, and the one rule set that is ours.** EasyList deliberately
allow-lists 4chan's self-hosted ads (`@@||4cdn.org/adv/`,
`@@||4channel.org/adv/`), so `_CUSTOM_RULES` re-blocks those paths with
`$important` — the only operator that beats an `@@` exception, and a *path*
rule because blocking the host would take out `s.4cdn.org`'s stylesheets and
`i.4cdn.org`'s images. `$important` is **final** in this engine (measured: no
exception undoes it, not even `@@…$important`), so `~/.config/surfer/blocklist.txt`
cancels one by *suppressing* it (`_custom_rules`) rather than by allow-listing
over it — otherwise the documented override would silently do nothing. That
file also now takes **verbatim Adblock rules**, not just hosts, alongside the
`host` / `!host` forms.

**The compiled-engine cache is stamped** (`engine.meta`) with the `adblock`
version, the resource source, the subscription set and `blocklist.txt`'s
contents. Without it, adding a list or editing `blocklist.txt` changed nothing
until the 7-day refresh happened to fire — and the package bump would have fed
the fork a `engine.dat` written by 0.5.6 (adblock-rust's DAT has had no
cross-version compatibility since 0.10.0; measured, that raises
`DeserializationError: VersionMismatch(0)`, which `_load_engine_cache` catches
**by class name as well as by type**, since the class is not importable from
every binding). **Bump the `vN` literal in `_cache_stamp` whenever you change
how the engine is BUILT**; the hashed inputs can only see a data change, never
a code one.

**Slots `CosmeticInjector` calls:** `specificCss` (raw CSS), `proceduralJson`
(engine actions, verbatim), `specificJs` (CSS + scriptlets, the fallback
carrier), `genericJs`. Add to those rather than making the injector read CSS
back out of `specificJs`'s output.

**Run `tools/adblock-test.py` under BOTH pythons** — the surfer wrapper's pyEnv
and one holding PyPI `adblock` 0.6.0 — after touching resources or procedural
code. It detects which engine it has and asserts the matching branch; both
currently pass with the same scratch cache directory, each correctly discarding
the other's `engine.dat` and `resources.json`.

Everything logs through `AdBlocker._log`, so `grep 'surfer adblock:'
~/.cache/surfer.log` is the whole subsystem: which lists were fetched, how many
resources registered, how many hide-exception rules were repaired, how many
procedural rules were recovered, and why a cache was discarded.

## Cosmetic ad-blocking rides the PROFILE, at document creation

Element hiding is a **profile-level `QWebEngineScript`** (`COSMETIC_RUNTIME_JS` +
`CosmeticInjector` in `main.py`, registered by `sharedProfile`'s
`Component.onCompleted` in `Main.qml`), not a per-view `runJavaScript` at
load-finished. The old placement was late by construction: the ads had painted,
nothing re-ran after `history.pushState` (i.e. all of YouTube after the first
click), and a lazily-inserted ad slot brought no new rules with it.

**A profile script is compiled once for every page, so it cannot carry one
site's selectors.** It is a courier: rules are pulled per-page out of Python
over the `surfercos://` scheme, whose five hosts each take a base64url JSON blob
as their path (the `gmxhr` convention) —
`s` (specific hide CSS, `text/css`), `x` (the scriptlets, alone), `g`
(`Cosmetic.genericJs`, narrowed to the page's own class/id tokens), `p`
(procedural filters, JSON), and `j` (`Cosmetic.specificJs` verbatim — the
fallback path only, see below).

**Why the flash is actually gone, and what you must not undo.** Measured on
PySide6 6.11 (`tools/cosmetic-test.py`): at `DocumentCreation`,
`document.documentElement` is still **null**. Anything that waits for a parent —
a `<style>`, a `<script>`, even a `MutationObserver` on `document` — lands after
the parser has built the whole body, and the ad gets a frame (verified: the ad
was still `display: block` in the page's first `requestAnimationFrame`). Exactly
two things work with no DOM, and the runtime is built on both:

- a **synchronous `XMLHttpRequest`** — the reply comes from `CosmeticInjector`
  in-process, no network and no disk; and
- **`document.adoptedStyleSheets`** with a constructed `CSSStyleSheet`, which is
  also exempt from `style-src`, so this is the CSP-proof path as well as the
  fast one.

So the specific rules — the ones that depend only on the url and can therefore
be known this early — are fetched and adopted inside the document-creation
callback itself. Everything that genuinely needs a DOM is deferred.

**Never `eval`/`new Function` engine output.** Deferred JS runs as a
`<script src="surfercos://…">`; the scheme is registered
`ContentSecurityPolicyIgnored` (like `gmxhr`/`surfercmd`), which is what lets it
run on a site with a strict `script-src` — `new Function` would not survive one.

**MAIN world, deliberately, and it is now load-bearing twice over.** An isolated
world gets its own `history` wrapper, so a `pushState` hook installed there
never sees the page's own calls. And uBO's `json-prune`-shaped scriptlets — the
YouTube payload is exactly this: it shadows the page's own player response —
are **completely inert** anywhere but `ScriptWorldId.MainWorld`. Do not move
this to `ApplicationWorld` to "isolate" it.

**Scriptlets are separated from the CSS on purpose, and fetched separately.**
They have to run EARLIER than the CSS can be appended: at document-start, before
the page reads its own globals. Run as one blob at document creation they would
not run at all — `Cosmetic._inject` appends the `<style>` first, and with no
`documentElement` that throws and takes the whole outer `try` (scriptlet
included) with it. So `x` serves the scriptlet alone and the runtime `eval`s it
inside the document-creation call. This is the ONE eval on this path and it has
a fallback: a page whose CSP forbids `unsafe-eval` gets the same code as a
`<script src>` off the CSP-ignored scheme as soon as there is a parent. Late
beats inert.

**Two string seams, and what happens when one breaks.** Until `Cosmetic` grows
`specificCss` / `scriptletJs` slots (both are preferred automatically if they
appear), `CosmeticInjector` recovers the CSS and the scriptlet from
`Cosmetic._inject`'s JS by `var css=` (read back with a JSON decoder, so any
selector content is exact) and by the trailing `try{…}catch(e){}`. Both return
**None**, never `""`, when the seam is gone — "no rules here" and "could not
read them" must stay distinguishable. On None the `s` body becomes the
`/*surfer-fallback*/` marker, the runtime falls back to running the engine's JS
the old (late) way over `j`, and one line goes to stderr. A change on the engine
side therefore costs the head start, not the blocking.

**Injected CSS is author-origin with `!important`, and there is no better
option here.** User-origin would win over page author rules without an
`!important` war, but the only APIs that grant it are the WebExtensions
`scripting.insertCSS({origin:"user"})` and CDP — QtWebEngine exposes neither,
and a constructed `CSSStyleSheet` is author-origin by definition. The engine
already emits `!important` on every hide rule, so this costs nothing today; it
is written down so nobody re-derives it.

**Accumulate adopted CSS, never replace it.** An SPA route change re-asks for
the new url's rules; on the same host the engine returns the same string and the
dedupe keeps the sheet at one entry, but where it does not, a `replaceSync` of
just the new rules silently UN-hides what the previous route hid while that DOM
is still on screen. The harness gives its two routes deliberately different
rules for exactly this reason.

**The observer has an escape hatch, and it is not optional.** Above ~400
mutation records/second the `MutationObserver` **disconnects** in favour of a
plain poll and comes back 10 s later (Brave's design). A throttle alone still
pays the per-record cost, and ad-heavy pages genuinely storm. The observer only
ever harvests the class/id **tokens** of *added* nodes, each asked about exactly
once — no selector matching in JS, no full-document re-query per mutation.

**Procedural filters are the embedder's job.** adblock-rust returns
`procedural_actions` as a set of JSON strings and does *not* apply them;
`CosmeticInjector._procedural` unwraps either shape (set/list of strings, or one
JSON document) so the page only ever sees objects. **No `action` key means
hide.** `##…:style(…)` arrives ONLY here since adblock-rust 0.12.5 dropped
`style_selectors`, so the `style` action is not optional — without it those
rules vanish silently. `runProc` compiles the operator chain
(fast path: a leading `css-selector` is resolved with `querySelectorAll` and the
chain starts at index 1) and applies the action **by attribute** — a random
per-page `data-surfer-*` tag plus one attribute per distinct style string,
backed by a stylesheet rule — never `element.style`, which a page can watch and
undo. `remove-class`/`remove-attr` check before removing, because both fire a
mutation even when they remove nothing, and that is how a filter becomes an
infinite loop. **An unknown operator must yield nothing, never everything.**

Nothing on this path inspects, rewrites or filters a selector, so `:has()` and
anything else the engine emits reaches the page verbatim.

Verified headlessly by **[`tools/cosmetic-test.py`](tools/cosmetic-test.py)** —
19 checks against a real offscreen QtWebEngine profile and a local page: hidden
before the parse-time script *and* before the first frame, a `json-prune`-shaped
scriptlet shadowing a page global before the page reads it, a lazily-inserted
slot, an SPA route change picking up the new url's rules without dropping the
old ones, `:has()` passthrough, the procedural operators and their by-attribute
styling, an unknown operator hiding nothing, a 1500-node mutation storm, and
both string seams (including the "seam is gone" case). Run it after touching
either half.

## Dark mode applies at DOCUMENT-CREATION, not after images load

The page style used to be injected per-view at
`LoadSucceededStatus`, i.e. AFTER images and scripts had finished — the page
painted light first and flipped dark only once everything loaded. It is now a
profile-level **document-creation courier**, exactly like cosmetic ad-blocking.
The style it carries has three parts (all computed by `DarkMode`):

- **the font-inherit layer, always on** (2026-08-08, his ask: pages inherit
  the system font in apparent size/styling/rendering): an `@layer` block that
  sets the live pick + desktop font size on `:root`, the monospace elements
  and the form controls, plus `font-synthesis:none` (§2.2's no-bold — the
  shipped faces are Regular-only). A layered author rule loses to ANY
  unlayered page rule, so this is an upgraded user-agent default, not a force
  — a site's own font styling always wins, which is what keeps it inside
  `docs/DESIGN.md` §16's family-only settlement. Rasterisation parity comes
  from the faces' fontconfig pins, which Chromium honours (verified by
  canvas raster offscreen 2026-08-08: mono glyphs, ink and advance identical
  to the QML PixelText pipeline at 15px). The layer's size is **divided by
  the shared page zoom AND the face's x-height size-adjust** (`Zoom.levelChanged` chained onto
  `darkmode.changed`, like `style.changed`), because zoom multiplies every
  CSS px on the way to the screen — at his live 0.83 the pixel font was
  rasterising at ~12.4 device px, which is what *"more perfect doesn't look
  like a pixel font anymore"* was. Same idiom as the scrollbar's
  zoom-compensated width. Site-styled text still zooms; only the inherited
  default holds the desktop's device-pixel size. The ÷adjust is the second
  half of the 2026-08-09 x-height settlement: the inherited text's computed
  px shrinks so the 1.14x face still lands on the desktop's 15 device px.
- **the dark filter** (global toggle, per-site exceptions), top frame only;
- **the system-font force** — the desktop family imposed on page text so ALL
  of a page reads in the pick, not just the runs a site left unstyled.
  GLOBAL with per-site exceptions (`fontOff`, dark mode's whitelist shape;
  it was opt-in per-site until 2026-08-08 — his: the inherit layer alone
  *"fails to capture all the text in a given webpage"*). Family only +
  `font-synthesis:none`, never sizes — the full reskin was retracted,
  `ad868e4` / DESIGN.md §16 — and icon-font elements (`_ICON_CARVE`) are
  excluded by class so pictogram fonts don't render as tofu. Since 2026-08-09
  the family it imposes is a **size-adjusted `@font-face` alias** (the pick +
  `" (web)"`, `src:local()`, `size-adjust:114%`, `font-weight:1 1000` +
  an italic twin): the pixel face's x-height is only ~44% of its em against
  the ~51% of the proportional fonts a site's sizes were designed around, so
  the site's size numbers render at the proportional x-height the site
  assumed — sizes still never imposed, apparent scale adjusted. Measured
  offscreen 2026-08-09: an adopted-sheet `@font-face` with `size-adjust`
  renders scaled exactly (document.fonts.check() lies about adopted sheets;
  the canvas ink does not), bold/italic requests match the range'd rule.

The plumbing:

- `PAGE_STYLE_RUNTIME_JS` in `main.py` + `PageStyle.scripts` (a
  `QWebEngineScript`, `DocumentCreation` / `MainWorld`, `RunsOnSubFrames` **on**
  since the inherit layer: a subframe asks the scheme for the fonts-only body
  (`f`) and never the dark filter — the top view already composites its
  iframes through its own `html` filter, a subframe copy would double-invert)
  is assigned onto
  `sharedProfile.userScripts.collection` in `Main.qml`, **concatenated** after
  `CosmeticInject.scripts`.
- At document creation it pulls the frame's style CSS from Python over the
  `surferstyle://` scheme (`PageStyleHandler`, a `QWebEngineUrlSchemeHandler`
  fed by `DarkMode.css(url)` for `s` / `DarkMode.fontsCss(url)` for `f`) and
  adopts it as a constructed `CSSStyleSheet` via
  `document.adoptedStyleSheets` — CSS rules match as the DOM builds, so the
  theme is on the page from its first frame. CSP-proof (`style-src` never sees
  it), and it never `replaceSync`-clobbers cosmetic's sheet (concat-only).
- **Live settings changes** (global toggle, brightness/contrast sliders,
  per-site exceptions/font toggles, and — via `style.changed` chained onto
  `darkmode.changed` in `main()` — a Settings > pixel font / font size change)
  still re-apply to open pages with no
  reload: `DarkMode.changed` → `win.reinjectDark()` → each view runs
  `window.__surferPageStyleRefresh()`, which re-fetches and re-adopts (or
  **strips** the sheet when the new state is off). Top frames only — an open
  subframe follows at its next navigation. `DarkMode.js(url)` remains
  the in-process/manual apply (the find-pixel harness drives it directly); it is
  *not* the live path any more.

Verified headlessly by **[`tools/pagestyle-test.py`](tools/pagestyle-test.py)** —
a real offscreen profile carrying **both** couriers via the exact `concat` line
Main.qml uses: the invert filter is present at the page's own parse-time inline
script *and* in its first `requestAnimationFrame` (both before any paint), still
present once settled, and a brightness change live-refreshes an open page while
off strips it back to `none`; plus the font checks — unstyled text inherits
the pick at the desktop's apparent size (the size-adjusted alias renders the
same ink as the raw 15px face), a page's own font styling beats the
layer, a subframe gets the face but never the filter, and the per-site force
imposes the family while the page's font-size survives (and its ink renders
~1.14x — the proportional x-height). Run it after touching
`main.py`'s
dark-mode block, `PAGE_STYLE_RUNTIME_JS`, `PageStyle`/`PageStyleHandler`, or the
`Main.qml` profile/courier wiring.

## OneeChan inherits the live wallpaper palette

The **OneeChan** userscript themes 4chan pages, but it bakes its own hex colours
(not CSS vars) into one `<style id=ch4SS>` it builds from its private `$SS`
theme — a var in a top-level IIFE, unreachable from outside, so its theme cannot
be re-driven without a **page reload** (which loses scroll position and
half-typed replies). So rather than poke OneeChan, surfer adopts its OWN
stylesheet from the live wallpaper palette (the same `WalPalette` the chrome and
the dark-mode courier read) and lets the CASCADE win: an adopted stylesheet
orders AFTER any document `<style>`, so with the SAME selectors + `!important` it
beats `ch4SS` on ties. No OneeChan internals are touched; **his tabs are never
reloaded.**

Exactly the dark-mode courier's shape, on a parallel scheme:

- `ONEE_THEME_RUNTIME_JS` in `main.py` + `OneeTheme.scripts` (a
  `QWebEngineScript`, `DocumentCreation` / `MainWorld`, `RunsOnSubFrames`
  **off** — OneeChan themes the board page, not its iframes) is `.concat`-ed
  after `PageStyle.scripts` onto `sharedProfile.userScripts.collection` in
  `Main.qml`.
- It pulls the palette-derived CSS from Python over the **`surferonee://`**
  scheme (`OneeThemeHandler` fed by `OneeTheme.css(url)`) and adopts it as a
  constructed `CSSStyleSheet` via `document.adoptedStyleSheets` (CSP-proof,
  concat-only so it never clobbers cosmetic/page-style sheets).
- **Two guards.** It runs only on 4chan hosts (`boards.4chan(nel)?.org`), and it
  **self-gates**: it adopts only once `document.documentElement` carries the
  `oneechan` class (OneeChan sets `html.oneechan` on init) — so the re-skin
  rides ONLY when OneeChan is actually active, never on bare 4chan. It polls for
  the class (~60s cap) since OneeChan marks the page after document-creation.
- **Live**: `WalPalette.onChanged` → `win.reinjectOnee()` → each view runs
  `window.__surferOneeThemeRefresh()`, which re-fetches + re-adopts (or strips
  the sheet if OneeChan went away) — no reload. Same `Connections{target:
  WalPalette}` block that drives `reinjectScrollbar`/`reinjectDark`.

The role→palette map (`OneeTheme._css`, selectors mirroring `ch4SS` verbatim so
specificity ties and cascade order decides): body bg=`bg`, reply/dialog
bg=`bgAlt`, borders=`border`, field bg=`highlight`, post text=`text`,
links=`dim` (hover `accent`) — but the non-hovered link is run through
`_legible_link` first: on a **dark** palette `dim` sits too close to the page
background to read (DESIGN.md §3.2 "contrast is measured"), so its HSL lightness
is lifted (hue/saturation kept, so it stays palette-derived) until it clears a
~4:1 contrast floor against the background, capped just under the hover accent so
hover still reads brighter; a light palette and the hover colour are untouched —
greentext + names=`ok`, tripcodes=`warn`,
subjects/board titles/quotelinks=`accent`, backlinks=`info`, post
highlight=`highlight`. Every rule is `!important`, because `ch4SS`'s are.

Verified headlessly by
**[`tools/oneechan-theme-test.py`](tools/oneechan-theme-test.py)** — a real
offscreen profile carrying the exact `concat` line, `boards.4chan.org` mapped to
loopback (`--host-resolver-rules`) so the host gate passes: over a baked
ch4SS-style baseline the palette colours win on body/reply/links/quotelinks
(proving adopted-after-`<style>` + `!important` beats ch4SS on ties), a
`WalPalette` change (the watched `Theme.qml` rewritten) live-re-skins the open
page, and a page WITHOUT `html.oneechan` keeps its baked baseline untouched (the
self-gate). Run it after touching `main.py`'s `ONEE_THEME_RUNTIME_JS`,
`OneeTheme`/`OneeThemeHandler`, the `surferonee://` registration, or the
`Main.qml` `reinjectOnee`/courier wiring.

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
- **Right-clicking a tab pops a tab menu** (Close / Close others / Close to
  right / Reload / Duplicate) at the click point. The tabs are plugin-drawn —
  no QML MouseArea ever sees a right-click on one — so the menu rides a new
  `RCLICK <id> <x> <y>` verb the plugin sends on the press (window-local
  coords); see `vtbclient.py`'s docstring and `Main.qml`'s `showTabMenu`.
  Triggers re-resolve the tab by tid, so a list that shifted between the
  right-click and the menu click still acts on the same tab.
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
clicking the menu entry always does something visible — but only when a human
asked for it; see "The handoff is a loaded gun" below).

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
  `SURFER_ALLOW_HANDOFF=1` / `SURFER_DESKTOP_LAUNCH=1` re-permit a bare, no-URL
  invocation (below).
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

### The handoff is a loaded gun, and it went off (2026-07-30)

**Three DuckDuckGo tabs appeared in his browser while he was using it.** An
agent wanted surfer's Qt environment for an offscreen harness, took the packaged
wrapper, stripped its last line and sourced the rest — three times. Stripping
the last line removes the `exec`; it leaves *line 3*, the `singleton.py "$@"`
probe, which with no argv sends `OPEN` with an empty url, which is `homeUrl`,
which is `https://start.duckduckgo.com/`. One tab per source. (Line 4,
`exec > ~/.cache/surfer.log`, then redirected the agent's own shell.)

**Never source a wrapper. `surfer-qtenv` is the supported way** —
`surfer-qtenv <cmd>...`, or `eval "$(surfer-qtenv)"` in a subshell. Same
`wrapQtAppsHook` environment plus surfer's own python on `PATH`, none of the
body. See `apps/AGENTS.md` → Verifying changes.

Three guards, so the class cannot recur rather than merely being written down:

- **The wrapper refuses to be sourced** (`sourceGuard` in
  `home/prog/surfer.nix`, both host branches, emitted as the FIRST line of the
  body): `BASH_SOURCE[0] != $0` → a message naming `surfer-qtenv`, and
  `return 1` before the probe.
- **`singleton.refusal()` refuses a bare, no-URL invocation** from a caller
  with no tty, whether or not a browser is running — so it can neither open a
  tab in his window nor a window on his screen. It is keyed on *no URL*, not on
  *no tty*, because every legitimate programmatic caller (a link click through
  `surfer.desktop`, anything using `$BROWSER`) names a URL and must keep
  working. `try_handoff` exits **3**; the standalone probe exits **0** so the
  wrapper stops there instead of falling through to a launch.
- **`SURFER_DESKTOP_LAUNCH=1` is set by `surfer.desktop`'s `Exec=`**, marking
  the one legitimate no-URL launch — the runner, Plasma's `BrowserApplication`.
  `SURFER_ALLOW_HANDOFF=1` is the manual override. An offscreen launch is
  excused only when `SURFER_NO_SINGLETON=1` is also set: offscreen alone still
  reaches his running browser over the socket, because the handoff happens
  before Qt exists.

Verified offscreen against a fake socket server standing in for his browser —
bare/no-tty sends nothing (rc 0, rc 3 via `try_handoff`), a URL still hands off,
both markers still hand off, and a real pty still hands off — plus the whole of
`tools/find-test.py` run through `surfer-qtenv`, and the built wrapper sourced
in a sealed env (guard fires, no process, no log).

## Memory — discard idle background tabs, cap the disk cache

**Where surfer's memory actually goes is the render process tree, and the lever
is QtWebEngine's page lifecycle, not cache knobs.** Measured offscreen
(`tools/mem-test.py`, real shared-profile views over loopback): a tab that has
ever loaded keeps a full renderer alive even hidden — **6 loaded tabs → 6
renderers, ~1217 MB of tree RSS (VmRSS summed across the whole process tree,
not just the main python process), and hiding the 5 background tabs changed
nothing by itself (+1 MB).**

- **`win.discardIdleTabs()` (Main.qml) is the fix.** QtWebEngine's
  `WebEngineView.lifecycleState` (enum `WebEngineView.LifecycleState.`)
  `Discarded` tears a hidden page's renderer down. The same 6-tab measurement
  after discarding the 5 hidden tabs: **1 renderer, ~606 MB — a ~617 MB / ~51 %
  drop.** Re-selecting a discarded tab sets it back to `Active`
  (`onPaneChanged`), which is what reloads it.
- **It never discards the on-screen pane** (`v.pane >= 0`), **never a cold
  restored tab** (`v.cold` holds no renderer), and it is deliberately
  conservative about the rest: the **`discardKeepCount`** most recently used
  hidden tabs are **never** discarded whatever their age, and only a hidden tab
  *beyond* that count is reclaimed, and only once it has been off-screen for
  `win.discardAfter` (**30 minutes by default**; it used to be 10). The reload
  cost is why — a just-used tab stays instant, and only an abandoned tab gives
  its memory back. A 30 s `Timer` walks `viewRep` and discards a hidden tab
  only when it is both older than the threshold AND past the kept-warm count.
- **Freezing is NOT a memory lever.** `Frozen` pauses JS/timers but keeps the
  renderer's V8 heap and caches — measured at ~+1 MB. It is a CPU/power saver,
  not an RSS one, so surfer only uses `Discarded`.
- **The disk cache is capped, separately.** With no cap Chromium let
  `~/.cache/surfer/surfer/QtWebEngine/surfer/Cache` reach **1.3 GB**.
  `_wire_profile` now calls `prof.setHttpCacheMaximumSize(512 MB)` (the QML
  profile object exposes the setter, verified) — it bounds that runaway disk
  growth and the in-memory cache index with it, at a level that does not make
  repeat visits re-fetch. This is cache sizing; the RSS win is the discard.
- **The render-process model is left at the default** (process-per-site-instance
  already shares one renderer across tabs of the same site, and the discard
  above reclaims the rest). `--process-per-site` / `--single-process` trade
  sandbox isolation for a little more memory and are not worth it.

**`tools/mem-test.py` is the kept measurement harness** (+ its `mem-test.qml`
fixture): N shared-profile views over loopback, `--none`/`--freeze`/`--discard`
modes, and it prints tree RSS *and* `--type=renderer` process count before and
after. It also drift-guards that Main.qml still carries the five discard tokens
and that main.py still caps the cache. Run it with `surfer-qtenv python3
apps/surfer/tools/mem-test.py --tabs 6 --discard`.

## Profile handoff between `top` and `book` (2026-07-26)

`tools/sync.py` merges the two machines' browser state; `home/prog/surfer.nix`'s
**air** wrapper brackets the run with it (`pull` before the window opens, `push`
after it closes; `SURFER_NO_SYNC=1` opts out, and the sync is timeout-bounded +
`guard_reachable`-gated (a 2 s hard deadline on resolving `top` — ssh's
`ConnectTimeout` does not cover DNS, and off the LAN/tailnet the bare name
takes ~8 s to *fail*, paid before the window could open) +
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
mDNS, while plain DNS resolves `top` to its LAN address. (The address itself
is not written down here on purpose — this repo is public; run `getent hosts
top` if you need it.)

# surfer — QtWebEngine browser

Live Python/QML source, packaged by home/prog/surfer.nix. Read ../AGENTS.md
for shared Qt, packaging, and test isolation rules.

## Launch and profile ownership

A persistent Chromium profile has one process owner. singleton.py is a Qt-free
AF_UNIX client called before importing PySide6; SingleInstance/QLocalServer
receives URLs through Instance.openUrl and normalizes them into new tabs.
Use $XDG_RUNTIME_DIR/surfer-<uid>.sock (/tmp fallback, mode 0600);
SURFER_SOCKET overrides it. Remove a stale socket only after connect fails.
A failed listen must not steal another process's socket; handoff failure falls
back to normal launch. Do not force focus through compositor actions.

Never source a packaged wrapper, even with its final exec removed: its early
handoff can open tabs in the live browser. Use surfer-qtenv <cmd>, or its
environment output in a subshell. sourceGuard rejects sourcing before handoff.
singleton.refusal rejects non-tty, no-URL launches unless marked by
SURFER_DESKTOP_LAUNCH=1 or SURFER_ALLOW_HANDOFF=1; URL launches remain valid.
Refusal returns 3 from try_handoff and 0 from the standalone wrapper probe.

Offscreen alone does not isolate the socket. Harnesses need
SURFER_NO_SINGLETON=1, SURFER_NO_SYNC=1, scratch HOME/XDG paths, and the
offscreen/session guards. A bare singleton.py invocation is an action, not a
read-only probe.

### Titlebar and input

Titlebar.__init__ stages _SEED_BUTTONS and title_edit=True before the VtbClient
I/O thread starts, so the first REGISTER includes the chrome before mapping.
Main.qml.tbButtons remains authoritative and refines that seed. The plugin
must also take its initial registration snapshot in the decoration constructor;
waiting for its heartbeat reintroduces the default-bar flash.
Test with apps/pylib/tools/vtb-register-test.py case_seed.

Window.title displays page title (URL fallback); Titlebar.setEditSeed(curUrl)
sends EDITSEED so editing opens the URL. Submission remains ADDR <url>; blur
returns to the title. This requires hyprvtb >=3.34.

Wire WebEngine spellcheck imperatively in _wire_profile; QML spellCheck
properties are ineffective on this stack. _spell_language resolves an installed
.bdic filename, not a locale: top uses en-US under QTWEBENGINE_DICTIONARIES_PATH,
book uses Fedora's en_US. isSpellCheckEnabled alone does not verify a dictionary.
Only web-page prose is checked; path/find fields are excluded.

ZoomFilter rescales touchpad wheel input using shared pylib/kinetic.py constants.
QML scroll surfaces undo the window-wide scaling with wheelGain: WheelGain.
Pass mouse detents unchanged; Chromium pages rely on the compositor's withheld
axis stop to suppress their own fling.

## Find, video, and file dialogs

FindBar and window-scoped HotkeyFilter own Ctrl+F. Chromium consumes ordinary
QML Shortcuts when a page has focus; QApplication-wide filters crash this stack.
Do not claim Escape globally: only the find field uses it to close the bar.
Read counts from findTextFinished, not the ineffective findText callback.
Search win.current and clear old highlights with findText("") on pane/tab
changes. Reissued queries may resume at an existing match.

CSS Custom Highlight ranges provide palette-visible marks under dark mode;
DarkMode.compensate inverts the page filter for their colours. Chromium still
owns count/index/scrolling. Drop ranges without client rects, and suppress only
the current-match mark if the custom walk disagrees with Chromium's count.

Keep host-specific video workarounds in main(). On top,
--disable-features=AcceleratedVideoDecodeLinuxGL avoids the NV12 shared-image
backing failure that loses the page's GL context. Book's
--disable-gpu-memory-buffer-video-frames and Vaapi-only flags do not substitute
for that top workaround. SURFER_GPU=hwvideo permits a deliberate isolated
retest after graphics/Qt changes.

FilePicker.qml queues Chromium requests; Files.pick/picked delegates to
filer --pick <spec.json>. Open/OpenMultiple map to open + multiple,
UploadFolder to dir, Save to save; defaultFileName becomes current_name.
CancelPick kills a request's subprocess. Every failure must dialogReject;
otherwise the page can leave its file input disabled. Only the focused tab's
requests open dialogs; preserve per-view queues and remembered directories.
Use FILER_BIN stubs in tests.

## Downloads and Instagram

Downloads.progress owns the toast gate: SLOW_MS (1.5s) or LARGE_BYTES (3MB),
with whole-percent throttling. QML forwards elapsed time and byte changes.
Progress uses a persistent replacement ID; completion/failure uses a normal
timeout. Downloads.done receives the absolute path and adds x-download-image
only for completed image extensions, aligned with filer's IMAGE_EXTS.
See the panel guide for moved-file resolution and notification rendering.

Repair extensionless suggested names with Downloads.fileName(suggested, mime)
before accept(). _looks_like_ext recognizes up to five alphanumeric characters;
MIME_EXTS/mimetypes supply missing extensions. application/octet-stream must
not invent one.

Instagram original-image saving resolves the click through overlays with
elementsFromPoint, then chooses the largest srcset candidate. Preserve signed
CDN query parameters; stripping resize tokens invalidates signatures.
IG_RESOLVE_JS feeds ImgDownload/UrlDownloader with UA + Referer and shares
Downloads' filename/progress handling. Empty resolution reports notFound.

IG_LAYOUT_JS identifies opened posts by media size and side-by-side ancestor
geometry, not hashed classes. It stacks media above the sidebar and leaves
already vertical feed posts alone. Inject once and recheck via debounced
MutationObserver and pushState/replaceState/popstate hooks for SPA navigation.

## Ad blocking

AdBlocker and Cosmetic support both top's newer jampe binding and book's legacy
PyPI adblock 0.6.0. Feature-detect APIs; do not choose by host/version.
Log through AdBlocker._log in ~/.cache/surfer.log.

- _resource_source checks Engine.add_resource versus add_resources. Modern
  resources come from adblock-rust's brave-resources.json; legacy resources
  are assembled from uBO 1.48.6 scriptlets and redirect assets. The separate
  Brave custom-resource file is not the full uBO library.
- Stamp resources.json with its source; wrong-format registration may silently
  stop argument substitution. Without resources, injected_script is empty.
- Modern procedural_actions pass through proceduralJson unchanged; absent
  (None) differs from an empty set. The legacy _scan_procedural recovers
  supported domain-specific :has() as CSS instead. Keep paths exclusive.
- Legacy _sanitize repairs mixed positive/negative domain generichide
  exceptions; the modern branch needs no repair.
- _CUSTOM_RULES overrides only the ad paths, using $important. User blocklist
  overrides suppress those custom rules; an exception cannot undo $important.
  blocklist.txt accepts hosts, !hosts, and verbatim rules.
- engine.meta stamps binding version, resource source, subscriptions, and
  blocklist contents. Bump _cache_stamp's vN when engine-building code changes.
  Catch deserialization errors by class name as well as type across bindings.
- Keep separate specificCss, proceduralJson, specificJs, and genericJs slots.
  Run tools/adblock-test.py with both bindings and scratch caches.

### Document-creation injection

COSMETIC_RUNTIME_JS/CosmeticInjector is a profile-level MainWorld script.
The surfercos scheme uses base64url JSON paths: s = CSS, x = scriptlets,
g = generic rules, p = procedural JSON, j = fallback specificJs.
Do not embed one page's selectors in the shared profile script.

At DocumentCreation, documentElement may be null. Synchronously fetch specific
CSS through the in-process scheme and adopt a constructed CSSStyleSheet before
the DOM/first frame. Author-origin !important rules are the available mechanism;
QtWebEngine does not expose user-origin WebExtension/CDP CSS injection.

Scriptlets must run in MainWorld to intercept page globals/history. The early
scriptlet path evaluates only the x body; if CSP blocks it, use a script src
from the CSP-ignored scheme once a parent exists. Deferred injection must not
depend on eval/new Function. Keep scriptlets separate from DOM-dependent CSS.

Prefer specificCss/scriptletJs slots; legacy extraction from _inject uses JSON
decoding for var css and the trailing try/catch. An unreadable seam returns
None, distinct from empty content, emits a diagnostic, and switches through the
surfer-fallback marker to j. Preserve blocking even when early injection fails.

Accumulate adopted sheets across SPA routes; replacing with only the newest
rules can unhide old DOM. Harvest added-node class/id tokens once. Above about
400 mutation records/second, disconnect the observer, poll, then reconnect
after 10 seconds; throttling alone still pays per-record cost.

Normalize procedural JSON into objects; absent action means hide. Support the
modern style action, tag matches with random per-page data-surfer attributes
and stylesheet rules, and avoid element.style, which pages can undo.
Check before removing attributes/classes to avoid mutation loops.
Unknown operators match nothing. Pass engine selectors through unchanged.

## Page styling

PAGE_STYLE_RUNTIME_JS/PageStyle runs at DocumentCreation in MainWorld.
Concatenate scripts with cosmetic injection; never replace its collection.
surferstyle serves full CSS (s) or fonts-only CSS (f); subframes request only
fonts because the top frame already filters their pixels.
Adopt sheets without clobbering other couriers.

DarkMode produces the inherited font layer, optional dark filter, and global
family forcing with per-site exceptions. The inherited @layer yields to page
rules; compensate its default size for page zoom and the installed web twin's
scale. Family forcing preserves site sizes and excludes icon fonts.
Use the real _adj_fam font family, not a local() @font-face alias, so fontconfig
controls rendering. Do not reintroduce the retracted full-page size reskin.

DarkMode.changed reinjects via __surferPageStyleRefresh without page reload.
Style/Zoom changes feed it too. Remove the sheet when disabled.
Existing subframes follow new settings at their next navigation.

OneeChan theme CSS belongs in shared pylib/chantheme.py, also used by Vivaldi.
Surfer only owns the surferonee courier: document-start, MainWorld, top-frame
4chan host gate, concat-only adopted sheet, live __surferOneeThemeRefresh on
palette changes. Do not wait for OneeChan's late marker or reload tabs.
Shared theme/palette and native-surface contracts belong in ../AGENTS.md.

## Split view

The titlebar uses | for side-by-side and _ for stacked (_ avoids the protocol's
reserved spacer token -). toggleSplit opens, closes the active orientation, or
reorients while retaining tabs and splitRatio. No page-conflicting shortcuts.
Pane A is currentTab, pane B splitTab; current/focusTab means the focused pane.

Use the shared axis geometry and keep every emitted rectangle positive even
at tiny sizes. Both panes always contain different tabs: swap instead of
duplicating a WebEngineView, and fold when no second tab remains.
Both tabs are lit; tooltips and the focus frame identify the focused pane.
newTab targets that pane. Track tab identity by tid across reorder and menus.

Flag programmatic focus changes with retargeting and apply focus through
Qt.callLater after visibility settles; hiding a view otherwise transfers
focus to the other pane. Add view x/y to view-relative menu/tooltip coordinates.
Tab RCLICK uses window-local coordinates; re-resolve tid when its action fires.

Persist splitRatio (0.08–0.92, on release), splitVertical (on change), and
session split (-1 for none), with backward-compatible defaults.
Dialogs from an unfocused pane wait in that view's queue.

## Memory and cross-host sync

discardIdleTabs reclaims only hidden, non-cold tabs beyond discardKeepCount and
older than discardAfter (30 minutes), checked every 30 seconds. Reactivate on
pane selection. Frozen pauses work but retains renderer memory; use Discarded.
_wire_profile caps the HTTP cache at 512MB; retain the default process model.

tools/sync.py merges cookies and userscripts; SURFER_NO_SYNC disables it.
Book initiates because it can reach top's SSH server. Use top, not top.local.
Log: ~/.cache/surfer-sync.log. Cookies merge on their unique index by newer
last_update_utc; scripts use rsync --update. Never merge LevelDB stores,
Service Worker, or caches. Sync does not delete; clearing requires both hosts.

Do not delay window creation for sync. _cookie_sync_live starts from
_wire_profile in a daemon thread and repeats every 15 minutes; wrapper push
runs after exit. fetch reads WAL-safe snapshots and returns winning rows;
only Chromium's setCookie writes a live local profile. Other commands retain
guard_local/remote ownership checks. Keep schema/index compatibility checks
and warn if encrypted_value becomes populated: copied encrypted cookies cannot
be assumed portable.

guard_reachable requires a connection to top:22 within three seconds; DNS
success alone does not prove reachability. _remote also needs a hard timeout
for stalled SSH banner exchange. cookie-live-test.py uses synthetic databases.

## Verification

Use surfer-qtenv and isolation described above. Focused tools/ harnesses:
spell-test.py; find-test.py; filepicker-test.py; download-test.py;
instagram-image-test.py; instagram-layout-test.py; adblock-test.py (both
bindings); cosmetic-test.py; pagestyle-test.py; oneechan-theme-test.py;
split-test.py and split-geom-test.py; mem-test.py; cookie-live-test.py.
Shared theme parity is apps/pylib/tools/chan-userscript-test.py.
Use stub notifications, dialogs, daemons, and synthetic profiles. Appearance
and interaction checks on the live browser belong to the user.

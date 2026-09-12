# player — music player

Read [../AGENTS.md](../AGENTS.md) for shared Qt/QML, session safety, and packaging
rules. `home/prog/player.nix` runs live Python/QML source on `top` and `book`
(flake attribute `air`). Source edits take effect at the user's next launch;
do not restart a running player or drive playback to verify a change.

Read private `docs/DESIGN.md` before visual changes and
`docs/agents/his-voice.md` Part A before desktop-visible strings. Operational
procedures and retained failure history live in `docs/agents/player-maintenance.md`;
SMB setup and recovery live in `docs/agents/air-library-share.md`.

## Source map

| Area | Owner |
| --- | --- |
| SQLite schema, scan, library queries, playback, models, IPC | `main.py` |
| Smart-playlist vocabulary and SQL | `SMART_FIELDS`, `SMART_OPS`, `SMART_SORTS`, `SmartLists` in `main.py` |
| Root composition and action table | `qml/Root.qml`; Hyprland window wrapper `qml/Main.qml` |
| Album browsing, track rows, shared row menu | `qml/AlbumGrid.qml`, `AlbumPanel.qml`, `TrackList.qml`, `TrackMenu.qml` |
| Plasma composition and controls | `qml/+plasma/`, `transport.py`, shared `pylib/kdeshell.py` |
| Safe audio-file replacement | `atomicsave.py` |
| Lyrics lookup/cache/writeback | `lyrics.py`, `LyricsProvider` in `main.py` |
| Artist identities (one person, many names) | `artistalias.py`, `qml/AliasEditor.qml` |
| Release identity, details and credits | `releaseinfo.py`, `albuminfo.py`, `infostore.py`, `qml/NowInfoPane.qml` |
| Artist facts and biography | `artistinfo.py`; `albuminfo.py` owns its stage and cache |
| Album write-up parsing | `albumprose.py` (Last.fm and linked Bandcamp album pages) |
| Related music and contributor connections | `relatedmusic.py`; `albuminfo.py` owns queries and requests |
| Last.fm integration | `scrobble.py`, shared `pylib/lastfm.py` |
| Acquisition, repair, migration tools | `tools/`; private maintenance runbook |

Library metadata is in `$XDG_DATA_HOME/player/library.db`, artwork in
`$XDG_CACHE_HOME/player/art/`, and preferences, smart lists, and the tag journal
in `$XDG_STATE_HOME/player/`. Respect each tool's path overrides in harnesses.

## Files, state, and database

- Every audio-file tag/art rewrite must use `atomicsave.atomic_save`, including
  TagWriter, embedded lyrics, tagtool, and ReplayGain. Never introduce an
  in-place `mutagen.save()`. Copy beside the target, retain its extension,
  check space on its filesystem, preserve mtime, fsync, and replace. Writers
  must update affected database metadata; size changes can still trigger scans.
- `TagWriter` coalesces changes by path and field before copying. `tagWrites`
  is `off|log|on` and defaults to `log`; embedded lyrics have their own
  `lyricsEmbed` preference, default on. Do not confuse these gates.
  Accepted tag intents are journaled before the worker delay; shutdown drains
  database writes, but does not wait for tag-file or Last.fm completion.
- `tools/tagtool.py` defaults to dry run, refuses rating/favourite/play-count
  keys, and records undo manifests for apply. Reserved metadata has no
  interchangeable upstream copy. Preserve the guard in both set and remove.
- Scan batch signals coalesce into at most one pending GUI refresh per second,
  flushed on completion. Artwork batches count actual mutations; absent art
  must never publish a change just because the mutation counter is zero.
- The scanner parses files before acquiring a SQLite write transaction, then
  commits a local batch. Never hold the writer lock across tag reads or SMB I/O.
- Absence and unreadability are different. Prune only confirmed missing local
  files under a proven mounted library; traversal/stat failures must preserve
  rows. Any traversal error disables all pruning for that scan while readable
  tracks can still import; report incomplete scans and actual removal counts.
  A disconnected library must retain ratings and history. Remote cached
  libraries do not prune from per-track availability checks.
- `Bridge._track_rows` is the shared listing/availability path. Rebuild album
  aggregates after deletion and defer refresh signals when already building a
  listing. Keep a browse anchor when album rows disappear.
- `AutoScanner` delegates download import to `tools/player-add.py`; do not
  duplicate its move/tag logic. Coalesce changes arriving during an import
  into follow-up work. Watch discovery covers local descendants off-thread and
  excludes remote libraries. Busy rescans retain follow-up requests too. Child
  start failures release busy state and report errors. The importer uses the
  shared Scanner, not a separate deletion/transaction implementation. Manual
  remote scans remain supported.
- `tools/dbsync.py` reconciles by track path, never row id, and never deletes.
  Seed a first database rather than renumbering a scan: saved queues contain
  ids. Snapshot SQLite with `backup()`, never copy an active WAL database.
  Migration tuples are `(table, column, declaration, rescan)`; app-written
  metadata should not invalidate the file mtime cache.
- Rating/favourite/play-count writes use the serialized `metadatawrites.py`
  worker. Pending UI values reconcile on success or roll back with an error;
  tag writes and Last.fm side effects follow a successful DB commit. Never
  wait for a busy SQLite writer during UI interaction. Jobs bind both id and
  path, and their timeout includes time already spent queued.
- Prefs are atomically replaced and report failures through the existing status
  surface; same-value sets avoid a write. Prefs are held in memory. External
  preference edits while player runs can be
  overwritten; `tools/set-pref.py` refuses that case. Keep persistence failures
  observable and preserve the last complete saved state on interrupted writes.

## Search, playlists, and queue

`parse_query` owns both full search and album filtering: free words plus
`genre:` and `year:`. Keep field values separate from the free-text haystack.
Years use `COALESCE(orig_year, year)`; unknown years do not satisfy bounded
queries. An unfinished field term contributes no filter. Album artist lookup
includes contained track artists, and genre metadata derives from tracks.
Keep `tools/library-ipc.py` consistent with the app's matching.

`artistalias.py` owns artist identities: one person, many names. A group is a
list of names stored as one portable row in infostore's user table (scope
`artists`, kind `aliases`), seeded once from `DEFAULT_GROUPS` and his
thereafter; membership is folded equality on the whole name, then a half-typed prefix run
(`MIN_PARTIAL`, one group only) because that is what a search box gets; never
`artist_matches`. Everything
matches through two seams — `Library.query_parts` (search and the gallery
filter) and `Library.artist_tracks` (shuffle artist, browse artist). An alias
widens the ARTIST columns only; folding it into the free-text haystack would
answer a search for the person with every record carrying a track of that name.
Nothing is retagged or merged: albums stay filed under the name they were
released as. `AliasEditor.qml` writes the group, `tools/library-ipc.py` expands
the same way, and `tools/alias-ui-test.py` covers both.

The gallery's multi-selection lives in `AlbumGrid.qml` (`selectedIds`, ctrl
toggles, shift takes the run from `_anchorId`) and is spent through
`Player.playAlbums/queueAlbums/playAlbumsNext`, which concatenate whole albums
in the order handed over. A model reset clears it: the covers picked are not
the ones a new filter or sort shows. `tools/album-multiselect-test.py` drives
the real gestures against `album-playnext-test.py`'s stubs; add fake Bridge
slots there rather than starting a second stub set.

Search retains the complete matching id set and pages its display in 400-row
chunks with an exact total. Play-all uses every match; clicking a page row
starts at its global result offset. Search display must not stat remote files
on the GUI thread.

Smart lists store specs, not membership. Built-ins seed an absent store;
restore-defaults adds missing names without overwriting edits. Bind SQL values,
allowlist sort expressions, use Unicode `cfold`, tolerate invalid rules, and
reverse only the primary sort column. Ratings are FMPS 0..1, displayed as 0..5;
retain `_STAR_EPS` for existing 0.79/0.99 tags. The editor gets vocabulary from
Python and edits a working copy; cancel must not mutate the store. Avoid
rebuilding text-field delegates on each keystroke. Suspend global Space/Escape
while its modal owns input.

`TrackMenu` is shared by every track listing and the now-playing header. Parent
menus to the window content so narrow lists cannot clip them. Lists emit
navigation requests; the root owns navigation. Queue actions operate on ids or
indices, and mutate `_orig_queue` with `_queue` so unshuffle preserves edits.
Removing another row must adjust `_index` without restarting the current track.
Long local mpv queues fill in bounded event-loop batches, including manual
skips and tail edits. Queue mutations cancel obsolete batches; appending during
a fill extends that fill without restarting playback. Remote libraries retain
their one-track lookahead.
Play-all uses `start=-1`; a clicked track pins its chosen opener. Loop-all
reshuffles through `_wrap_to_start` without overwriting the original order.

## Playback and external interfaces

- `%F` handling accepts supported paths and file URIs. Known library paths use
  real ids; external tracks use transient negative ids and must never receive
  library tag/stat writeback. An unreadable open is a no-op. With explicit
  paths, restore preferences without resuming or scheduling a stale seek.
- `handoff_paths` runs before Qt: paths send `OPEN`, a bare launch sends `RAISE`.
  The queue socket provides the handoff; there is no SQLite singleton lock.
  Do not remove a socket accepting connections.
- `start_queue_server` owns `$XDG_RUNTIME_DIR/player-queue.sock`. Its source
  docstring is the wire reference: queue snapshots, `GOTO`, percent-encoded
  `OPEN`/`QUEUE`, `RAISE`, and per-connection `LYRICS` subscriptions. Catch and
  report failures without taking down playback.
- Lyrics are opt-in per connection. Clear payload on track change and join
  asynchronous results to the current track id. Send complete lines once;
  the panel derives its current line from MPRIS position.
- `MPRIS_NAME` is the single bus-name definition. Publication is asynchronous;
  retain the later ownership diagnostic. Never claim a harness's name on the
  user's bus.
- `Player._maybe_count` owns the listen threshold and scrobble submission;
  timestamps identify track start. Reassert now-playing on start and resume.
  Shared `pylib/lastfm.py` owns credentials/network semantics and
  `pylib/trackmatch.py` owns song normalization. Network calls stay off the GUI
  thread. A remote love failure must not undo a local favourite.
- Last.fm import only adds favourites, takes maximum play counts, advances
  last-played, and leaves ratings unchanged. One recording's remote count goes
  to the most-played local copy, not every duplicate. Do not bulk-push local
  favourites as an implicit part of pulling stats.

Shutdown pauses mpv and cancels pending playlist fills before any scanner,
metadata, or preference cleanup. Preserve queue/index/position for resume.

## Lyrics, gain, and web metadata

Lyrics resolve timestamped-first: embedded synced, sidecar LRC, then strict
LRCLIB matching. Plain embedded text does not end the search. Preserve separate
`instrumental`, user-marked instrumental (undoable), and retryable `none`
verdicts; never infer instrumental from a title or genre. Do not add a loose
search fallback to a feature that writes audio files.

mpv applies ReplayGain independently of the volume slider. Scan all supported
tag families, matching MP4 freeform names case-insensitively. Untagged tracks
use the library median. `tools/replaygain.py` computes with rsgain then writes
through atomicsave; retain unsupported-format handling and automatic-failure
memory to avoid retry loops.

Release details and credits precede related music and optional prose. Embedded
MusicBrainz release/recording identifiers are read during scans and lazily on
the metadata worker for existing tracks; never force a full rescan to add them.
Release search must corroborate album tracks and preserve ambiguous candidates.
Recording IDs and multidisc positions are constraints, not title hints. Never
choose the first release attached to a recording.

`albuminfo.py` owns a single worker and generation-checked GUI delivery. Network
requests must occur outside SQLite transactions. Drain accepted corrections on
shutdown without waiting for network requests. Cache downloaded releases by
entity ID in `music_info_cache`, with album-directory scopes in
`music_info_links`; `music_info_user` stores independent timestamped corrections
and revert tombstones. `tools/dbsync.py` merges these across top/book. Cache
clearing and transient failures preserve choices and edits. Failed and partial
lookups retry after a short backoff while retaining usable cached details.
Legacy web tables remain readable during migration; old recording choices stay
track-scoped. No web correction writes an audio tag.

The artist resolves independently of the release, so an unidentified,
unofficial or 503'd release still shows who made it. Prefer tagged artist IDs;
a name search must come back as that same name at full score, because a
biography under the wrong person reads exactly like the right one. A
compilation credit is not a person (`NOT_A_PERSON`). Artist entities are cached
by MBID and shared by every album that credits them, with the biography in its
own cache entry — a linked Wikipedia article first, an identity-checked Last.fm
biography second. Clearing an album's cache clears its artist too.

Related ranking computes the current track's active credits and labels once,
not once per library candidate. Related music remains available when release lookup fails. Rank local tracks
using recording/artist identity, scoped credits, labels, and genre; a shared
year alone is insufficient. Track credits require matching disc/position/title;
credits from another edition must not leak through a release-group match.
Keep owned tracks playable and outside Last.fm discoveries as source links.
Publish cached facts before tag reads, indexing, and network requests. Fetch
linked Wikipedia/Wikidata prose after publishing release details and
recommendations, then fall back to identity-checked Last.fm album wikis and
MusicBrainz-linked Bandcamp album descriptions. Keep source URLs and plain
text; artist biographies and shop-only links are not album descriptions.
Empty prose retries daily, failures after five minutes; version the prose
cache when expanding providers so old misses do not suppress new lookups.
`tools/library-ipc.py info` exposes effective cached
facts, choices and provenance without triggering downloads.

## QML and desktop integration

`Root.qml.tbButtons` supplies both hyprvtb chrome and Plasma menus/toolbars.
`Titlebar.buttonsChanged` must fire for state changes even when the vtb socket
is absent. Plasma actions own shortcuts; duplicate QML shortcuts stand down,
and bare-key actions suspend while typing. Root's search field remains the
single search state mirrored to the native toolbar field.

Plasma uses a real `QMainWindow` with opaque `QQuickWidget`, native menus and
transport toolbar; player disables the status bar. Scan/mount text appears only
while nonempty. Shared kdeshell owns shell mechanics. Own the file selector for
its engine lifetime. Selected controls retain their sibling API; controlled
slider values need a `Binding`. `transport.py` keeps pending/drag seeks separate
from reported position and banks sub-detent wheel motion.

The Hyprland art layout chooses its breakpoint from window geometry, never a
fraction being dragged. Plasma selects its own `NowPlaying.qml` with persisted
art/info and upper/queue splits. Preserve the continuous style-owned background
through overlays. The visualizer consumes the existing producer: the short
`player-view.json` lease suppresses duplicate titlebar/panel display and expires
if player dies. Never start a second analyzer.

Favourite hearts are compact flat silhouettes: theme accent fill only when
favourited, otherwise an outline. `HeartIcon.qml` owns QML geometry;
`kdeshell_icons.py` renders the matching player-heart icons for native actions.
Keep click targets unchanged when changing the drawing size.

A track row names only the artists a listing does not already say: the open
album section suppresses the album's own credit (`TrackList.hideArtist`) and a
mixed listing suppresses its majority one (`autoHideArtist`), so what survives
beside a title is the guest. That credit is a different datum from the title,
not a quieter one, and takes `fgGuest` — a wash of the accent over the dim
tone, never the accent itself.

Release facts in `NowInfoPane.qml` are detached from QVariant maps once per
album change; status/related updates must preserve credit delegates. Instantiate
credit rows only for the selected album tab and matching scope. Metadata-only
album track listings must never stat files or prune the library.

Use shared Kinetic views, Motion, and VScroll per the parent guide. Foreground
and artwork tones are derived at the root and passed down; app-side inactive
fading is retired because the compositor owns dimming. Do not resurrect one
half or reinterpret menu disabled colors as focus state.

## Temporary performance logging

`perftrace.py` starts only in normal app launches and writes
`$XDG_STATE_HOME/player/performance.jsonl` (default `~/.local/state/player/`).
It retains a 2 MiB log and three rotated copies. `PLAYER_PERF_LOG=0` disables it.
A 50 ms GUI heartbeat records gaps over 250 ms; a background watchdog captures
Python stacks during stalls at most once a second. Timed queue/metadata work
logs durations over 25 ms, with queue size/index and 10-second CPU samples.
The monitor stays running through shutdown cleanup and closes after the event
loop returns. No file writes happen on the GUI thread. Stack records omit locals and source
text. Python stacks can identify a blocking native call but cannot unwind its
C++/QML internals; a GIL-holding call may delay the watchdog too.

## Focused verification

Use the safety protocol in the parent/root guides: guarded offscreen or nested
execution, isolated XDG state/runtime paths, fake mpv, no live player socket,
MPRIS, scans, tag writes, audio, or preference saves. Read a harness before
running it; never source the player wrapper to obtain its interpreter.
`main.py --selftest` is the app-construction probe, not permission to use live
state. `tools/resource-fixture.py` supplies scratch metadata and a no-audio stub
for resource sampling. The user performs real visual/interaction checks.

Choose relevant harnesses under `tools/`; these are local regression probes,
not a CI suite:

| Change | Harnesses |
| --- | --- |
| Scan/availability | `scanner-safety-test.py`, `scanner-lock-test.py`, `prune-missing-test.py`, `watch-remote-test.py` |
| Tag writes/import/gain | `atomic-write-test.py`, `tagtool-test.py`, `player-add-test.py`, `replaygain-test.py` |
| Smart lists/search/Last.fm | `smartlist-test.py`, `smartlist-ui-test.py`, `lastfm-test.py`, `search-page-test.py`, `search-ui-test.py` |
| Queue/path/socket | `queue-ops-test.py`, `album-playnext-test.py`, `open-path-test.py`, `queue-lyrics-test.py` |
| Preference/metadata persistence | `state-write-test.py`, `metadata-worker-test.py` |
| Metadata/sync | `now-info-test.py`, `artist-info-test.py`, `album-prose-test.py`, `release-info-test.py`, `related-music-test.py`, `info-sync-test.py`, `info-connection-test.py`, `library-ipc-test.py`, `test-dbsync.py` |
| Album information UI | `album-info-ui-test.py`, `album-guest-ui-test.py` |
| Native/QML presentation | `plasma-chrome-test.py`, `transport-test.py`, `focus-fade-test.py`, `view-preserve-test.py`, `favourite-surfaces-test.py`, `trash-track-test.py` |

Atomic-write probes operate on copies and hash decoded audio only
(`ffmpeg -map 0:a -f s16le`), because cover-art streams can make whole-file
conversion hashes misleading. Never point write-capable probes at the library.

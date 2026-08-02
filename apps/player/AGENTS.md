# `player` — music player

Vendored source of the standalone Qt/QML music player (`main.py`, `qml/`).
Built/installed by `home/prog/player.nix` (mirrors `viewer.nix`); runs the
**live** source, so `.py`/`.qml` edits need no rebuild — relaunch the app. See
[`../AGENTS.md`](../AGENTS.md) for the shared live-source/pylib/vtb rules.

Tag-driven library (background mutagen scan of `/run/media/lam/SSD/aud` →
`~/.local/share/player/library.db`, art thumbs in `~/.cache/player/art/`),
libmpv playback (python-mpv), MPRIS via `mpris-server` (the panel's MediaPanel
controls it), FMPS rating/playcount/favourite tag writeback (journaled to
`~/.local/state/player/tagwrites.log`, gated by prefs `tagWrites: off|log|on`,
ships in `log`), synced lyrics, ReplayGain volume levelling.

## Every write to a library file goes through `atomicsave.py`

**There are exactly two paths that modify a file in `aud/`** — `TagWriter`
(FMPS rating / FAVORITE / playcount) and `lyrics.write_embedded` (USLT /
`LYRICS` / `©lyr`, also used by `tools/lyrics-sync.py`) — and **both** now end
in `atomicsave.atomic_save(path, mutate)`: copy beside the original, mutate the
copy, `fsync`, `os.replace()`. Never add a third `mutagen.save()`.

Both used to save in place, which for a tag block that outgrows its padding
shifts the audio data itself; an interruption there leaves a truncated file on
exFAT, with no snapshots anywhere on this machine to undo it. The lyrics path
was the live one — it defaults on and had already written to the library.

The module's docstring carries the reasoning; the four rules it is easy to
undo are: the temp file must be **in the target's own directory** (elsewhere,
`os.replace` is not a rename), it must **keep the original extension**
(`mutagen.File()` scores partly on the filename — a `.tmp` copy of a `.dsf`
sniffs wrong), **mtime is preserved** (the scan caches on (mtime, size) and
dbsync ships the DB to book on mtime passing through SMB byte-exact; both write
paths update the DB row themselves, so no rescan has anything to rediscover —
size still changes, so a genuine re-read still happens), and free space is
checked against the **target's own filesystem** before the copy, failing with
`NoSpace` and a journal line rather than filling the disk. The old "in-place, no
free-space cost" rationale was written against a 95%-full SSD; it is 932G with
662G free (2026-07-28).

`TagWriter` **coalesces**, because a copy is far heavier than an in-place save:
a popped entry waits `COALESCE_S` (1.5s) and then absorbs every other queued
entry for the same path, last value winning per field. Five stars clicked in a
row are one rewrite of the FLAC.

```bash
tools/atomic-write-test.py --samples DIR [--exfat-probe DIR]
```

Runs on COPIES only and refuses to run inside `aud/`. Per format
(mp3/flac/m4a/dsf/wav) it hashes the **audio stream alone**
(`ffmpeg -map 0:a -f s16le - | md5sum` — never plain `-f md5 -`, which is
nondeterministic with cover art), round-trips the tags, and checks mtime and
temp-file hygiene; then every failure path (no space, missing file, unreadable
audio, read-only directory, a `mutate()` that raises) for "original intact, no
litter"; then hammers `os.replace()` with a concurrent reader to show it is a
real rename on **exFAT** too. 53/53 on the SSD, 2026-07-28.

**`tagWrites` cannot be changed while the app is running** — `Prefs` holds the
whole file in memory and rewrites all of it on any `set()` (volume, sort,
album-grid scroll, quit), and reads prefs only at startup. `tools/set-pref.py`
sets a key from outside, backs the file up, and refuses while `main.py` is up.

**ALL chrome is hyprvtb titlebar buttons** — transport + view switcher + sort +
the `fs` search toggle (`Ctrl+F`; it was labelled `/`, a key nothing was ever
bound to — docs/DESIGN.md §11.2, §12.1) + a bottom-anchored settings button
whose drawer (surfer's `dm`-panel idiom) holds rescan and the album gallery's live column count — plus
the `PLAYBAR`/`SEEK` scrub bar. The pushed playbar fraction is floored at 0.002
because plugin builds ≤2.44 abort the compositor on a zero-height fill rect
(fixed plugin-side in v2.45 — guard every computed rect when adding hyprvtb
drawing).

**The now-playing cover art is RESPONSIVE, and the narrow window is the
reference.** `NowPlaying.qml`'s art is a full-width top row in the ~480x826
window this page normally lives in, and a full-height LEFT COLUMN once the
window is wide (`sideArt`) — because a top row scales a square cover to the
window's *width*, so maximized it kept a 1406x472 band, 30% of the art. Both
branches bleed to the window outline; neither letterboxes (docs/DESIGN.md §5.1).
Two constraints when touching it: the switch reads **window geometry only**,
never `artFrac` (a layout that flipped mid-drag would rearrange the page under
the cursor), and it must be a **strict no-op below the breakpoint** — verified
by rendering both branches offscreen and comparing PNGs byte-for-byte across
sizes, `artFrac` values and with/without lyrics, which is the harness pattern to
reuse for any further change here.

**Track list, album grid and both lyrics panes are `Kinetic*` views from `../qmlcommon/`** — player's scrolling policy is the scrollbar and the wheel only, never drag-flicking, so the compositor's momentum is the only momentum. `WheelScroll.qml` used to live in `player/qml/`; it is shared now and player is no longer its owner. `TrackList` passes `wheelEnabled: root.scrollable` so a table sized to hold every row (AlbumPanel) hands the wheel out to the gallery behind it. See [`../AGENTS.md`](../AGENTS.md).

## Focus: three tones, derived once, handed down (`docs/DESIGN.md` §3.1.1)

**No file under `qml/` may read `Theme.text`, `Theme.textDim` or `Theme.accent`
for a thing it draws, and none may read `Window.active`.** `Main.qml` derives

```qml
readonly property color fgText:   win.active ? Theme.text    : Theme.inactive
readonly property color fgDim:    win.active ? Theme.textDim : Theme.inactive
readonly property color fgAccent: win.active ? Theme.accent  : Theme.inactive
```

and every pane, list, drawer and leaf takes those three as plain `color`
properties (defaulting to the lit tones, so a harness can build one alone).
`Theme.inactive` is the exact grey hyprvtb fades the titlebar to; player was the
**third** app to grey its chrome and leave its content lit, after painter and
reader, which is why §3.1.1 exists and why this is tested.

**The artwork fades with them**, through a fourth derived value on the same
chain — `readonly property real fgArt: win.active ? 1.0 : 0.55`, wired
`Main` → `AlbumGrid` → `AlbumPanel` and `Main` → `NowPlaying`. **All three
covers**: the gallery thumbnails, the album section's art and the now-playing
full-bleed cover. This REVERSES the first implementation, which left the art lit
by analogy with filer's `PreviewTile`; **his call, 2026-07-28** — *"dim it with
everything else — the window reads as one unfocused surface"*. Do not restore
the old reading, in code or in `docs/DESIGN.md` §3.1.1.

The mechanism is plain `opacity` on the existing `Image`, i.e. compositing the
cover toward the `Theme.bgAlt` fill every artBox already draws behind it — no
shader, no `Qt5Compat` effect and no extra item in a gallery of tiles (verified:
the item count of the whole window is unchanged at 406, and load+first-frame CPU
time is indistinguishable). A grey scrim in `Theme.inactive` was the obvious
alternative and is wrong for the same reason `Theme.dim` is exempt below: the
grey is lighter than a dark sleeve, so it would BRIGHTEN half the library.
**0.55 is measured**: over 200 real thumbnails from `~/.cache/player/art`
composited on the live palette's `bgAlt` it moves the mean cover 18.5 L\* (median
18.3), against `fgDim`'s 22.5 L\* and `fgText`/`fgAccent`'s 47.3 L\* — just under
the weaker text move, because a cover is a large field where a step reads
stronger than in glyph-sized text, and matching 47 would take the average sleeve
to near-black and read as broken rather than quiet.

Deliberately NOT faded, and each for a reason:

- **`Theme.dim`** — the tertiary tone (the `♫` art placeholder, an unrated star,
  a play count, the search placeholder). It sits *below* the inactive grey, so
  mapping it there would BRIGHTEN it on focus loss.
- **`Theme.crit`** — the favourite heart is a status colour, per `PreviewTile`'s
  error tone.
- **`Theme.border` / `Theme.bgAlt` / `Theme.highlight` / `Theme.bg`** — §3.1.1
  moves foregrounds only. The row-highlight fill in particular must not move, or
  the window reads as broken rather than unfocused.
- **`CtxMenu` / `TrackMenu`** — `CtxMenu.qml` is byte-identical to filer's, and
  inside it `Theme.inactive` already means *disabled*: fade the whole menu and a
  greyed-out entry becomes indistinguishable from a live one. A menu is also
  only ever open on a focused window. Changing it is a seven-app decision, not
  player's.
- **`Theme.windowBorder`** on the settings drawer — nine call sites across five
  apps draw an overlay frame with it and none of them switch to the
  `windowBorderInactive` that `Theme` already defines. Worth doing, but
  desktop-wide and in one pass.

```bash
tools/focus-fade-test.py [--png DIR]   # offscreen, never touches the live player
```

Three layers: the derivation (real `Window.active`, driven by activating a
second offscreen window — no faked flag); the propagation (every visible item in
every view is asked what colour it *ended up* with, which is the layer both
earlier occurrences of the bug lived in); and the pixels (480x826 — the size
player actually runs at — histogrammed focused vs unfocused, with a fake palette
that gives every theme slot a unique hue so a count is unambiguous). The
propagation layer also asks every visible `Image` whether it took `fgArt` (an
`AlbumPanel` whose relay through `AlbumGrid` is missing dims the gallery and
leaves the open album section lit), and the pixel layer asserts the art
**differs** between the frames — gone at the lit RGB, and back at the exact tone
`fgArt` over `bgAlt` predicts, in the same pixel count, so a cover that had been
blanked fails as loudly as one left lit. 39/39, 2026-07-28. Two traps
that harness paid for: `highlight` must not be a grey, because `Theme.inactive`
over `bg` composites to exactly `#404040`; and Qt caches a directory's file
listing on first load, so a scratch `.qml` written afterwards fails with "File
name case mismatch".

## Right-click: one menu for every listing (`qml/TrackMenu.qml`)

player draws a track in five places — the queue, an album's inline section, a
smart playlist, the search results and the now-playing header — and every one of
them opens the **same** `TrackMenu`. The look and the ordering rule are
`docs/DESIGN.md` §7.2 (which also carries the vocabulary and why each entry
greys out when it does); this section is the mechanics.

- **Four of the five come free from `TrackList`**, which owns the menu and the
  right-click handler. A new listing gets one by existing.
- **The menu is parented to `Window.contentItem`, not to the list.** `CtxMenu`
  measures and clamps against its own bounds, and the queue is a ~240px column
  in a 480px window — owned by the list, the menu would be clamped to a sliver
  of the window or cut off at the list's edge. The right-click `MouseArea` is
  declared **last** in the delegate (so it covers the right-hand rating column
  that `rowMouse` deliberately stops short of) and accepts **only**
  `Qt.RightButton`, so every left click still falls through to the stars, the
  heart and `rowMouse` underneath it.
- **`TrackList` never navigates.** "go to album" / "search for artist" are
  relayed out as `openAlbumRequested` / `browseArtistRequested` and the window
  decides — the same reason `NowPlaying` already had those two signals. The
  relay chain for the album section runs `AlbumPanel` → `AlbumGrid` → `Main`.
- **The site supplies the two facts only it knows**: `inAlbum` (this listing IS
  that album, so "go to album" is absent rather than a no-op) and `isQueue`
  (rows are queue rows, so they can be removed).
- **No multi-select anywhere in this app**, so the menu acts on the row under
  the cursor. The Player slots all take a LIST of ids/indices, so a selection
  model would not need them changed.

Queue mutation lives in `Player.queueTracks` / `playNext` / `removeFromQueue`
(`queueAlbum` is now just `queueTracks` over an album's ids). Two traps they
exist to respect: `_orig_queue` — the pre-shuffle order — has to be mutated
alongside `_queue`, or anything added while shuffled vanishes the moment shuffle
is turned off; and a removal that does **not** touch the playing row must shift
`_index` arithmetically rather than through `_set_index`, which would also zero
the position readout and the play-count accumulator of a track that never
stopped.

```bash
tools/queue-ops-test.py   # headless; a Player built without __init__ (so no
                          # libmpv, no audio device) driven against a fake mpv
                          # playlist. The LIVE player is never touched.
```

## Opening a file by path (`%F`)

`player /path/to/track.flac` plays that track, and so does double-clicking one
in filer — `home/prog/player.nix` writes `Exec=…/bin/player %F` and player is
now the registered default for **all fourteen** extensions in `AUDIO_EXTS`.
Until 2026-07-29 it was the default for nine and dropped the argument on the
floor; `home/prog/mime-defaults.nix` and `docs/agents/mime-defaults-audit.md`
carry the reason the other five were withheld, which was exactly this defect.

Three pieces, each with a rule:

- **`paths_from_argv`** takes plain paths and `file://` URIs, skips anything
  starting with `-` (QGuiApplication owns the option namespace), and filters on
  `AUDIO_EXTS`. Honouring a `.pdf` dropped on the icon would be the app acting
  on a type it never registered.
- **`Library.ids_for_paths`** resolves a path inside the library to its **real
  row**, so a double-clicked track behaves exactly like the same track clicked
  in the queue — rating, play count, lyrics and its album all key on the id
  because it *is* that id. A path the library has never scanned gets a
  **transient row under a NEGATIVE id**, held in memory only and returned by
  `tracks_by_ids` alongside the DB rows. That is what lets a download outside
  `aud/` play at all, and the sign is load-bearing: every write path
  (`setRating`, `setFavorite`, `bump_playcount`, `LyricsProvider._resolve_one`)
  is `… WHERE id=?` followed by a guard on having found a row, so all of them
  miss and **nothing is ever written to a file this library does not own**.
  `save_state` stores the id and the next launch's `tracks_by_ids` cannot
  resolve it, so a one-off file does not come back — which is the wanted
  behaviour, not a leak.
- **The queue socket's `OPEN` verb** is the singleton. A second launch calls
  `handoff_paths`, which connects to `$XDG_RUNTIME_DIR/player-queue.sock` with
  a plain stdlib socket (before Qt starts — the whole point is not to start it),
  sends the percent-encoded paths and exits when the server answers. Two players
  must never run at once: they would fight over the MPRIS name, the socket and
  the audio device, and both would be audible. The module's docstring used to
  claim a *library lock* prevented that; there is no such lock — sqlite's WAL
  lets a second writer in after a 60s wait — so before this a second launch
  really did start a second player.

Opening REPLACES the queue (what every player does with a file handed to it
from a file manager), and an open whose arguments were all unreadable is a
no-op rather than a stop. With paths on the command line, `restore_state` is
called with `resume=False`: it brings back the session's shuffle/loop and queue
but does not re-sync mpv or post the delayed position seek, which would land
300 ms later on the queue that has since been replaced.

```bash
QT_QPA_PLATFORM=offscreen python3 apps/player/tools/open-path-test.py
```

Headless, on a scratch DB under an isolated `XDG_DATA_HOME`/`XDG_RUNTIME_DIR`;
the live player's socket, database and audio device are never touched. It covers
all three pieces, including a filename with a space and a `%` in it (the reason
`OPEN` is encoded at all — the protocol splits on whitespace) and the proof that
writing to a transient id creates no DB row. 37/37, 2026-07-29.

**Known gap:** a handoff cannot raise the running window — hyprvtb has no
"activate this window" verb the app can reach, and MPRIS `Raise` is declared
unsupported here. Double-clicking a track while player is minimized starts it
playing without bringing it forward.

## The queue socket (`start_queue_server`)

The desktop panel's media widget draws a queue drawer, and MPRIS cannot carry
it — the TrackList interface is optional and the panel's Quickshell has no
client for it. So the app serves its own queue on
`$XDG_RUNTIME_DIR/player-queue.sock`, one line at a time:

```
server -> client   {"index": n, "tracks":[{"title","artist","dur"}, ...],
                    "lyrics": {"source","synced","lines":[{t,line}],"text"} | null}
                   on connect, and on queueChanged / indexChanged / currentChanged
client -> server   GOTO <index>        -> player.jumpTo(index)
                   LYRICS <0|1>        -> subscribe this connection to lyrics
```

- **Push, not poll**: the panel is animating this, and a file it had to re-read
  on a timer would be both later and more work.
- Only the three fields the drawer draws are sent. The panel has no library and
  no art cache; anything else would be bytes per queue change for nothing.
- A stale socket from a crash is removed before `listen()` — two players never
  run at once (the second dies on the library lock long before this).
- **Every failure is caught and printed.** A queue drawer is a convenience and
  must never be able to take the music player down; the same rule `start_mpris`
  already follows.

### `LYRICS` is a subscription, and that is the whole design

The panel's queue drawer now grows a lyrics box on the right when the playing
track has words (`docs/DESIGN.md` §5.4), and this socket is the only channel there
is: MPRIS has no lyrics field, and `LyricsProvider` lives in this process.

- **Opt-in, per connection.** Resolving is not free — tag reads, an LRCLIB
  request, and (with `lyricsEmbed` on, the default) a writeback into the file.
  Doing it for every track the user plays merely because the panel exists would
  turn a widget nobody has opened into a library-wide sweep, which is what
  `tools/lyrics-sync.py` is for. So nothing is resolved until a client says
  `LYRICS 1`, and the panel only says it while its drawer is actually open.
- **The payload is per CONNECTION, because the subscription is.** `snapshot()`
  takes a `with_lyrics` flag and `push()` builds at most two lines. It read the
  `want` set as a global "is anybody listening" first, so one subscriber turned
  lyrics on for every other client — including a panel predating this protocol,
  handed a few KB of words it has no field for on every push.
- **`lyr_tid` is a join key, not a cache tag.** A resolve is asynchronous, so by
  the time one lands the user may have skipped — and a payload sent under the
  wrong track is the panel confidently scrolling another song's words. Nothing
  is ever emitted unless the cached id still equals what is playing, and a
  track change clears the payload *before* the push that announces it.
- **Whole lines, once per track; the panel does the following.** It has the
  MPRIS position already, so pushing a current-line index would only add socket
  latency to something the other side can compute exactly.
- **`none` / `instrumental` are sent as a payload with no words in it**, which
  is how the panel knows to collapse the column rather than draw an empty box.
  It has no "mark instrumental" control — that needs the library.

```bash
tools/queue-lyrics-test.py     # headless; isolated XDG_RUNTIME_DIR, fake
                               # Player + LyricsProvider, so the LIVE player's
                               # socket is never touched.
```

## Lyrics + ReplayGain (2026-07-25)

`lyrics.py` is a Qt-free module shared by the app and `tools/lyrics-sync.py`:
LRC parse, embedded read/write (LRC text in USLT / `LYRICS` / `©lyr` — *not* ID3
`SYLT`, which nothing reads), and a strict LRCLIB client. Resolution is
**timestamped-first**: embedded synced → sidecar `.lrc` → LRCLIB, and a plain
unsynced tag never ends the search (≈18% of this library has plain words sitting
in its tags, which used to block the lookup permanently). Fetched synced lyrics
are **written back into the file** (pref `lyricsEmbed`, default on; journaled to
`tagwrites.log`).

Two rules learned the hard way here:

1. **Matching must be STRICT because this writes to files.** NetEase's search
   always returns a top hit and was observed matching "Wu-Lu — Run Away Dream"
   to an unrelated Chinese pop song, so it is deliberately NOT used as a
   fallback.
2. **There are THREE negative verdicts, not one**, because "this track has no
   words" and "nobody has indexed them" are different claims and only the first
   is knowable: `instrumental` (LRCLIB's flag — permanent, pane collapses),
   `instrumental-user` (marked by hand from the pane — permanent and undoable),
   and `none` (undetermined — retried on a widening backoff, 7/14/28…180d, via
   `lyrics.attempts`).

**Do not try to infer instrumental from titles or genre**: an audit found only
163 of 11k titles carry any marker, catching 11 of the first 770 misses, and
`Intro`/`Interlude`/`skit` often *do* have lyrics. The miss pile really is mixed
— wordless ambient sits next to vocal tracks too obscure to index (Coaltar of
the Deepers, Astrid Sonne) — so the only thing that could settle the rest is
analysing the audio for singing, which is deliberately NOT built. Title/artist
normalisation (`(Monopoly mix)`, `(ft. X)`, `prod. Y`) lifted the sample hit
rate 42%→60%.

`tools/lyrics-sync.py` sweeps the library: dry run by default, `--write` to
embed, `--embed-cached` to do the file writes with no network. The split exists
because looking up 11k tracks is harmless while music plays, whereas rewriting
tags under the running player is not — the tool refuses `--write` if `main.py`
is up.

**ReplayGain**: the scan mirrors `REPLAYGAIN_*`/`R128_*` (all three tag
families; MP4 freeform names must be matched case-insensitively — some files say
`com.apple.itunes`) into `tracks.rg_*` columns, and **mpv applies the gain
itself** (`replaygain`/`-preamp`/`-fallback`/`-clip`), independent of the volume
slider — verified empirically at −6.3 dB measured vs −6.32 dB tagged. ~93.5% of
the library is already tagged; untagged files use the library's **median** gain
rather than a made-up constant.

The untagged remainder is filled in by `tools/replaygain.py`: it runs the
packaged `rsgain` (an EBU-R128 / ReplayGain 2.0 scanner, on PATH) in scan-only
mode to *compute* each track's gain+peak, then **writes the tags itself through
`atomicsave`** — copy-then-replace, never in place, the same path every other
write into aud/ takes, so a run that dies halfway cannot leave a truncated file
on exFAT. Dry run is the default; `--write` applies. It writes both track and
album gain (album-grouped by directory, so album-mode playback keeps an album's
intended contrast). Formats `rsgain` cannot tag — DSF/DMF/MPC/TTA, listed once
as `RG_UNSUPPORTED_EXTS` in main.py — are skipped and stay on the median
fallback. `AutoScanner` runs it as a child after every rescan
(`scan --write --auto`; idempotent, failures remembered in
`~/.local/state/player/replaygain-auto.json`), so **any track that lands in the
library — a Soulseek download via player-add.py or a file dropped straight into
aud/ — is normalized automatically**, no manual step. Harness:
`tools/replaygain-test.py` (28 checks, offscreen, on scratch copies; the live
library and running player are never touched).

NB when integrity-checking tag writes: `ffmpeg -i f -f md5 -` is
**nondeterministic** on files with embedded cover art — hash audio only
(`-map 0:a -f s16le - | md5sum`).

## Sharing the library with `air` (2026-07-25)

`air` has ~12 GB free and the library is 208 GB, so it is never copied —
`sys/net/share.nix` serves `/run/media/lam/SSD/aud` over SMB (samba, not NFS:
exFAT has no `export_operations` for nfsd) plus avahi (`top.local`) and
keys-only sshd, every port scoped to `enp12s0`; `sys/disks.nix` declares the SSD
so it is up before a session is. Off-LAN, `sys/net/tailscale.nix` joins top to a
tailnet — samba's hosts-allow includes the CGNAT range and `--operator=lam` lets
agents drive it without sudo. **`tailscale0` is deliberately NOT a trusted
interface**: exactly two ports are opened on it, and the header comment in
`sys/net/tailscale.nix` says which and why (an earlier `trustedInterfaces` entry
published every listener on the box). Do not restate the port list here — read
it there, and treat adding to it as a security decision. Book's daemon is
dnf-installed Fedora state, not managed here. `air-launch.sh` probes
`top.local` first, then the MagicDNS name `top`, so the player's metadata sync
follows book onto any network.

**The one invariant everything rests on: `air` mounts the share at the SAME
absolute path**, which makes `top`'s database valid there verbatim — no path
rewriting, no rescan (measured: mtime passes through exFAT-over-SMB3 byte-exact
for all 11 099 tracks).

Metadata is reconciled by `tools/dbsync.py` (`pull`/`push`/`sync`/`status`),
keyed on `tracks.path` and never on `id`, stdlib-only so it runs under Fedora's
python, and its own remote agent — it pipes ITSELF to `python3 -` over ssh. It
never deletes, and a first pull **seeds** rather than merges (a locally-scanned
db renumbers the rowids that `prefs.json`'s saved queue is made of). Two traps:
snapshot with sqlite's `backup`, never `cp` (WAL); and `MIGRATIONS` entries are
`(table, col, decl, rescan)` — adding a `tracks` column with `rescan=True`
clears the mtime cache and forces an 11k-file re-read, which over SMB is brutal,
so a column the APP writes (`meta_mtime`) must set it False.

Full plan, runbook and STATUS: `docs/agents/air-library-share.md` — **both parts
are done and verified** (Part B on `book`, 2026-07-26). That doc's STATUS block
is authoritative; this paragraph is not.

## Spotify export → what's missing locally (2026-07-25)

`tools/spotify-dump.py` exports the account's Spotify library (Authorization
Code + **PKCE**, so no client secret exists to leak; token cached 0600 in
`~/.local/state/spotify-dump/`, client id kept out of this public tree) and
`tools/spotify-missing.py` diffs it against `library.db` into
matched/suspect/**missing** TSVs — the last being the work list for finding
copies elsewhere. Both stdlib-only, same reason as `dbsync.py`.

**Saved albums expand into the work list.** The dump writes each saved album's
tracks into `saved_albums[].tracks`, and `spotify-missing.py` folds them into
the missing list alongside saved/liked and playlist tracks — so saving an album
counts as wanting its missing tracks downloaded. The expansion lives in the
dump, so **`tools/spotify-dump.py` must be re-run to regenerate the dump** (and
then `spotify-missing.py`) for the album tracks to reach `missing.tsv`; the
album-origin rows appear under the album name in the `sources` column.

`tools/soulseek-missing.py` acts on that work list: for each `missing.tsv` row
still **not** in the live `library.db`, it submits one slskd search over the
loopback HTTP API (key from `~/.secrets/slskd-api-key`, pinned in
`home/prog/slskd.nix`), matches a peer's offered file by the same
`trackmatch` artist/title folding + a duration check, and queues the download.
Stdlib-only, so it needs no runtime dependency and runs on both hosts; it keeps
a per-dump-dir `soulseek-state.tsv` so re-runs never re-search or re-download
what is already handled, and `--dry-run` shows picks without enqueueing. It
requires slskd to be **running and logged in** — which the generated
`slskd.yml` alone does not provide (see `home/prog/slskd.nix`).

**Each run fans the batch out across distinct peers.** slskd serializes
downloads from one peer over a single connection (the Soulseek protocol grants
one upload slot per user), so a run that piled every match onto the same peer —
common when an album/single-artist set lives on one user's share — lined them
all up behind that one slot and read as "only one transfer at a time" however
high `global.download.slots` was. `pick_candidate` therefore de-prioritizes a
peer a run has already enqueued `MAX_ENQUEUES_PER_PEER` (2) files to, and
prefers a peer advertising a free upload slot on the tiebreak. Both biases
break ties only — a file offered solely by an already-loaded/busy peer is still
enqueued there rather than refused.

Each run also **re-sources downloads that ended failed** — slskd's
`Completed, Rejected` (and `Cancelled`/`TimedOut`/`Errored`/`Aborted`) states,
where a peer accepted the request then refused the transfer, so the track
never lands in the library yet the state file keeps it `queued`. It reads
`/transfers/downloads`, matches each failed transfer back to its missing track
(by the same artist/title folding the search uses), drops that track's
`queued` marker so the normal pass re-searches it, and blocks the refusing
peer from the pick so the re-source lands on a different source. Each failed
transfer's id is remembered in a per-dump-dir `soulseek-rescued.json` — only
once a matching queued track was actually re-sourced — so a rejection lingering
in slskd's list is only ever acted on when there is something to do (not on
every poll, and never while the track is in a nofind/error state that would
leave the id burned with nothing re-sourced). Transfers that ended in a failed
terminal state are also excluded from the never-re-queue guard, so a re-sourced
track is not re-marked "queued" pointing at the dead transfer; they only guard
the re-queue while they might still produce a file. This is also what actually
populates the never-re-queue guard: the `/transfers/downloads` response nests
as username → directories → files, and the guard was previously walking only
the top level and matching nothing.

**Every errored/failed download is then cleared from slskd itself.** slskd keeps
completed/failed transfers until explicitly removed, so a re-sourced track left
a dead errored row accumulating in the downloads view forever. `clear_handled_failures()`
DELETE-cleans **every** failed-terminal transfer from `/transfers/downloads` —
pure cleanup of a row that can never produce a file: the re-source (not the
lingering row) is what recovers the track. It runs after the rescue pass, so the
same run has already seen the failures it needed to re-source before removing
the rows. Two traps, both paid for: slskd's `DELETE downloads/{username}/{id}`
only removes the row from the store (which the webapp reads) when
`?remove=true` is passed — a bare DELETE merely "cancels" an already-failed
transfer (a no-op) and the row stays visible; and clearing must not be gated on
`soulseek-rescued.json`, or a failure whose track is nofind/error (never
queued, so never rescued) accumulates in the downloads view forever.

slskd drops completed downloads into `~/.local/share/slskd/downloads/`, and the
player only ever sees a track once it is moved into `aud/` and rescanned. The
pipeline's last step (`tools/player-add.py`, run automatically by
soulseek-missing.py unless `--no-import`) closes that gap: it moves each
completed download into `aud/<Artist>/<Album>/` following the library's folder
convention, fills missing tags from the same `missing.tsv` (a Soulseek file can
arrive bare — the 0181 mp3 had no artist/title), and does an incremental
rescan of `library.db`. Because the scan is tag-driven, the DB row comes from
the file's own tags; a file whose tags arrive empty is only metadata-correct
once the importer tags it from the pipeline's own record of what was queued.
`player-add.py` runs under the **player's** python env (it reuses
`main.py`'s `read_tags`/`open_db`/`rebuild_albums`), which soulseek-missing.py
resolves from the `player` wrapper; it writes the DB out-of-process in WAL
(busy-timeout 60s) like `tools/dbsync.py`, and never touches the running
player's session.

**Automatic pickup (`main.py`'s `AutoScanner`).** Both feeds into the library
are watched by the app now, so a freshly downloaded track reaches "recently
added" with no manual Rescan:

- the **downloads dir** — on change (debounced 3s) the app runs `player-add.py`
  as a child of itself (`sys.executable`, the player's python env) to move/tag
  new downloads into `aud/` and rescan, then re-scans in-process so the open
  smart playlist refreshes. A startup pass imports anything already sitting in
  `downloads/`. One import runs at a time; a change while one is in flight is
  debounced and picked up next.
- the **library root** — on change (debounced 2s) a rescan picks up files
  dropped straight into `aud/` (a manual copy, a ripper).

Both converge on `Library.rescan()`, whose `changed` signal re-opens the open
smart playlist — that is what makes the track appear in "recently added"
without the button. `AutoScanner` is inert on `air` (no slskd dir) and wherever
`aud/` is unmounted, and the dirs are re-watched every 30s so a remount or a
first slskd launch is picked up. It never reimplements the move/tag logic — it
runs the tool.

Three things worth knowing before touching them:

1. **`GET /playlists/{id}/tracks` no longer exists** — Spotify's Feb–Mar 2026
   migration replaced it with `/playlists/{id}/items` and renamed each entry's
   `track` key to `item`; the old path 403s unconditionally and `/me/playlists`
   reports `tracks:null`, so there is no fallback.
2. A **Development-mode** app gets playlist *contents* only for playlists the
   user created or collaborates on (14 of 92 here are other people's, metadata
   only), so a per-playlist 403 is normal and must never abort the run.
3. The local db has **no ISRC column**, so the diff cannot use the ISRCs the
   dump collects — matching is normalised artist+title with duration as a signal
   that *flags* (`suspect.tsv`) rather than rejects. Adding `isrc` to the scan
   would mean a `MIGRATIONS` entry with `rescan=True`, i.e. a full 11k-file
   re-read.

## `../pylib/trackmatch.py` owns artist/title normalisation

It was extracted from `lyrics.py`, which imports `mutagen` and therefore cannot
be imported by anything running under a bare `python3`. `lyrics.py` imports it
back under its historical private names (`_fold`, `_title_matches`, …), so
behaviour there is unchanged. **Any new "are these two tag strings the same
song?" code must use this module** rather than grow a second copy — the
decoration stripping is what took the LRCLIB hit rate from 42% to 60%, and a
drifting duplicate would silently regress that.

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

**ALL chrome is hyprvtb titlebar buttons** — transport + view switcher + sort +
search toggle + a bottom-anchored settings button whose drawer (surfer's
`dm`-panel idiom) holds rescan and the album gallery's live column count — plus
the `PLAYBAR`/`SEEK` scrub bar. The pushed playbar fraction is floored at 0.002
because plugin builds ≤2.44 abort the compositor on a zero-height fill rect
(fixed plugin-side in v2.45 — guard every computed rect when adding hyprvtb
drawing).

**Track list, album grid and both lyrics panes are `Kinetic*` views from `../qmlcommon/`** — player's scrolling policy is the scrollbar and the wheel only, never drag-flicking, so the compositor's momentum is the only momentum. `WheelScroll.qml` used to live in `player/qml/`; it is shared now and player is no longer its owner. `TrackList` passes `wheelEnabled: root.scrollable` so a table sized to hold every row (AlbumPanel) hands the wheel out to the gallery behind it. See [`../AGENTS.md`](../AGENTS.md).

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
slider — verified empirically at −6.3 dB measured vs −6.32 dB tagged. ~96% of
the library is already tagged; untagged files use the library's **median** gain
rather than a made-up constant.

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

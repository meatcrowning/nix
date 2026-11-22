# `booru` — booru browser

Search a booru, page through thumbnails, open a post, read its tags by
category, follow a tag (click: search it; middle/Ctrl+click: add it; right
click: exclude, wiki, copy, blacklist), and save or hand the original to
`viewer`. Revived from cte's Danbooru tab (top: `~/Projects/cte/app`). Packaged
by `home/prog/booru.nix`, which runs this live source on both hosts. Read
`../AGENTS.md` first.

| Area | Source | Test |
|---|---|---|
| Site APIs, throttle, disk cache | `booruapi.py` (Qt-free) | `tools/booru-test.py` |
| Threads, image provider, `Booru` | `main.py` | same |
| Window, actions, post view | `qml/Root.qml`, `qml/VideoPane.qml` | same |

## Contracts

- **Every request carries `booruapi.USER_AGENT`.** Danbooru's CDN answers 403
  to Qt's default `Mozilla/5.0`, so images never load through QML's network
  stack: `image://booru/<percent-encoded url>` is `main.ImageProvider`, which
  fetches through `booruapi.cached()` into `~/.cache/booru/` (1 GiB, pruned
  oldest-first at startup). GIF and video play from the cache file
  (`Booru.media`). Full-size requests outrank thumbnails in the pool.
- **Keys live only in `~/.config/booru/<site>.json`** (`login`/`user_id`,
  `api_key`), never in this repo. cte's file hard-coded a Gelbooru key; do not
  copy from it. Gelbooru refuses without one, with the path in the message.
  Danbooru without an account allows 2 tags per search (rating/order metatags
  are free); the error names the file that lifts it.
- **Sites** are `booruapi.SITES`: Danbooru (wiki, related, categories),
  Safebooru.org and Gelbooru (dapi), yande.re and Konachan (moebooru).
  safebooru.donmai.us sits behind a challenge and is not one of them. Sites
  without server categories are grouped by `pylib/boorutags`.
- **Wiki DText becomes plain text** (`_dtext_plain`); `[[links]]` come back as
  tags drawn as buttons, never markup (DESIGN §2.6).
- **History**: `go()` records before changing the search; stepping between
  posts replaces rather than stacks. Back/forward mouse buttons and Alt+arrows.
- State is `~/.config/booru/state.json` (site, query, rating, order, thumb
  size, blacklist, mute). Saves go to `~/Pictures/booru/<site>-<id>.<ext>`.
- The completer is the shared `qmlcommon/TagPopup.qml` over `boorutags`.

## Testing

```bash
booru-qtenv python3 apps/booru/tools/booru-test.py [--shot DIR]
```

Both faces offscreen against a loopback Danbooru fixture
(`BOORU_BASE_URL`), scratch XDG dirs and a private D-Bus with no service
activation (the stock config starts xdg-desktop-portal-kde and ksecretd, which
outlive the bus). It never touches the network, the user's cache, config or
Pictures. `--shot` writes grid and post PNGs per face for the user's check.

"""booruapi -- the booru sites booru can search, Qt-free.

Ported from cte's `danbooru_api.py` (top's ~/Projects/cte/app): the shared
throttle, the 429 backoff that honours Retry-After, the TTL cache and the
response normalisers survive; the QThread plumbing does not (main.py owns the
threads). cte's Gelbooru key was hard-coded in that file; here every key comes
from ~/.config/booru/<site>.json (mode 0600) and a site that needs one and has
none refuses with the path in its message.

Every call blocks and raises `BooruError`; callers run them off the GUI thread.

Sites differ in what they can answer. `SITES[...]["caps"]` says which of
wiki / related / categories a site has; a site without server-side tag
categories gets them from the local Danbooru vocabulary (pylib/boorutags).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Danbooru's CDN answers 403 to a bare "Mozilla/5.0" (Qt's default) and 200 to
# a named client, measured 2026-11-21. Every request carries this.
USER_AGENT = "booru/0.1 (desktop booru browser)"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "booru"

SITES = {
    "danbooru": {"label": "Danbooru", "api": "danbooru",
                 "base": "https://danbooru.donmai.us",
                 "caps": {"wiki", "related", "categories"}, "key": "optional"},
    "safebooru": {"label": "Safebooru", "api": "gelbooru",
                  "base": "https://safebooru.org", "caps": set(), "key": "none"},
    "gelbooru": {"label": "Gelbooru", "api": "gelbooru",
                 "base": "https://gelbooru.com", "caps": set(), "key": "required"},
    "yandere": {"label": "yande.re", "api": "moebooru",
                "base": "https://yande.re", "caps": set(), "key": "none"},
    "konachan": {"label": "Konachan", "api": "moebooru",
                 "base": "https://konachan.com", "caps": set(), "key": "none"},
}

# Test seam: point every site at a loopback fixture server.
_BASE_OVERRIDE = os.environ.get("BOORU_BASE_URL", "").rstrip("/")

GROUPS = ("artist", "copyright", "character", "general", "meta")

MIN_INTERVAL = 0.15
CACHE_TTL = 600.0
MAX_BACKOFF = 30.0
TIMEOUT = 12.0
RETRIES = 2

VIDEO_EXTS = {"webm", "mp4", "mov", "m4v", "mkv", "ogv"}


class BooruError(Exception):
    pass


def base_url(site):
    return _BASE_OVERRIDE or SITES[site]["base"]


def credentials(site):
    """{"login"/"user_id", "api_key"} from ~/.config/booru/<site>.json, or {}."""
    try:
        d = json.loads((CONFIG_DIR / f"{site}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in d.items() if v} if isinstance(d, dict) else {}


# ---- transport: one throttle and one cache for the whole process -----------

_rate_lock = threading.Lock()
_next_at = 0.0
_backoff = 0.0
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}


def _throttle():
    global _next_at
    with _rate_lock:
        now = time.time()
        wait = max(0.0, _next_at - now)
        _next_at = max(_next_at, now) + MIN_INTERVAL
    if wait:
        time.sleep(wait)


def _mark_429(retry_after):
    global _backoff, _next_at
    with _rate_lock:
        if retry_after:
            _backoff = min(MAX_BACKOFF, retry_after)
        else:
            _backoff = min(MAX_BACKOFF, _backoff * 2 if _backoff else 2.0)
        _next_at = max(_next_at, time.time() + _backoff)


def _mark_ok():
    global _backoff
    with _rate_lock:
        _backoff = 0.0


def _error_text(e: urllib.error.HTTPError):
    try:
        body = e.read().decode("utf-8", "replace")
        d = json.loads(body)
        msg = d.get("message") or d.get("reason") or ""
        if msg:
            return str(msg)
    except Exception:  # noqa: BLE001 - an HTML error page
        pass
    return f"http {e.code}"


def fetch(url, accept="*/*", referer=None):
    """GET bytes, throttled, retried on 429/5xx. Raises BooruError."""
    headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip"}
    if referer:
        headers["Referer"] = referer
    last = None
    for attempt in range(RETRIES + 1):
        _throttle()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                _mark_ok()
                return raw
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    ra = float(e.headers.get("Retry-After") or 0)
                except ValueError:
                    ra = 0
                _mark_429(ra)
                last = BooruError("rate limited, backing off")
                continue
            if e.code in (500, 502, 503, 504) and attempt < RETRIES:
                last = BooruError(_error_text(e))
                time.sleep(min(MAX_BACKOFF, 0.5 * 2 ** attempt))
                continue
            raise BooruError(_error_text(e)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = BooruError(str(getattr(e, "reason", e)))
            continue
    raise last or BooruError("request failed")


def get_json(site, path, params):
    url = base_url(site) + path
    if params:
        url += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
    key = url
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    raw = fetch(url, accept="application/json")
    try:
        data = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else []
    except ValueError:
        raise BooruError("the site did not answer with JSON") from None
    with _cache_lock:
        _cache[key] = (now + CACHE_TTL, data)
    return data


# ---- the one post shape every site normalises to ---------------------------

def _ext(url):
    return os.path.splitext(urllib.parse.urlparse(url or "").path)[1].lstrip(".").lower()


def _kind(ext):
    if ext in VIDEO_EXTS:
        return "video"
    if ext == "gif":
        return "gif"
    return "image"


def _abs(site, u):
    u = str(u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return base_url(site) + u
    return u


_RATING_NAME = {"g": "general", "s": "sensitive", "q": "questionable", "e": "explicit",
                "general": "general", "sensitive": "sensitive", "safe": "safe",
                "questionable": "questionable", "explicit": "explicit"}


def _post(site, *, pid, preview, sample, original, width, height, rating, score,
          source, groups, page):
    original = original or sample
    sample = sample or original
    # What the post view shows. Danbooru's sample of a video is a still or a
    # webm; an ugoira's original is a zip and its sample the webm. Pick the
    # first that a player or an Image can actually open.
    oext = _ext(original)
    sext = _ext(sample)
    if oext in VIDEO_EXTS or oext == "gif":
        view = original
    elif oext == "zip" and sext in VIDEO_EXTS:
        view = sample
    else:
        view = sample
    vext = _ext(view)
    tags = [t for g in GROUPS for t in groups.get(g, [])]
    return {
        "site": site, "id": int(pid or 0),
        "preview": preview or sample, "view": view, "original": original,
        "ext": oext or vext, "kind": _kind(vext),
        "width": int(width or 0), "height": int(height or 0),
        "rating": _RATING_NAME.get(str(rating or "").lower(), str(rating or "")),
        "score": int(score or 0), "source": str(source or ""),
        "groups": {g: groups.get(g, []) for g in GROUPS},
        "tags": tags, "page": page,
    }


def _grouped_locally(tag_string):
    """Tag categories for a site that does not send them: the local Danbooru
    vocabulary's, and `general` for anything it has never heard of."""
    import boorutags
    groups = {g: [] for g in GROUPS}
    for t in str(tag_string or "").split():
        e = boorutags.resolve(t)
        cat = e["category"] if e else "general"
        groups[cat if cat in groups else "general"].append(t)
    return groups


# ---- per-API query mapping -------------------------------------------------

def _query(api, query, rating, order):
    toks = [t for t in str(query or "").split()
            if not t.lower().startswith(("order:", "rating:", "sort:"))]
    if rating:
        r = rating[0]
        if api == "danbooru":
            toks.append(f"rating:{r}")
        elif api == "gelbooru":
            toks.append("rating:" + {"g": "general", "s": "sensitive",
                                     "q": "questionable", "e": "explicit"}[r])
        else:   # moebooru has safe/questionable/explicit; g and s are both "safe"
            toks.append("rating:" + {"g": "s", "s": "s", "q": "q", "e": "e"}[r])
    if order:
        if api == "danbooru":
            toks.append(f"order:{order}")
        elif api == "gelbooru":
            toks.append({"score": "sort:score:desc", "favcount": "sort:score:desc",
                         "rank": "sort:score:desc"}[order])
        else:
            toks.append({"score": "order:score", "favcount": "order:fav",
                         "rank": "order:score"}[order])
    return " ".join(toks)


def search_posts(site, query, page=1, limit=40, rating="", order=""):
    """{"posts": [...], "total": int or None}."""
    s = SITES[site]
    api = s["api"]
    q = _query(api, query, rating, order)
    creds = credentials(site)
    if s["key"] == "required" and not creds.get("api_key"):
        raise BooruError(f"{s['label'].lower()} needs an api key in "
                         f"~/.config/booru/{site}.json")
    if api == "danbooru":
        p = {"tags": q, "limit": limit, "page": page}
        if creds.get("login") and creds.get("api_key"):
            p.update(login=creds["login"], api_key=creds["api_key"])
        rows = get_json(site, "/posts.json", p)
        posts = [x for x in (_danbooru_post(site, r) for r in rows or []) if x]
        total = None
        if page == 1:
            try:
                c = get_json(site, "/counts/posts.json", {"tags": q})
                total = int(c.get("counts", {}).get("posts"))
            except (BooruError, AttributeError, TypeError, ValueError):
                total = None
        return {"posts": posts, "total": total}
    if api == "gelbooru":
        p = {"page": "dapi", "s": "post", "q": "index", "json": "1",
             "tags": q, "limit": limit, "pid": page - 1}
        if creds.get("api_key"):
            p.update(user_id=creds.get("user_id", ""), api_key=creds["api_key"])
        data = get_json(site, "/index.php", p)
        total = None
        if isinstance(data, dict):
            try:
                total = int(data.get("@attributes", {}).get("count"))
            except (TypeError, ValueError):
                total = None
            data = data.get("post", [])
        return {"posts": [_gelbooru_post(site, r) for r in data or [] if isinstance(r, dict)],
                "total": total}
    rows = get_json(site, "/post.json", {"tags": q, "limit": limit, "page": page})
    return {"posts": [_moebooru_post(site, r) for r in rows or [] if isinstance(r, dict)],
            "total": None}


def _danbooru_post(site, r):
    if not isinstance(r, dict) or not r.get("id"):
        return None
    # Banned/deleted posts come back without URLs for anonymous users.
    if not (r.get("file_url") or r.get("large_file_url")):
        return None
    preview = r.get("preview_file_url")
    for v in (r.get("media_asset") or {}).get("variants") or []:
        if v.get("type") == "360x360":
            preview = v.get("url")
    groups = {g: str(r.get("tag_string_" + g) or "").split() for g in GROUPS}
    return _post(site, pid=r["id"], preview=_abs(site, preview),
                 sample=_abs(site, r.get("large_file_url")),
                 original=_abs(site, r.get("file_url")),
                 width=r.get("image_width"), height=r.get("image_height"),
                 rating=r.get("rating"), score=r.get("score"), source=r.get("source"),
                 groups=groups, page=f"{SITES[site]['base']}/posts/{r['id']}")


def _gelbooru_post(site, r):
    return _post(site, pid=r.get("id"), preview=_abs(site, r.get("preview_url")),
                 sample=_abs(site, r.get("sample_url")), original=_abs(site, r.get("file_url")),
                 width=r.get("width"), height=r.get("height"), rating=r.get("rating"),
                 score=r.get("score"), source=r.get("source"),
                 groups=_grouped_locally(r.get("tags")),
                 page=f"{SITES[site]['base']}/index.php?page=post&s=view&id={r.get('id')}")


def _moebooru_post(site, r):
    return _post(site, pid=r.get("id"), preview=_abs(site, r.get("preview_url")),
                 sample=_abs(site, r.get("sample_url")), original=_abs(site, r.get("file_url")),
                 width=r.get("width"), height=r.get("height"), rating=r.get("rating"),
                 score=r.get("score"), source=r.get("source"),
                 groups=_grouped_locally(r.get("tags")),
                 page=f"{SITES[site]['base']}/post/show/{r.get('id')}")


# ---- Danbooru-only lookups -------------------------------------------------

def wiki(site, tag):
    """{"title", "body"} — body is DText, `[[links]]` intact. "" when none."""
    if "wiki" not in SITES[site]["caps"]:
        return {"title": tag, "body": ""}
    rows = get_json(site, "/wiki_pages.json",
                    {"search[title]": tag, "limit": 1, "only": "title,body"})
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return {"title": str(rows[0].get("title") or tag), "body": str(rows[0].get("body") or "")}
    return {"title": tag, "body": ""}


_CAT_NUM = {"general": 0, "artist": 1, "copyright": 3, "character": 4, "meta": 5}
_NUM_CAT = {v: k for k, v in _CAT_NUM.items()}


def related(site, tag, category="", limit=40):
    """[{"tag", "category", "posts"}], most related first."""
    if "related" not in SITES[site]["caps"]:
        return []
    p = {"query": tag, "limit": limit}
    if category in _CAT_NUM:
        p["category"] = _CAT_NUM[category]
    d = get_json(site, "/related_tag.json", p)
    out = []
    for e in (d.get("related_tags") or []) if isinstance(d, dict) else []:
        t = e.get("tag") or {}
        name = t.get("name")
        if name and name != tag:
            out.append({"tag": name, "category": _NUM_CAT.get(t.get("category"), "general"),
                        "posts": int(t.get("post_count") or 0)})
    return out


# ---- media cache -----------------------------------------------------------

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "booru"
CACHE_LIMIT = 1 << 30   # 1 GiB, pruned oldest-first at startup


def cache_path(url):
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    ext = _ext(url) or "bin"
    return CACHE_DIR / h[:2] / f"{h}.{ext}"


def cached(url):
    """Local path of `url`, downloading it on a miss. Atomic: a half-written
    file is never visible at the final name."""
    p = cache_path(url)
    if p.exists():
        try:
            os.utime(p)
        except OSError:
            pass
        return p
    data = fetch(url, referer=_referer(url))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".part%d" % threading.get_ident())
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return p


def _referer(url):
    host = urllib.parse.urlparse(url).netloc
    for s in SITES.values():
        if host.endswith(urllib.parse.urlparse(s["base"]).netloc.split(".", 1)[-1]):
            return s["base"] + "/"
    return None


def prune_cache(limit=CACHE_LIMIT):
    files = []
    total = 0
    for f in CACHE_DIR.glob("*/*"):
        try:
            st = f.stat()
        except OSError:
            continue
        if ".part" in f.name and time.time() - st.st_mtime > 3600:
            f.unlink(missing_ok=True)
            continue
        files.append((st.st_mtime, st.st_size, f))
        total += st.st_size
    files.sort()
    for _, size, f in files:
        if total <= limit:
            break
        f.unlink(missing_ok=True)
        total -= size

"""How much of his usage is gone — the two numbers under the model chooser.

[his, 2026-07-29] *"add usage indicators directly under the orchestrator
model-selection box: how much of his daily usage and how much of his weekly
usage has been consumed"*, with one explicit constraint: **no Fable figure**.
Three things below are decisions rather than plumbing.

**THE FIGURES ARE THE ACCOUNT'S OWN, NEVER DERIVED HERE.** A percentage per
limit window, account-scoped, computed against the real plan by whoever
published it. Nothing on this desktop knows a limit otherwise — the session
transcripts carry token counts but no denominator, `~/.claude/stats-cache.json`
carries neither and stops updating for days at a time, and there is no `claude
usage` subcommand to ask. **It never derives a percentage from tokens against a
ceiling nobody published**: the same refusal `boardphase` makes about an assumed
context window, for the same reason — a denominator you guessed makes the
numerator a lie (docs/DESIGN.md §10, §10.5).

**TWO CACHES, AND THE FRESHER ONE WINS.** [his, 2026-07-29] *"why did it take me
opening an instance of claude-code for the usage indicators to update? they
should always be up to date"* — and he was right, for a reason no amount of
polling here could fix:

- `~/.claude.json` -> `cachedUsageUtilization` is what the CLI last fetched for
  `/usage`. It was the only source, and **it advances only while a claude-code
  session runs.** Measured on `top` 2026-07-29: with no session live its
  `fetchedAtMs` does not move at all, and even a whole `claude -p "/usage"` run
  leaves it untouched — it printed 16% while the cache still said 14%. The board
  app polled a file nothing was writing, so its number was as old as his last
  session, however honestly it said so.
- So this module now fetches for itself: `fetch()` does the same
  `GET /api/oauth/usage` the CLI does, with the OAuth access token the CLI
  already holds, and writes the answer to `LIVE_PATH` — **a file this app owns.**
  The response body is shape-identical to `cachedUsageUtilization.utilization`
  (`limits[]` and all), so nothing downstream had to learn a second format, and
  a stored payload is wrapped in the same envelope the CLI uses.
- `_cache()` reads both and takes whichever has the newer `fetchedAtMs`, so the
  CLI's own writes are never thrown away and a host where the fetch cannot work
  behaves exactly as before.

**`~/.claude.json` AND THE CREDENTIALS ARE READ-ONLY FROM HERE.** Both belong to
the CLI. In particular `fetch()` uses the access token and **never refreshes or
rewrites it** — the refresh token rotates, and racing the CLI for that file
could log him out of every session on the machine. When the token has expired
the fetch simply fails; `nudge()` asks the CLI to sort its own credentials out
(`claude auth status`, ~0.2s, no session, no transcript) and the fetch is
retried once. If that does not work either, the last reading is still drawn with
its honest age, which is what the old behaviour was for every reading.

**THE SHORT WINDOW IS FIVE HOURS, NOT A DAY.** He asked for "daily"; the
account has no daily bucket. What actually stops him mid-afternoon is the
rolling 5-hour session limit, so that is what is drawn — under its own name,
because putting the word "daily" over a five-hour number is exactly the kind of
mislabelled readout §10.5 is about. The weekly one genuinely is seven days.

**NO FABLE ROW.** The `limits` list carries a `weekly_scoped` entry whose
`scope.model.display_name` is `Fable`, beside the unscoped `weekly_all`. He does
not want that broken out, so this module reads **only entries with no scope** —
and folding needs no arithmetic, because `weekly_all` is already the whole
account with that usage inside it. `utilization.seven_day_opus` /
`seven_day_sonnet` and the rest of the per-model keys are ignored for the same
reason; a future scoped kind is ignored by construction rather than by a name
list that would go stale.

**Unknown is a state, not a zero.** A missing file, a missing key, a percentage
that is not a number: all report `known = False` and the caller draws nothing
where the bar goes. A cache older than `STALE_SEC` still reports its number —
73% an hour ago is not false — but says how old it is, in the row and not only
in a tooltip, so the age cannot be missed (§3.5).

Machine-local by construction: neither `~/.claude.json` nor `LIVE_PATH` is in
the `~/.claude` tree that syncs between `top` and `book`
(`home/srvs/claude-state.nix`), so each host draws what it last read for itself.
The account is the same; the freshness is not.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime

#: Claude Code's own config/cache file. Not under `~/.claude`, and deliberately
#: read-only from here — this app never writes it.
CLAUDE_JSON = os.path.join(os.path.expanduser("~"), ".claude.json")

#: Where `fetch()` puts what it read. The file this app DOES own, in the same
#: envelope the CLI uses so `_read()` needs no second parser. Under
#: `XDG_STATE_HOME` like `main.STATE_PATH`, and machine-local like everything
#: there.
LIVE_PATH = os.path.join(
    os.environ.get("XDG_STATE_HOME")
    or os.path.join(os.path.expanduser("~"), ".local", "state"),
    "board", "usage.json")

#: The CLI's OAuth credentials. Read for the access token, NEVER written — see
#: the docstring.
CREDS = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")

#: The endpoint the CLI itself calls for `/usage` (`GET`, ~350ms, ~1KB).
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

#: Short, because a usage bar is never worth stalling anything for.
FETCH_TIMEOUT = 8.0

#: Set in any harness: `fetch()` and `nudge()` become no-ops, so a test neither
#: reaches the network nor writes his real state directory.
OFFLINE_ENV = "BOARD_USAGE_OFFLINE"

#: Beyond this, the reading still shows but carries its age. The CLI refreshes
#: the cache while a session runs, so an hour is ordinary and a day is not.
STALE_SEC = 2 * 3600

#: The two windows drawn, in order, as `(key, kind, label, hover)`. `kind` is
#: the `limits[].kind` the CLI publishes; `label` is his prose, never the wire
#: name (§2).
WINDOWS = (
    ("session", "session", "5h",
     "the rolling 5 hour session limit - the account has no daily window"),
    ("weekly", "weekly_all", "7d",
     "this week, the whole account - never broken out by model"),
)


def _read(path):
    """`(utilization dict, fetched-at seconds)` from ONE file, or `(None, 0)`.

    Every failure is one answer — unreadable, not JSON, key absent, wrong shape
    — because the app has exactly one thing to say about all of them.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None, 0
    if not isinstance(doc, dict):
        return None, 0
    cached = doc.get("cachedUsageUtilization")
    if not isinstance(cached, dict):
        return None, 0
    util = cached.get("utilization")
    if not isinstance(util, dict):
        return None, 0
    try:
        fetched = float(cached.get("fetchedAtMs") or 0) / 1000.0
    except (TypeError, ValueError):
        fetched = 0.0
    return util, fetched


def _cache(path=None):
    """The FRESHER of the two caches, as `(utilization dict, fetched-at)`.

    An explicit `path` reads exactly that file and nothing else — that is what
    the tests pass, and it is also the honest answer to "what does this file
    say". With no path both are read and the newer `fetchedAtMs` wins, so
    `fetch()`'s reading supersedes the CLI's while a CLI that got there first
    is never discarded.
    """
    if path is not None:
        return _read(path)
    best = (None, 0.0)
    for p in (CLAUDE_JSON, LIVE_PATH):
        util, fetched = _read(p)
        if util is not None and fetched >= best[1]:
            best = (util, fetched)
    return best


def _unscoped(util, kind):
    """The `limits` entry for `kind` that is about NO particular model.

    An entry with a `scope` is a per-model breakout — `weekly_scoped` for Fable
    today — and is the one thing he asked not to see. Skipping it here is the
    whole of that rule; nothing downstream has to know the shape.
    """
    limits = util.get("limits")
    if not isinstance(limits, list):
        return None
    for lim in limits:
        if not isinstance(lim, dict) or lim.get("kind") != kind:
            continue
        if lim.get("scope"):
            continue
        return lim
    return None


#: Fallback keys, for a CLI whose payload predates `limits`. Both are unscoped
#: totals; the per-model `seven_day_opus`-style keys are never read.
_FLAT = {"session": "five_hour", "weekly_all": "seven_day"}


def _percent(util, kind):
    """`(percent, resets_at)` for an unscoped window, or `(None, "")`."""
    lim = _unscoped(util, kind)
    if lim is None:
        flat = util.get(_FLAT.get(kind, ""))
        lim = flat if isinstance(flat, dict) else None
        raw = lim.get("utilization") if lim else None
    else:
        raw = lim.get("percent")
    if lim is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, ""
    resets = lim.get("resets_at")
    return float(raw), resets if isinstance(resets, str) else ""


def _clock(iso, now):
    """`resets_at` as something short and ASCII, or `""`.

    Today reads `5:40pm`; another day gets its weekday in front. The font has no
    ellipsis and no arrows (§2.3), and this string never needs one.
    """
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    stamp = when.strftime("%I:%M%p").lstrip("0").lower()
    if stamp.endswith(":00am") or stamp.endswith(":00pm"):
        stamp = stamp[:-5] + stamp[-2:]
    if when.date() != datetime.fromtimestamp(now).astimezone().date():
        return when.strftime("%a ") + stamp
    return stamp


def _left(iso, now):
    """How long until `resets_at`, terse and ASCII: `2h 14m`, `14m`, or `""`.

    The tooltip is a COUNTDOWN and not a clock time — [his, 2026-07-30] the chip
    should read *"resets in ____"* and nothing else. A wall-clock `5:40pm`
    answers "when" only after he has worked out what time it is now; the
    remaining span is the thing he is actually asking for when he points at a bar
    that is 80% full. `_clock()` stays: `detail` still uses it, and one of these
    is not the other.

    `""` for a time that cannot be parsed OR that has already passed — a reading
    whose window reset before we drew it is stale rather than imminent, and
    saying "resets in 0m" would be inventing a countdown out of an old payload
    (§10). The caller words both cases.
    """
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    left = when.timestamp() - now
    if left <= 0:
        return ""
    if left < 60:
        return "under a minute"
    mins = int(left // 60)
    if mins < 60:
        return "%dm" % mins
    hours, mins = divmod(mins, 60)
    if hours < 24:
        return "%dh %dm" % (hours, mins) if mins else "%dh" % hours
    # The seven-day window resets up to 168 hours out, and `161h 20m` is a
    # number to do arithmetic on rather than a span to read. Two units, coarsest
    # first, the way `_age` steps up (§9.3).
    days, hours = divmod(hours, 24)
    return "%dd %dh" % (days, hours) if hours else "%dd" % days


def _age(seconds):
    """How old the cache is, in the terse register the readouts use (§9.3)."""
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return "%dm old" % round(seconds / 60.0)
    if seconds < 36 * 3600:
        return "%dh old" % round(seconds / 3600.0)
    return "%dd old" % round(seconds / 86400.0)


def readings(path=None, now=None):
    """The two rows the window draws, always both, always in `WINDOWS` order.

    Each is `{key, label, known, percent, text, note, stale, detail, reset}`:
    `percent` is 0-100 and meaningless when `known` is false, `text` is what sits
    beside the bar, `note` is the age when the cache is stale (empty otherwise),
    and `detail` is the hover sentence — which always names the window and,
    when there is nothing to show, says why rather than blaming him.

    `reset` is the row's TOOLTIP, and it is ONE SHORT LINE: [his, 2026-07-30]
    *"the tooltip should just say `resets in ____`"* — a COUNTDOWN (`resets in
    2h 14m`), not the wall-clock time it used to carry and not a sentence naming
    the window. The label is two characters away under the pointer, so the chip
    spends its width on the one thing the row does not already say. It is still
    **never empty**: a payload with no `resets_at`, or one whose reset has
    already gone by, says that instead — the §10 rule that a missing reading is
    reported rather than invented. The wording lives here with the rest of his
    prose, not in the QML.
    """
    now = time.time() if now is None else now
    util, fetched = _cache(path)
    age = max(0.0, now - fetched) if fetched else -1.0
    rows = []
    for key, kind, label, hover in WINDOWS:
        pct, resets = _percent(util, kind) if util else (None, "")
        if pct is None:
            rows.append({
                "key": key, "label": label, "known": False, "percent": 0,
                "text": "unknown", "note": "", "stale": False,
                "detail": ("no usage reading on this host yet - it needs the "
                           "account reachable once"),
                "reset": "resets in ? - no usage reading on this host yet",
            })
            continue
        stale = age < 0 or age > STALE_SEC
        detail = hover
        clock = _clock(resets, now) if resets else ""
        left = _left(resets, now) if resets else ""
        reset = ("resets in %s" % left if left
                 else "resets in ? - this reading carries no reset time"
                 if not resets
                 else "resets in ? - this reading's reset time has gone by")
        if clock:
            detail += " - resets " + clock
        if age >= 0:
            detail += " - read " + _age(age)
        rows.append({
            "key": key, "label": label, "known": True,
            "percent": max(0.0, min(100.0, pct)),
            "text": "%d%%" % round(pct),
            "note": _age(age) if stale and age >= 0 else ("" if age >= 0 else "age unknown"),
            "stale": stale, "detail": detail, "reset": reset,
        })
    return rows


def _token(now):
    """`(access token, seconds until it expires)` from the CLI's credentials.

    `(None, 0)` for every way that can fail, including a token the CLI has
    already let expire — asking with one of those is a round trip that can only
    come back 401.
    """
    try:
        with open(CREDS, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None, 0
    oauth = doc.get("claudeAiOauth") if isinstance(doc, dict) else None
    if not isinstance(oauth, dict):
        return None, 0
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        return None, 0
    try:
        left = float(oauth.get("expiresAt") or 0) / 1000.0 - now
    except (TypeError, ValueError):
        left = 0.0
    return token, left


def _store(util, now):
    """Write `util` to `LIVE_PATH`, atomically, in the CLI's own envelope."""
    doc = {"cachedUsageUtilization": {"fetchedAtMs": int(now * 1000),
                                      "utilization": util}}
    tmp = LIVE_PATH + ".new"
    try:
        os.makedirs(os.path.dirname(LIVE_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        os.replace(tmp, LIVE_PATH)
    except OSError:
        return False
    return True


def fetch(timeout=FETCH_TIMEOUT, now=None):
    """Read the account's live figures and cache them. Never raises.

    Returns a short reason word, `"ok"` on success, for a caller that wants to
    log or to escalate: `off`, `no-token`, `expired`, `unauthorized`,
    `http-<code>`, `offline`, `bad-payload`, `unwritable`. Every one of them
    leaves the previous reading in place, so a failed fetch costs freshness and
    nothing else.

    **A payload that yields no window at all is refused rather than stored** —
    overwriting a real reading with a shape we cannot parse would turn a working
    bar into `unknown` for as long as the endpoint stayed odd.
    """
    if os.environ.get(OFFLINE_ENV):
        return "off"
    now = time.time() if now is None else now
    token, left = _token(now)
    if not token:
        return "no-token"
    if left <= 60:
        return "expired"
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "goetia-usage/1",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            util = json.load(resp)
    except urllib.error.HTTPError as e:
        return "unauthorized" if e.code in (401, 403) else "http-%d" % e.code
    except (urllib.error.URLError, OSError, ValueError):
        return "offline"
    if not isinstance(util, dict):
        return "bad-payload"
    if all(_percent(util, kind)[0] is None for _k, kind, _l, _h in WINDOWS):
        return "bad-payload"
    return "ok" if _store(util, now) else "unwritable"


def nudge():
    """Ask the CLI to sort out its own expired token, and say whether it ran.

    `claude auth status` is the cheapest thing that touches auth at all —
    measured on `top`: 0.22s, no session, no transcript, no model call — and it
    is the CLI's job to refresh from there. **We never write the credentials
    ourselves**; see the module docstring for why that is not a shortcut worth
    taking. Best effort by construction: if it is not on `PATH`, or it hangs, or
    it fails, the caller keeps the reading it already had.
    """
    if os.environ.get(OFFLINE_ENV):
        return False
    try:
        subprocess.run(["claude", "auth", "status"], timeout=30,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return True

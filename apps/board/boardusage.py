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
import math
import os
import sqlite3
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


# ------------------------------------------- nous (hermes) account balance
#: Hermes' own OAuth credentials. Read for the `nous` access token, NEVER
#: written — same rule as `~/.claude/.credentials.json` above: the refresh
#: token rotates and a rewrite here would race the CLI and risk logging him out
#: of every hermes session on the machine. It is machine-local (hermes is
#: installed per host; `~/.claude` syncs, `~/.hermes` does not), which is
#: exactly the split every other reading here already relies on.
NOUS_CREDS = os.path.join(os.path.expanduser("~"), ".hermes", "auth.json")

#: Where `fetch_nous()` puts what it read. A file the board app owns, under the
#: same `XDG_STATE_HOME/board` tree as `LIVE_PATH`, machine-local like it.
NOUS_LIVE_PATH = os.path.join(
    os.environ.get("XDG_STATE_HOME")
    or os.path.join(os.path.expanduser("~"), ".local", "state"),
    "board", "nous.json")

#: The portal account endpoint Hermes itself calls for the real balance
#: (`GET {portal_base}/api/oauth/account`, with the oauth access token). It is
#: the same call `hermes_cli.nous_account.__fetch_nous_account_info` makes, so
#: the figure here is the account's own, not derived (§2). The scope on the
#: token is `inference:invoke`; the endpoint is the one that publishes the
#: subscription and usable-credit fields below, so it is reachable with the
#: token hermes already holds.
NOUS_ACCOUNT_PATH = "/api/oauth/account"

#: The portal's own base when the credentials do not name one.
NOUS_PORTAL_DEFAULT = "https://portal.nousresearch.com"


def _nous_token():
    """`(access token, portal base)` from Hermes' credentials, or `(None, None)`.

    Every failure is one answer — unreadable, not JSON, no nous provider, no
    token. The token is never refreshed or rewritten from here (see `NOUS_CREDS`).
    """
    try:
        with open(NOUS_CREDS, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None, None
    prov = doc.get("providers", {}).get("nous") if isinstance(doc, dict) else None
    if not isinstance(prov, dict):
        return None, None
    token = prov.get("access_token")
    if not isinstance(token, str) or not token:
        return None, None
    base = prov.get("portal_base_url")
    return token, base if isinstance(base, str) and base.strip() else None


def _nous_read(path=None):
    """`(account payload dict, fetched-at seconds)` from the board's own cache,
    or `(None, 0)`. Every failure is one answer, like `_read`."""
    p = NOUS_LIVE_PATH if path is None else path
    try:
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None, 0
    if not isinstance(doc, dict):
        return None, 0
    payload = doc.get("account")
    if not isinstance(payload, dict):
        return None, 0
    try:
        fetched = float(doc.get("fetchedAtMs") or 0) / 1000.0
    except (TypeError, ValueError):
        fetched = 0.0
    return payload, fetched


def _num(v):
    """`v` as a finite float, or None for anything not a usable number.

    Non-finite values (NaN/Inf) slip past `isinstance` and are refused the same
    way `agent.account_usage` refuses them — "$nan of $22 left" would be a lie.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if (f != f or f in (float("inf"), float("-inf"))) else f


def _nous_account_fields(payload):
    """`(cap, remaining, renews)` parsed out of a portal account payload.

    `cap` is the subscription's `monthly_credits` — a real denominator the
    portal publishes only when a subscription defines one. `remaining` is the
    usable balance: the subscription's `credits_remaining`, falling back
    through `paid_service_access.subscription_credits_remaining` to
    `total_usable_credits` for an account whose subscription object is lean.
    `renews` is the `current_period_end`, when present. `remaining` may be
    None (nothing usable published); `cap` and `renews` may be None too.
    """
    sub = payload.get("subscription") if isinstance(payload, dict) else None
    psa = payload.get("paid_service_access") if isinstance(payload, dict) else None
    sub = sub if isinstance(sub, dict) else None
    psa = psa if isinstance(psa, dict) else None
    cap = _num(sub.get("monthly_credits")) if sub else None
    remaining = _num(sub.get("credits_remaining")) if sub else None
    if remaining is None and psa is not None:
        remaining = _num(psa.get("subscription_credits_remaining"))
    if remaining is None and psa is not None:
        remaining = _num(psa.get("total_usable_credits"))
    renews = sub.get("current_period_end") if sub else None
    renews = renews if isinstance(renews, str) else None
    return cap, remaining, renews


def _nous_topup(payload):
    """The purchased ("top-up") credit balance the account can still spend, or
    None.

    This is the pay-as-you-go pool the portal publishes as
    `purchased_credits_remaining` — SEPARATE from the monthly subscription
    `credits_remaining` that `_nous_account_fields` counts down. On a plan whose
    monthly credits are spent (`credits_remaining` 0), this is the only usable
    money left, which is exactly why it is drawn beside the subscription row.
    Falls back to `paid_service_access.purchased_credits_remaining`, the same
    figure the portal mirrors there. The account's own number, never derived
    (§2).
    """
    if not isinstance(payload, dict):
        return None
    v = _num(payload.get("purchased_credits_remaining"))
    if v is None:
        psa = payload.get("paid_service_access")
        if isinstance(psa, dict):
            v = _num(psa.get("purchased_credits_remaining"))
    return v


def _nous_store(payload, now):
    """Write `payload` to `NOUS_LIVE_PATH`, atomically, in our own envelope."""
    doc = {"fetchedAtMs": int(now * 1000), "account": payload}
    tmp = NOUS_LIVE_PATH + ".new"
    try:
        os.makedirs(os.path.dirname(NOUS_LIVE_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        os.replace(tmp, NOUS_LIVE_PATH)
    except OSError:
        return False
    return True


def fetch_nous(timeout=FETCH_TIMEOUT, now=None):
    """Read the account's REAL balance from the portal API and cache it.

    Never raises. Returns a short reason word like `fetch()`: `off`, `no-token`,
    `unauthorized`, `http-<code>`, `offline`, `bad-payload`, `unwritable`, or
    `ok`. A failure leaves the previous reading in place, and a payload that
    yields no usable balance at all is refused rather than stored — overwriting
    a real reading with a shape we cannot use would blank the bar for as long as
    the endpoint stayed odd, the same rule `fetch()` applies.

    This is the balance route the board's hermes readout had no figure for: the
    account's own `remaining` of the account's own `monthly_credits`, published
    by the portal, fetched here with the token hermes already holds.
    """
    if os.environ.get(OFFLINE_ENV):
        return "off"
    now = time.time() if now is None else now
    token, base = _nous_token()
    if not token:
        return "no-token"
    url = ((base or NOUS_PORTAL_DEFAULT).rstrip("/") + NOUS_ACCOUNT_PATH)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "goetia-usage/1",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        return "unauthorized" if e.code in (401, 403) else "http-%d" % e.code
    except (urllib.error.URLError, OSError, ValueError):
        return "offline"
    if not isinstance(payload, dict):
        return "bad-payload"
    if _nous_account_fields(payload)[1] is None:
        return "bad-payload"
    return "ok" if _nous_store(payload, now) else "unwritable"


def _nous_balance(path=None, now=None):
    """The cached balance as `{remaining, cap, used, fraction, renews, age}`, or
    None when no usable reading is cached. `fraction` is the used share of
    `cap` (0..1) and None when the portal publishes no `monthly_credits`
    denominator. `age` is the cache's age in seconds (-1 when unknown)."""
    now = time.time() if now is None else now
    payload, fetched = _nous_read(path)
    if payload is None:
        return None
    cap, remaining, renews = _nous_account_fields(payload)
    if remaining is None:
        return None
    used = fraction = None
    if cap is not None and cap > 0 and remaining <= cap:
        used = cap - remaining
        fraction = used / cap
    return {
        "remaining": remaining, "cap": cap, "used": used, "fraction": fraction,
        "renews": renews,
        "age": max(0.0, now - fetched) if fetched else -1.0,
    }


def _fmt_usd(v):
    """A dollar balance in the readout's short register: `$20.50`."""
    return "$%.2f" % v


def _level_for(fraction):
    """The PROXIMITY_LEVELS band a used-fraction falls in, or None."""
    if fraction is None:
        return None
    for level, low, high in PROXIMITY_LEVELS:
        if low <= fraction < high:
            return level
    return None


# ------------------------------------------------- hermes spirit usage
#: Hermes' session store. Read-only from here, never written: it is Hermes'
#: own ledger (`hermes insights` reads the same file).
HERMES_DB = os.path.join(os.path.expanduser("~"), ".hermes", "state.db")

#: Spirit spawns run hermes with `--source tool` (`HermesBackend.args`), so a
#: query filtered on this source is exactly the hermes usage this board's
#: spirits produced — never his interactive sessions or his other agents.
HERMES_SOURCE = "tool"

#: The two recency windows the hermes readout mirrors the settings with, in the
#: same `(key, label, hover)` tuple shape the Anthropic meters use. Labels are
#: recency, not "session limit": there is no published hermes limit to be a %
#: of, so these are FIGURES (tokens + cost), never a percentage — see the
#: module docstring for that rule (docs/DESIGN.md §10).
HERMES_WINDOWS = (
    ("h5", "5h", "hermes spirit usage in the last 5 hours - tokens and cost"),
    ("d7", "7d", "hermes spirit usage in the last 7 days - tokens and cost"),
)


def _fmt_tokens(n):
    """A token count as the short, human figure the readouts use: `1.2M`,
    `48k`, or the bare number below a thousand."""
    n = int(n or 0)
    if n >= 1_000_000:
        v = ("%.2f" % (n / 1_000_000.0)).rstrip("0").rstrip(".")
        return v + "M"
    if n >= 1_000:
        v = ("%.1f" % (n / 1_000.0)).rstrip("0").rstrip(".")
        return v + "k"
    return str(n)


def _hermes_db_path():
    """The ledger path, honouring the `BOARD_HERMES_DB` redirect `boardhermes`
    sets up for a harness. This module opens the same file through its own
    read-only connection; one path rule, so a test cannot miss it."""
    return os.environ.get("BOARD_HERMES_DB") or HERMES_DB


def _hermes_query(seconds, now):
    """`(tokens, cost_usd)` for spirits in the last `seconds`, or `(None, 0)`
    if the ledger is unreachable. Public for the harness; the board draws via
    `hermes_readings()`."""
    try:
        db = sqlite3.connect("file:%s?mode=ro" % _hermes_db_path(), uri=True)
    except (OSError, sqlite3.Error):
        return None, 0.0
    try:
        row = db.execute(
            "SELECT COALESCE(SUM(input_tokens),0)"
            ", COALESCE(SUM(output_tokens),0)"
            ", COALESCE(SUM(cache_read_tokens),0)"
            ", COALESCE(SUM(cache_write_tokens),0)"
            ", COALESCE(SUM(reasoning_tokens),0)"
            ", COALESCE(SUM(estimated_cost_usd),0)"
            " FROM sessions WHERE source=? AND started_at>=?",
            (HERMES_SOURCE, now - seconds)).fetchone()
    except sqlite3.Error:
        return None, 0.0
    finally:
        try:
            db.close()
        except sqlite3.Error:
            pass
    if row is None:
        return None, 0.0
    tokens = sum(int(x or 0) for x in row[:5])
    return tokens, float(row[5] or 0.0)


def hermes_readings(now=None):
    """The hermes spirit usage rows the window draws, in `HERMES_WINDOWS`
    order. Each is `{key, label, known, text, note, detail}` where `known` is
    false when the ledger is unreachable (nothing drawn), and `text` is real
    figures — `<tokens> · $<cost>` — never a percentage. Honest by the same
    rule as the Anthropic meters: a number here is what Hermes recorded, and
    `known=False` reports the absence rather than inventing a zero."""
    now = time.time() if now is None else now
    rows = []
    for key, label, hover in HERMES_WINDOWS:
        tokens, cost = _hermes_query(_WINDOW_SECS.get(key, 0), now)
        if tokens is None:
            rows.append({
                "key": key, "label": label, "known": False,
                "text": "unknown", "note": "",
                "detail": ("no hermes ledger on this host yet - it needs one "
                           "hermes spirit run to have written state.db"),
            })
            continue
        rows.append({
            "key": key, "label": label, "known": True,
            "text": "%s · $%.2f" % (_fmt_tokens(tokens), cost),
            "note": "", "detail": hover,
        })
    return rows


# ------------------------------------------------- hermes proximity signal
#: The coarse level the display draws for the hermes spirit spend, and the
#: two FRACTION bounds each level means (level, low, high). CHOSEN AND STATED
#: HERE, IN ONE PLACE, so the QML binds the `level` string and never does
#: arithmetic. `fraction` is the USED share of the real monthly cap the portal
#: publishes (`fetch_nous`); when the plan defines no `monthly_credits` it is
#: None and `level` stays "unknown", because there is no margin to judge.
#: Bands are spend-fraction of the limit: below 60% ok, to 85% warning,
#: beyond critical.
PROXIMITY_LEVELS = (
    ("ok",       0.0,  0.60),
    ("warning",  0.60, 0.85),
    ("critical", 0.85, 1.01),
)

#: What each level means, for the hover sentence when the day a fraction can
#: be computed. Kept beside the thresholds so the wording moves with them.
PROXIMITY_WORD = {
    "ok": "well within the limit",
    "warning": "getting close to the limit",
    "critical": "very close to the limit",
}


# ----------------------------------------------------------- his own budget
#: The allowance HE can set for the hermes spirit window — ONE number, a
#: dollar budget, stored where the board keeps its other settings
#: (`~/.local/state/board/`, the same dir `boardwork` uses for `cap` and
#: `summoners`). It is the fallback denominator for `hermes_proximity` when the
#: real nous account publishes no monthly `monthly_credits` cap (a pay-as-you-go
#: plan) or no balance has been read at all; with none set, the honest-unknown
#: path stands. It is only ever his number, never invented (docs/DESIGN.md §10).
def _hermes_budget_file():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "board", "hermes_budget")


def hermes_budget():
    """His dollar budget for the spirit window, or None when unset."""
    try:
        with open(_hermes_budget_file(), "r", encoding="utf-8") as f:
            v = float(f.read().strip())
    except (OSError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def set_hermes_budget(v):
    """Persist his budget, returning it. Raises ValueError for a non-positive one."""
    v = float(v)
    if not math.isfinite(v) or v <= 0:
        raise ValueError("a budget is a positive dollar amount")
    p = _hermes_budget_file()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("%.2f\n" % v)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return v


def clear_hermes_budget():
    """Remove his budget; the honest-unknown path stands again."""
    try:
        os.remove(_hermes_budget_file())
    except OSError:
        pass


def _hermes_span(now):
    """`(tokens, cost_usd, span_days)` for spirits in the LAST 7 DAYS.

    `span_days` is how much real history that window contains (clamped to at
    least an hour, at most 7) — the honest denominator for a per-day burn
    rate, so a machine that only started running spirits yesterday is not
    assumed to have spent across a full week. `(None, 0.0, 0.0)` when the
    ledger is unreachable.
    """
    secs = _WINDOW_SECS["d7"]
    now = time.time() if now is None else now
    try:
        db = sqlite3.connect("file:%s?mode=ro" % _hermes_db_path(), uri=True)
    except (OSError, sqlite3.Error):
        return None, 0.0, 0.0
    try:
        row = db.execute(
            "SELECT COALESCE(SUM(input_tokens),0)"
            ", COALESCE(SUM(output_tokens),0)"
            ", COALESCE(SUM(cache_read_tokens),0)"
            ", COALESCE(SUM(cache_write_tokens),0)"
            ", COALESCE(SUM(reasoning_tokens),0)"
            ", COALESCE(SUM(estimated_cost_usd),0)"
            ", MIN(started_at), COUNT(*) FROM sessions"
            " WHERE source=? AND started_at>=?",
            (HERMES_SOURCE, now - secs)).fetchone()
    except sqlite3.Error:
        return None, 0.0, 0.0
    finally:
        try:
            db.close()
        except sqlite3.Error:
            pass
    if row is None or row[1] is None:
        return None, 0.0, 0.0
    tokens = sum(int(x or 0) for x in row[:5])
    cost = float(row[5] or 0.0)
    n = int(row[7] or 0)
    if n == 0:
        return 0, 0.0, 0.0
    min_start = float(row[6] or now)
    span_days = max(1 / 24.0, min(7.0, (now - min_start) / 86400.0))
    return tokens, cost, span_days


def _prox_reset(renews, now):
    """The hermes proximity row's TOOLTIP — `resets in ____` on the nous
    account's `renews`, the one reset the row's "% used" is a share of.

    Same register as `readings()`'s `reset`, so the two tooltips read alike:
    a COUNTDOWN (`resets in 2h 14m`), and never empty — no `renews` read yet,
    or one whose time has gone by, each words itself rather than inventing a
    countdown (docs/DESIGN.md §10).
    """
    if not renews:
        return "resets in ? - the nous account has not been read on this host yet"
    left = _left(renews, now)
    if left:
        return "resets in %s" % left
    return "resets in ? - this renewal time has gone by"


def hermes_proximity(now=None):
    """The ONE signal the display binds for "how much of hermes is left".

    [his, 2026-07-31] the readout counts down FROM the account's REAL balance
    — the nous subscription, whose `remaining` and monthly `monthly_credits`
    the portal publishes and this module fetches (`fetch_nous`). So where this
    function used to be an explicit unknown because "no figure reaches this
    desktop", there is one now, read with the token hermes already holds.

    Returns a dict:
      known     bool        True when a real balance is cached and readable
      fraction  float|None  0..1 of the monthly cap used, None when the portal
                            publishes no `monthly_credits` denominator (the
                            % gauge then has nothing to be a share of, and is
                            not invented — docs/DESIGN.md §10)
      remaining float|None  $ of the balance left (None when not known)
      level     str         "ok" | "warning" | "critical" | "unknown" — the
                            PROXIMITY_LEVELS band the used-fraction falls in;
                            "unknown" when there is no fraction to judge, and
                            the fallback (broken / stale / missing cache) case
      text      str         one short data-backed line for the row
      detail    str         the hover sentence: the number and why not more

    When no balance is cached (never fetched, stale beyond tolerance, or a
    payload that parses to nothing usable) it falls back to the ledger-based
    honest unknown — spend and burn rate only, `known` False — the exact
    behaviour before this decision, because a number we cannot verify is the
    one thing this function must never draw as real.

    The one case the real account cannot answer is his settable budget
    (`hermes_budget`): when the plan publishes no monthly denominator, or no
    balance has been read at all, a budget he set becomes the allowance and the
    signal counts his spirit spend against it — `used`, `left`, `fraction`
    and the level are then real arithmetic on his own number, never invented.
    With no budget set and no real figure, the honesty above stands.
    """
    now = time.time() if now is None else now
    bal = _nous_balance(now=now)
    # ---- his OWN budget: the settable fallback (see `hermes_budget`) ----
    # Consulted only when the real account data cannot answer used-vs-left by
    # itself: the plan publishes no `monthly_credits` denominator, or no balance
    # has been read at all. A real balance WITH a fraction always wins, so his
    # number never overrides it. With no budget set this block is skipped and
    # the honest-unknown paths below stand exactly as before.
    if bal is None or bal["fraction"] is None:
        budget = hermes_budget()
        if budget is not None:
            tokens, cost, span_days = _hermes_span(now)
            if tokens is not None:
                per_day = cost / span_days if span_days else 0.0
                left = max(0.0, budget - cost)
                fraction = min(1.0, cost / budget) if budget > 0 else None
                level = _level_for(fraction) or "unknown"
                burn = (" · ~$%.2f/day" % per_day) if per_day else ""
                text = "$%.2f used of $%.2f budget - $%.2f left%s" % (
                    cost, budget, left, burn)
                detail = ("his $%.2f budget for the spirit window; hermes "
                          "spirits spent $%.2f in 7d, $%.2f left%s" % (
                              budget, cost, left, burn))
                if bal is not None:
                    detail += ("; the nous account itself shows $%.2f usable"
                               % bal["remaining"])
                return {
                    "known": True, "fraction": fraction, "remaining": left,
                    "level": level, "text": text, "detail": detail,
                    "reset": _prox_reset(bal["renews"] if bal else None, now),
                }
    if bal is not None:
        remaining = bal["remaining"]
        cap = bal["cap"]
        fraction = bal["fraction"]
        level = _level_for(fraction)
        level = level if level is not None else "unknown"
        if fraction is not None:
            pct = round(fraction * 100.0)
            text = "%d%% used · %s left" % (pct, _fmt_usd(remaining))
        else:
            text = "%s left" % _fmt_usd(remaining)
        bits = ["%s left" % _fmt_usd(remaining)]
        if cap is not None:
            bits.append("%s this period" % _fmt_usd(cap))
        if bal["renews"]:
            clock = _clock(bal["renews"], now)
            if clock:
                bits.append("renews %s" % clock)
        if fraction is not None and level in PROXIMITY_WORD:
            bits.append(PROXIMITY_WORD[level])
        detail = "; ".join(bits)
        if bal["age"] >= 0:
            detail += " - read " + _age(bal["age"])
        else:
            detail += " - read age unknown"
        return {
            "known": True, "fraction": fraction, "remaining": remaining,
            "level": level, "text": text, "detail": detail,
            "reset": _prox_reset(bal["renews"], now),
        }
    # No real balance to count down from: the ledger-only honest shrug. Same
    # wording as before the decision — spend and burn rate, and the reason the
    # margin is unknown.
    tokens, cost, span_days = _hermes_span(now)
    if tokens is None:
        return {
            "known": False, "fraction": None, "remaining": None,
            "level": "unknown", "text": "unknown",
            "detail": ("no hermes ledger on this host yet - it needs one hermes "
                       "spirit run to have written state.db"),
            "reset": _prox_reset(None, now),
        }
    per_day = cost / span_days if span_days else 0.0
    text = "~$%.2f in 7d · ~$%.2f/day" % (cost, per_day)
    detail = ("hermes spirits spent ~$%.2f in 7d (~$%.2f/day); the real nous "
              "account balance has not been read on this host yet, so the margin "
              "is unknown") % (cost, per_day)
    return {
        "known": False, "fraction": None, "remaining": None,
        "level": "unknown", "text": text, "detail": detail,
        "reset": _prox_reset(None, now),
    }


def hermes_topup(now=None, path=None):
    """The account's TOP-UP balance — the purchased pay-as-you-go credit left.

    [his, 2026-08-02] *"hermes agent usage should also show the top up money
    left as well"*. `hermes_proximity` counts down the monthly SUBSCRIPTION
    allowance; the top-up is the other pool — credits he bought outright, which
    the portal publishes as `purchased_credits_remaining` (`_nous_topup`) beside
    that subscription. On his Plus plan whose monthly credits are spent it is
    the whole of what is usable, so it is its own row rather than folded in. The
    figure is the account's own, read from the same `nous.json` cache the
    proximity row uses, never derived and never invented (§2, docs/DESIGN.md
    §10).

    Returns a dict:
      known     bool        True when a top-up figure is cached and readable
      remaining float|None  $ of purchased credit left (None when not known)
      text      str         one short data-backed line for the row
      detail    str         the hover sentence: the figure and its read age

    When no balance has been cached on this host (never fetched, or a payload
    that carried no purchased-credit field) it is an honest unknown — nothing
    is drawn as real that has not been read, exactly like `hermes_proximity`'s
    fallback.
    """
    now = time.time() if now is None else now
    payload, fetched = _nous_read(path)
    topup = _nous_topup(payload)
    if topup is None:
        return {
            "known": False, "remaining": None,
            "text": "top-up unknown",
            "detail": ("the nous account has not been read on this host yet, so "
                       "the top-up balance is unknown"),
        }
    age = max(0.0, now - fetched) if fetched else -1.0
    text = "%s top-up left" % _fmt_usd(topup)
    detail = "%s of purchased top-up credit left" % _fmt_usd(topup)
    detail += (" - read " + _age(age)) if age >= 0 else " - read age unknown"
    return {
        "known": True, "remaining": topup,
        "text": text, "detail": detail,
    }


#: Seconds per `HERMES_WINDOWS` key.
_WINDOW_SECS = {"h5": 5 * 3600, "d7": 7 * 86400}

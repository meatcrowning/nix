"""How much of his usage is gone — the two numbers under the model chooser.

[his, 2026-07-29] *"add usage indicators directly under the orchestrator
model-selection box: how much of his daily usage and how much of his weekly
usage has been consumed"*, with one explicit constraint: **no Fable figure**.
Three things below are decisions rather than plumbing.

**THE SOURCE IS CLAUDE CODE'S OWN CACHE, and it is the only one on this
desktop.** `~/.claude.json` -> `cachedUsageUtilization` is what the CLI last
fetched for `/usage`: a percentage per limit window, account-scoped, refreshed
while a session runs. Nothing else here knows a limit at all — the session
transcripts carry token counts but no denominator, `~/.claude/stats-cache.json`
carries neither and stops updating for days at a time, and there is no `claude
usage` subcommand to ask. So every percentage this module reports is one the
CLI already computed against the real plan; **it never derives one from tokens
against a ceiling nobody published**. That is the same refusal `boardphase`
makes about an assumed context window, for the same reason: a denominator you
guessed makes the numerator a lie (docs/DESIGN.md §10, §10.5).

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

Machine-local by construction: `~/.claude.json` is not in the `~/.claude` tree
that syncs between `top` and `book` (`home/srvs/claude-state.nix`), so each host
draws what its own CLI last fetched. The account is the same; the freshness is
not.
"""
import json
import os
import time
from datetime import datetime

#: Claude Code's own config/cache file. Not under `~/.claude`, and deliberately
#: read-only from here — this app never writes it.
CLAUDE_JSON = os.path.join(os.path.expanduser("~"), ".claude.json")

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


def _cache(path=None):
    """`(utilization dict, fetched-at seconds)`, or `(None, 0)`.

    Every failure is one answer — unreadable, not JSON, key absent, wrong shape
    — because the app has exactly one thing to say about all of them.
    """
    try:
        with open(path or CLAUDE_JSON, "r", encoding="utf-8") as f:
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

    Each is `{key, label, known, percent, text, note, stale, detail}`:
    `percent` is 0-100 and meaningless when `known` is false, `text` is what sits
    beside the bar, `note` is the age when the cache is stale (empty otherwise),
    and `detail` is the hover sentence — which always names the window and,
    when there is nothing to show, says why rather than blaming him.
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
                "detail": ("no usage reading on this host yet - claude code "
                           "caches one while it runs"),
            })
            continue
        stale = age < 0 or age > STALE_SEC
        detail = hover
        if resets:
            clock = _clock(resets, now)
            if clock:
                detail += " - resets " + clock
        if age >= 0:
            detail += " - read " + _age(age)
        rows.append({
            "key": key, "label": label, "known": True,
            "percent": max(0.0, min(100.0, pct)),
            "text": "%d%%" % round(pct),
            "note": _age(age) if stale and age >= 0 else ("" if age >= 0 else "age unknown"),
            "stale": stale, "detail": detail,
        })
    return rows

"""What the board SYSTEM spends, across every provider it dispatches to.

[his ask, 2026-08-02] a usage/spend section in goetia — its own band beside the
others — showing, across ALL the providers this board automation reaches (the
deepseek/hermes ministers AND every Claude tier haiku/sonnet/opus/fable): how
many agents were dispatched per model, what each model cost, and the total
tokens split input vs output.

**This is the board system's OWN footprint, not his interactive coding.** A
Claude session counts here only when its first prompt marks it as something the
board spawned — a summoner tick (Solomon), a dispatched minister/worker, or a
decision agent (`_role_of`, the same markers `tools/claude-usage-report.py` and
`boardphase` read). His own `claude` sessions at this desk are his, not the
board's, and are left out — the section is about what the automation costs.

**Two providers, two ledgers, and neither figure is invented (docs/DESIGN.md
§10, §10.5).**

- **Claude tiers** have no cost or token ledger anywhere on the machine —
  `~/.claude.json` carries only a percentage of the account limit, never broken
  out by model (see `boardusage`). So the Claude figures are summed from the
  session transcripts (`~/.claude/projects/*/*.jsonl`), whose assistant messages
  carry a real `usage` block (`input_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`, `output_tokens`) and the `model` that produced
  them. The tokens are MEASURED; the dollar figure is those tokens weighted by
  the public per-token API rates (`RATES`) — a **compute-weight, not a bill**,
  because he is on a plan measured in % of limit and there is no invoice to read.
  That is stated in the readout, never implied away.
- **deepseek/hermes ministers** DO keep a real ledger — Hermes' own
  `~/.hermes/state.db` — with `estimated_cost_usd` the provider itself computed
  and true input/output token columns. Board ministers run `--source tool`
  (`boardusage.HERMES_SOURCE`), so that filter is exactly this board's hermes
  spend. Here the cost is the provider's own estimate, not ours.

**A missing source is UNKNOWN, never a zero.** No transcripts, no hermes ledger:
that provider simply contributes no rows and `known` says so, rather than
drawing a confident $0 for work that may well have happened.

Read-only throughout. The transcripts and `~/.hermes/state.db` both belong to
other programs; this module only ever opens them `mode=ro` and reads.
"""
import collections
import datetime
import glob
import json
import os
import sqlite3
import time

import boardusage  # beside this file — HERMES_DB / HERMES_SOURCE path rules

CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")

#: Per-token USD rates, the public API prices, used ONLY as a cost weight for
#: the Claude side (there is no bill to read). Same table and provenance as
#: `tools/claude-usage-report.py`: (fresh_in, cache_read, cache_write, output).
#: cache_write is the 5-minute rate — the overwhelming majority of writes here.
RATES = {
    "opus":   (15e-6, 1.5e-6, 18.75e-6, 75e-6),
    "sonnet": (3e-6,  0.3e-6, 3.75e-6,  15e-6),
    "haiku":  (0.8e-6, 0.08e-6, 1e-6,   4e-6),
    "fable":  (3e-6,  0.3e-6, 3.75e-6,  15e-6),   # ASSUMED sonnet-tier
}

#: The order families are drawn in when costs tie — a stable, sensible ranking
#: rather than dict insertion. Cost desc is the real sort; this only breaks ties.
_FAMILY_ORDER = ("opus", "sonnet", "haiku", "fable", "deepseek", "other")

#: How many days the per-day token chart spans — a month, one bar per day. This
#: window is FIXED and independent of `snapshot`'s aggregate `window`: the ranked
#: list may be all-time while the chart is always the trailing month, so the two
#: never share a cutoff.
DAILY_DAYS = 30


def _day_str(epoch):
    """The local calendar day an epoch falls in, `YYYY-MM-DD` — the bucket key
    both the Claude and hermes daily series agree on (both use local time, as
    does `snapshot`'s dense-day fill, so a bar lines up with the day he lived)."""
    return datetime.date.fromtimestamp(epoch).isoformat()


def _fam(model):
    """The Claude tier family a wire model string belongs to, or None."""
    if not model:
        return None
    m = model.lower()
    for k in ("opus", "sonnet", "haiku", "fable"):
        if k in m:
            return k
    return None


#: The board-role markers, read from a session's FIRST user prompt (the role
#: prompt the spawner injected). Identical to the ones `boardphase` and the
#: usage report key on — kept in sync by being the literal spawn-prompt text.
def _role_of(first_user):
    t = first_user or ""
    if "You are Solomon" in t:
        return "summoner"
    if ("split up something he asked for" in t
            or "bound you to one piece" in t
            or "gave you one piece" in t):
        return "worker"
    if ("He answered one decision" in t
            or "Your whole job is that ONE decision" in t):
        return "decision"
    return None   # his own interactive/headless session — not the board's spend


def _claude_rows(now, window):
    """`(agg, daily)` for board-spawned Claude sessions.

    `agg` is `{family: {"dispatched", "cost", "in", "out"}}` over the aggregate
    `window` (the ranked list's numbers). `daily` is `{day: {family: tokens}}`
    over the trailing `DAILY_DAYS`, independent of the aggregate cutoff — its own
    window, so the chart is always a month even when the list is all-time. Both
    empty when there are no transcripts to read.

    One transcript is one dispatched agent, filed under the family of the model
    that did most of its turns, and attributed to the day of its last activity.
    Tokens are the real `usage` sums; `cost` is those tokens weighted by `RATES`
    — a compute-weight, said so upstream."""
    files = glob.glob(os.path.join(CLAUDE_PROJECTS, "*", "*.jsonl"))
    out = collections.defaultdict(
        lambda: {"dispatched": 0, "cost": 0.0, "in": 0, "out": 0})
    daily = collections.defaultdict(lambda: collections.defaultdict(int))
    cutoff = None if window is None else now - window
    daily_cutoff = now - DAILY_DAYS * 86400
    live = set(files)
    for stale in [k for k in _SUMMARIES if k not in live]:
        del _SUMMARIES[stale]           # a transcript that was moved or deleted
    for f in files:
        got = _summary(f)
        if got is None:
            continue
        fam, t_in, t_out, cost, ts = got
        # The daily series has its OWN trailing-month window, applied before the
        # aggregate cutoff so the chart stays a full month even when the list is
        # narrower (or, as by default, all-time).
        if ts is not None and ts >= daily_cutoff:
            daily[_day_str(ts)][fam] += t_in + t_out
        if cutoff is not None:
            if ts is None or ts < cutoff:
                continue
        row = out[fam]
        row["dispatched"] += 1
        row["cost"] += cost
        row["in"] += t_in
        row["out"] += t_out
    return out, daily


#: The per-transcript memo behind `_summary`: `{path: ((size, mtime_ns), value)}`.
#: Not an optimisation for its own sake — see `_summary` for the freeze it fixes.
_SUMMARIES = {}


def _summary(f):
    """`_read_transcript(f)`, remembered until the file itself changes.

    THE READ IS NOT CHEAP AND IT IS ON A CLOCK. `snapshot()` is polled every 60s
    and kicked again on every agent lifecycle change, and `_claude_rows` re-read
    EVERY transcript on every one of those — measured on `top` 2026-08-02, 1,003
    files / 526 MB / **1,134 ms**, all of it here. That ran on the GUI thread, so
    goetia stopped dead for over a second at least once a minute, and it got
    worse as the corpus grew (`claude-state` syncs book's transcripts in too).

    A transcript is immutable except for the live ones being appended to, so
    size+mtime is a sound identity: unchanged file, unchanged numbers. In steady
    state two or three sessions are being written and the other thousand are
    answered from here. A file that shrank or vanished simply misses the key and
    is re-read from scratch — this never has to be right about WHY it changed.
    """
    try:
        st = os.stat(f)
    except OSError:
        _SUMMARIES.pop(f, None)
        return None
    key = (st.st_size, st.st_mtime_ns)
    hit = _SUMMARIES.get(f)
    if hit is not None and hit[0] == key:
        return hit[1]
    val = _read_transcript(f)
    _SUMMARIES[f] = (key, val)
    return val


def _read_transcript(f):
    """One transcript reduced to `(family, in, out, cost, last_epoch)`, or None
    when it is not a board-spawned session at all (his own coding, or one with
    no assistant turn to attribute). One file is one dispatched agent, filed
    under the family of the model that did most of its turns."""
    first_user = None
    entry = None
    models = collections.Counter()
    t_in = t_out = 0
    cost = 0.0
    last_ts = None
    try:
        fh = open(f, errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except (ValueError, TypeError):
                continue
            if entry is None and r.get("entrypoint"):
                entry = r.get("entrypoint")
            mt = r.get("timestamp")
            if mt:
                last_ts = mt
            typ = r.get("type")
            msg = r.get("message", {}) or {}
            if typ == "user" and first_user is None:
                c = msg.get("content")
                if isinstance(c, str):
                    first_user = c[:8000]
                elif isinstance(c, list):
                    for x in c:
                        if isinstance(x, dict) and x.get("type") == "text":
                            first_user = (x.get("text") or "")[:8000]
                            break
            if typ == "assistant":
                u = msg.get("usage")
                if not u:
                    continue
                model = msg.get("model")
                if model and model != "<synthetic>":
                    models[model] += 1
                fm = _fam(model)
                if fm is None:
                    continue
                fin = u.get("input_tokens", 0) or 0
                crd = u.get("cache_read_input_tokens", 0) or 0
                out_t = u.get("output_tokens", 0) or 0
                cc = u.get("cache_creation", {}) or {}
                w5 = cc.get("ephemeral_5m_input_tokens", 0) or 0
                w1 = cc.get("ephemeral_1h_input_tokens", 0) or 0
                cw = u.get("cache_creation_input_tokens", 0) or 0
                if not (w5 or w1) and cw:
                    w5 = cw
                t_in += fin + crd + w5 + w1
                t_out += out_t
                rin, rrd, rw, rout = RATES[fm]
                cost += fin * rin + crd * rrd + (w5 + w1) * rw + out_t * rout
    if _role_of(first_user) is None or not models:
        return None
    return (_fam(models.most_common(1)[0][0]) or "other",
            t_in, t_out, cost, _epoch(last_ts))


def _epoch(iso):
    """An ISO transcript timestamp as an epoch float, or None. Tolerant of the
    trailing `Z`; a value it cannot parse is None (treated as out of window)."""
    if not iso:
        return None
    try:
        import datetime
        return datetime.datetime.fromisoformat(
            iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _hermes_rows(now, window):
    """`{label: {...}}` for board (source=tool) hermes ministers, grouped by the
    session's model, or an empty dict when the ledger is unreachable. Cost is the
    provider's own `estimated_cost_usd`; tokens are the real columns. `in` folds
    the cache and reasoning read/write into the input side to mirror the Claude
    figure; `out` is the generated tokens."""
    path = boardusage._hermes_db_path()
    cutoff = None if window is None else now - window
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except (OSError, sqlite3.Error):
        return {}
    try:
        if cutoff is None:
            q = ("SELECT model, COUNT(*),"
                 " COALESCE(SUM(input_tokens),0),"
                 " COALESCE(SUM(cache_read_tokens),0),"
                 " COALESCE(SUM(cache_write_tokens),0),"
                 " COALESCE(SUM(output_tokens),0),"
                 " COALESCE(SUM(reasoning_tokens),0),"
                 " COALESCE(SUM(estimated_cost_usd),0)"
                 " FROM sessions WHERE source=? GROUP BY model")
            args = (boardusage.HERMES_SOURCE,)
        else:
            q = ("SELECT model, COUNT(*),"
                 " COALESCE(SUM(input_tokens),0),"
                 " COALESCE(SUM(cache_read_tokens),0),"
                 " COALESCE(SUM(cache_write_tokens),0),"
                 " COALESCE(SUM(output_tokens),0),"
                 " COALESCE(SUM(reasoning_tokens),0),"
                 " COALESCE(SUM(estimated_cost_usd),0)"
                 " FROM sessions WHERE source=? AND started_at>=? GROUP BY model")
            args = (boardusage.HERMES_SOURCE, cutoff)
        rows = db.execute(q, args).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            db.close()
        except sqlite3.Error:
            pass
    out = {}
    for model, n, inp, crd, cwr, outp, reason, cost in rows:
        label = _hermes_label(model)
        r = out.setdefault(
            label, {"dispatched": 0, "cost": 0.0, "in": 0, "out": 0})
        r["dispatched"] += int(n or 0)
        r["cost"] += float(cost or 0.0)
        r["in"] += int(inp or 0) + int(crd or 0) + int(cwr or 0)
        r["out"] += int(outp or 0) + int(reason or 0)
    return out


def _hermes_label(model):
    """A short family label for a hermes wire model. `deepseek/...` folds to
    `deepseek`; anything else keeps the tail after the last slash, so a stray
    title-generation model is named honestly rather than mislabelled deepseek."""
    if not model:
        return "hermes"
    m = model.lower()
    if "deepseek" in m:
        return "deepseek"
    tail = model.rsplit("/", 1)[-1]
    return tail.split(":", 1)[0] or "hermes"


def _hermes_daily(now):
    """`{day: {label: tokens}}` for board (source=tool) hermes ministers over the
    trailing `DAILY_DAYS`, bucketed by `started_at`'s local day, or an empty dict
    when the ledger is unreachable. `tokens` folds every column the aggregate's
    `in`/`out` do, so a day's chart bar equals the sum of its per-model figures."""
    path = boardusage._hermes_db_path()
    daily_cutoff = now - DAILY_DAYS * 86400
    daily = collections.defaultdict(lambda: collections.defaultdict(int))
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except (OSError, sqlite3.Error):
        return daily
    try:
        q = ("SELECT model, started_at,"
             " COALESCE(input_tokens,0)+COALESCE(cache_read_tokens,0)"
             " +COALESCE(cache_write_tokens,0)+COALESCE(output_tokens,0)"
             " +COALESCE(reasoning_tokens,0)"
             " FROM sessions WHERE source=? AND started_at>=?")
        rows = db.execute(q, (boardusage.HERMES_SOURCE, daily_cutoff)).fetchall()
    except sqlite3.Error:
        return daily
    finally:
        try:
            db.close()
        except sqlite3.Error:
            pass
    for model, started_at, toks in rows:
        if started_at is None:
            continue
        daily[_day_str(float(started_at))][_hermes_label(model)] += int(toks or 0)
    return daily


#: Which provider a family/label belongs to, for the readout's provider tag.
_PROVIDER = {
    "opus": "Claude", "sonnet": "Claude", "haiku": "Claude",
    "fable": "Claude", "deepseek": "Hermes",
}


def snapshot(now=None, window=None):
    """The whole readout the QML draws, as one plain dict:

        {
          "known": bool,          # any provider had a source to read
          "estimated": bool,      # any Claude row present -> a $ is a weight
          "window": str|None,     # human label for the span, None = all recorded
          "models": [             # one per family, COST-DESC
             {"model","provider","dispatched","cost","in","out"}, ...],
          "totals": {"dispatched","cost","in","out"},
          "daily": [              # exactly DAILY_DAYS entries, OLDEST -> NEWEST
             {"date","label","total","models":{family: tokens}}, ...],
        }

    `daily` is a dense trailing month — one entry per calendar day whether or not
    anything ran, so the chart has a bar per day (a silent day is `total` 0 and
    an empty `models`). Its per-family token figures share the ranked list's
    family keys, so hovering a day can rebind the list's bars to that day.

    `window` is a span in seconds (None = everything ever recorded, the default:
    the board automation is a week old, so all-time IS the useful view). A
    provider with no readable source contributes nothing and never a zero row."""
    now = time.time() if now is None else now
    claude, claude_daily = _claude_rows(now, window)
    hermes = _hermes_rows(now, window)
    hermes_daily = _hermes_daily(now)

    merged = {}
    for fam, r in claude.items():
        merged[fam] = dict(r)
    for label, r in hermes.items():
        d = merged.setdefault(
            label, {"dispatched": 0, "cost": 0.0, "in": 0, "out": 0})
        for k in ("dispatched", "cost", "in", "out"):
            d[k] += r[k]

    models = []
    for fam, r in merged.items():
        models.append({
            "model": fam,
            "provider": _PROVIDER.get(fam, "Hermes"),
            "dispatched": int(r["dispatched"]),
            "cost": round(float(r["cost"]), 2),
            "in": int(r["in"]),
            "out": int(r["out"]),
        })
    # Cost desc, then the canonical family order as the tie-break.
    order = {f: i for i, f in enumerate(_FAMILY_ORDER)}
    models.sort(key=lambda m: (-m["cost"], order.get(m["model"], 99), m["model"]))

    totals = {
        "dispatched": sum(m["dispatched"] for m in models),
        "cost": round(sum(m["cost"] for m in models), 2),
        "in": sum(m["in"] for m in models),
        "out": sum(m["out"] for m in models),
    }
    window_label = None
    if window is not None:
        days = window / 86400.0
        window_label = ("last %gh" % (window / 3600.0)
                        if days < 1 else "last %gd" % days)

    # A dense trailing month: merge both providers' per-day maps, then emit one
    # entry per calendar day (oldest -> newest) so the chart has a bar per day.
    day_models = collections.defaultdict(lambda: collections.defaultdict(int))
    for src in (claude_daily, hermes_daily):
        for day, fams in src.items():
            for fam, tok in fams.items():
                day_models[day][fam] += int(tok)
    today = datetime.date.fromtimestamp(now)
    daily = []
    for i in range(DAILY_DAYS - 1, -1, -1):
        d = today - datetime.timedelta(days=i)
        fams = day_models.get(d.isoformat(), {})
        daily.append({
            "date": d.isoformat(),
            "label": str(d.day),
            "total": int(sum(fams.values())),
            "models": {k: int(v) for k, v in fams.items()},
        })

    return {
        "known": bool(models),
        "estimated": any(m["provider"] == "Claude" for m in models),
        "window": window_label,
        "models": models,
        "totals": totals,
        "daily": daily,
    }


def fmt_tokens(n):
    """A token count as the short human figure the rest of goetia uses: `1.2M`,
    `48k`, or the bare number. Re-exported from `boardusage` so the readout and
    its Python have one formatter."""
    return boardusage._fmt_tokens(n)


if __name__ == "__main__":   # a quick read-only dump for a person at a shell
    print(json.dumps(snapshot(), indent=1))

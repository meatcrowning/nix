"""What the board SYSTEM spends, across every provider it dispatches to.

[his ask, 2026-08-02] a usage/spend section in goetia — its own band beside the
others — showing, across ALL the providers this board automation reaches (the
deepseek/hermes spirits AND every Claude tier haiku/sonnet/opus/fable): how
many agents were dispatched per model, what each model cost, and the total
tokens split input vs output.

**This is the board system's OWN footprint, not his interactive coding.** A
Claude session counts here only when its first prompt marks it as something the
board spawned — a summoner tick (Solomon), a dispatched spirit/worker, or a
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
- **deepseek/hermes spirits** DO keep a real ledger — Hermes' own
  `~/.hermes/state.db` — with `estimated_cost_usd` the provider itself computed
  and true input/output token columns. Board spirits run `--source tool`
  (`boardusage.HERMES_SOURCE`), so that filter is exactly this board's hermes
  spend. Here the cost is the provider's own estimate, not ours.
- **The hermes rows are BOTH hosts', not just this one's.** `~/.hermes/state.db`
  does NOT sync (unlike the transcripts, which ride the `claude-state` sync),
  so each host writes a small export of its board sessions to
  `~/nix/docs/spend.<host>.json` (quarter-hourly unit in
  `home/srvs/board-spend-export.nix`, writer at
  `apps/board/tools/hermes-spend-export.py`), and the docs sync carries it to
  the other machine. This module reads the LOCAL ledger plus every OTHER host's
  synced export (`_hermes_export_files`) and folds both through the same
  aggregation — the own export is never read, being a stale copy of the local
  ledger, and reading both would double count. The export is only as fresh as
  its write + the 5-minute docs sync, which the readout inherits without
  claiming otherwise: the figures are real, and the section never shows an age.

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


def _daily_bucket():
    """One day's accumulator, shared by both providers' daily series: tokens and
    cost per family, plus a count of distinct dispatches (one transcript / one
    hermes session = one agent) that landed on the day."""
    return {"tokens": collections.defaultdict(int),
            "cost": collections.defaultdict(float),
            "agents": 0}


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
    `window` (the ranked list's numbers). `daily` is
    `{day: {"tokens": {family: tokens}, "cost": {family: cost}, "agents": int}}`
    over the trailing `DAILY_DAYS`, independent of the aggregate cutoff — its own
    window, so the chart is always a month even when the list is all-time. The
    per-day `cost` and `agents` count feed the hover readout beside the token
    bars. Both empty when there are no transcripts to read.

    One transcript is one dispatched agent, filed under the family of the model
    that did most of its turns, and attributed to the day of its last activity.
    Tokens are the real `usage` sums; `cost` is those tokens weighted by `RATES`
    — a compute-weight, said so upstream."""
    files = glob.glob(os.path.join(CLAUDE_PROJECTS, "*", "*.jsonl"))
    out = collections.defaultdict(
        lambda: {"dispatched": 0, "cost": 0.0, "in": 0, "out": 0})
    daily = collections.defaultdict(_daily_bucket)
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
            b = daily[_day_str(ts)]
            b["tokens"][fam] += t_in + t_out
            b["cost"][fam] += cost
            b["agents"] += 1        # one transcript is one dispatched agent
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


#: Where the per-host hermes exports live. The docs checkout — the file the
#: writer mints there (`spend.<host>.json`) syncs to the other machine via the
#: docs sync, and this module reads it back beside the local ledger. Env
#: override for a harness, the same courtesy `BOARD_HERMES_DB` gives the db.
def _hermes_export_dir():
    return os.environ.get("BOARD_SPEND_EXPORT_DIR") or os.path.join(
        os.path.expanduser("~"), "nix", "docs")


def _hermes_export_files():
    """The OTHER hosts' synced spend exports, `spend.<host>.json` under
    `_hermes_export_dir()`, never this host's own — the local ledger is the
    live source for this host and its own export is a stale copy of it, so
    reading both would double count. A missing dir or an empty glob is simply
    no rows from the other host: a machine that has not deployed the writer
    yet, or one that has no hermes spirits at all, contributes nothing."""
    d = _hermes_export_dir()
    try:
        names = sorted(glob.glob(os.path.join(d, "spend.*.json")))
    except OSError:
        return []
    own = "spend.%s.json" % os.uname().nodename
    return [f for f in names if os.path.basename(f) != own]


def _hermes_export_sessions(path):
    """`[(model, started_at, input, cache_read, cache_write, output, reasoning,
    cost), ...]` from one synced export file — the same tuple shape
    `_hermes_db_sessions` yields, so both sources fold through one reducer. An
    unreadable or malformed file is `[]`, not a crash: the other host's export
    breaking must not take the whole readout with it.

    The format is the writer's contract (`tools/hermes-spend-export.py`): one
    object with `host`, `written` and `sessions`, each session carrying the
    exact columns the local query selects."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict):
        return []
    out = []
    for s in doc.get("sessions") or []:
        if not isinstance(s, dict):
            continue
        out.append((s.get("model"), s.get("started_at"),
                    s.get("input_tokens"), s.get("cache_read_tokens"),
                    s.get("cache_write_tokens"), s.get("output_tokens"),
                    s.get("reasoning_tokens"), s.get("estimated_cost_usd")))
    return out


def _hermes_db_sessions():
    """`[(model, started_at, input, cache_read, cache_write, output, reasoning,
    cost), ...]` for board (source='tool') sessions in the LOCAL ledger, or
    `[]` when the ledger is unreachable. Unwindowed — the cutoff is applied by
    the fold, exactly so the same reducer can consume the synced exports."""
    path = boardusage._hermes_db_path()
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except (OSError, sqlite3.Error):
        return []
    try:
        rows = db.execute(
            "SELECT model, started_at, input_tokens, cache_read_tokens,"
            " cache_write_tokens, output_tokens, reasoning_tokens,"
            " estimated_cost_usd FROM sessions WHERE source=?", (boardusage.HERMES_SOURCE,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        try:
            db.close()
        except sqlite3.Error:
            pass
    return [tuple(r) for r in rows]


def _hermes_fold(out, sessions, cutoff):
    """Fold raw hermes session tuples into the aggregate dict, applying `cutoff`
    (`None` = all-time) to `started_at` the same way the old SQL did: a session
    without a timestamp counts only when there is no cutoff, and a session
    before the cutoff never does. `in` folds cache and reasoning read/write
    into the input side to mirror the Claude figure; `out` is generated tokens.
    The single reducer for BOTH sources — the local ledger and every synced
    export — so a hermes row on the other host is aggregated identically to one
    here."""
    for model, started_at, inp, crd, cwr, outp, reason, cost in sessions:
        if cutoff is not None and (started_at is None or started_at < cutoff):
            continue
        label = _hermes_label(model)
        r = out.setdefault(
            label, {"dispatched": 0, "cost": 0.0, "in": 0, "out": 0})
        r["dispatched"] += 1
        r["cost"] += float(cost or 0.0)
        r["in"] += int(inp or 0) + int(crd or 0) + int(cwr or 0)
        r["out"] += int(outp or 0) + int(reason or 0)


def _hermes_rows(now, window):
    """`{label: {...}}` for board (source=tool) hermes spirits on BOTH hosts,
    grouped by the session's model, or an empty dict when neither source is
    readable. Cost is the provider's own `estimated_cost_usd`; tokens are the
    real columns, folded exactly as `_hermes_fold` documents. The local ledger
    is the live source for this host; the other host's figures ride its synced
    export, which lags its own write + the 5-minute docs sync."""
    cutoff = None if window is None else now - window
    out = {}
    _hermes_fold(out, _hermes_db_sessions(), cutoff)
    for path in _hermes_export_files():
        _hermes_fold(out, _hermes_export_sessions(path), cutoff)
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
    """`{day: {"tokens": {label: tokens}, "cost": {label: cost}, "agents": int}}`
    for board (source=tool) hermes spirits on BOTH hosts over the trailing
    `DAILY_DAYS`, bucketed by `started_at`'s local day, or an empty dict when
    neither source is readable. `tokens` folds every column the aggregate's
    `in`/`out` do, so a day's chart bar equals the sum of its per-model figures;
    `cost` is the provider's own estimate and `agents` counts the day's
    dispatches. The other host's sessions ride its synced export exactly as the
    ranked list's do."""
    daily_cutoff = now - DAILY_DAYS * 86400
    daily = collections.defaultdict(_daily_bucket)
    for sessions in [_hermes_db_sessions()] + \
            [_hermes_export_sessions(p) for p in _hermes_export_files()]:
        for model, started_at, inp, crd, cwr, outp, reason, cost in sessions:
            if started_at is None or started_at < daily_cutoff:
                continue
            toks = (int(inp or 0) + int(crd or 0) + int(cwr or 0)
                    + int(outp or 0) + int(reason or 0))
            label = _hermes_label(model)
            b = daily[_day_str(float(started_at))]
            b["tokens"][label] += toks
            b["cost"][label] += float(cost or 0.0)
            b["agents"] += 1
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
             {"date","label","total","models":{family: tokens},
              "costs":{family: cost},"cost":float,"agents":int}, ...],
        }

    `daily` is a dense trailing month — one entry per calendar day whether or not
    anything ran, so the chart has a bar per day (a silent day is `total` 0 with
    an empty `models`/`costs`, `cost` 0 and `agents` 0). Its per-family token
    figures share the ranked list's family keys, so hovering a day can rebind
    the list's bars to that day; `costs`/`cost`/`agents` are the day-scoped
    figures the hover readout draws beside those bars (each model's spend, the
    day's total spend, and how many agents ran).

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
    day_acc = collections.defaultdict(_daily_bucket)
    for src in (claude_daily, hermes_daily):
        for day, b in src.items():
            acc = day_acc[day]
            for fam, tok in b["tokens"].items():
                acc["tokens"][fam] += int(tok)
            for fam, c in b["cost"].items():
                acc["cost"][fam] += float(c)
            acc["agents"] += b["agents"]
    today = datetime.date.fromtimestamp(now)
    daily = []
    for i in range(DAILY_DAYS - 1, -1, -1):
        d = today - datetime.timedelta(days=i)
        b = day_acc.get(d.isoformat())
        toks = b["tokens"] if b else {}
        costs = b["cost"] if b else {}
        daily.append({
            "date": d.isoformat(),
            "label": str(d.day),
            "total": int(sum(toks.values())),
            "models": {k: int(v) for k, v in toks.items()},
            "costs": {k: round(float(v), 4) for k, v in costs.items()},
            "cost": round(float(sum(costs.values())), 2),
            "agents": int(b["agents"]) if b else 0,
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

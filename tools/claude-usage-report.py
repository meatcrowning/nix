#!/usr/bin/env python3
"""Stream ~/.claude/projects/*/*.jsonl and aggregate token spend by model,
token class, session and category. Read-only measurement of what is consuming
the Claude usage budget. Prints a compact aggregate only — never the transcripts.

Category is inferred from the first user prompt (the spawner's role prompt):
  orchestrator  "You are Solomon, the orchestrator"
  worker        "An orchestrator, Solomon, split up"
  decision      "He answered one decision" / "Your whole job is that ONE decision"
  interactive   entrypoint == 'cli' with no role marker
  headless?     sdk-cli with no recognised marker
Dollar rates are the public per-token API rates, used purely as a cost weight
(cache reads dominate volume but are ~10x cheaper than fresh input).
"""
import json, glob, os, sys, datetime, collections

BASE = os.path.expanduser("~/.claude/projects")

# per-token USD rates: (fresh_in, cache_read, cache_write_5m, cache_write_1h, output)
RATES = {
    "opus":   (15e-6, 1.5e-6, 18.75e-6, 30e-6, 75e-6),
    "sonnet": (3e-6,  0.3e-6, 3.75e-6,  6e-6,  15e-6),
    "haiku":  (0.8e-6,0.08e-6,1e-6,     1.6e-6,4e-6),
    "fable":  (3e-6,  0.3e-6, 3.75e-6,  6e-6,  15e-6),   # ASSUMED sonnet-tier
}
def fam(model):
    if not model: return None
    m = model.lower()
    if "opus" in m: return "opus"
    if "sonnet" in m: return "sonnet"
    if "haiku" in m: return "haiku"
    if "fable" in m: return "fable"
    return None

def parse_ts(s):
    if not s: return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    except Exception:
        return None

# window anchors (UTC), from ~/.claude.json cachedUsageUtilization: weekly resets 2026-08-02T03:00Z
WEEK_START = datetime.datetime(2026,7,26,3,0,tzinfo=datetime.timezone.utc)
WEEK_END   = datetime.datetime(2026,8,2,3,0,tzinfo=datetime.timezone.utc)
D30_START  = WEEK_END - datetime.timedelta(days=30)

def categorize(first_user, entrypoint):
    t = first_user or ""
    if "You are Solomon" in t: return "orchestrator"
    if "split up something he asked for" in t or "bound you to one piece" in t or "gave you one piece" in t: return "worker"
    if "He answered one decision" in t or "Your whole job is that ONE decision" in t: return "decision"
    if entrypoint == "cli": return "interactive"
    if entrypoint == "cli" or entrypoint is None: return "interactive"
    return "headless?"

class Sess:
    __slots__=("file","proj","model","entry","cat","turns","first_user","ts_first","ts_last","cwd","branch",
               "cls","cost","raw")
    def __init__(self):
        self.turns=0; self.first_user=None; self.ts_first=None; self.ts_last=None
        self.cls=collections.Counter(); self.cost=0.0; self.raw=collections.Counter()
        self.model=None; self.entry=None; self.cwd=None; self.branch=None

def process(f):
    s=Sess(); s.file=f
    s.proj=os.path.basename(os.path.dirname(f))
    models=collections.Counter()
    for line in open(f, errors="replace"):
        line=line.strip()
        if not line: continue
        try: r=json.loads(line)
        except Exception: continue
        if s.entry is None and r.get("entrypoint"): s.entry=r.get("entrypoint")
        if s.cwd is None and r.get("cwd"): s.cwd=r.get("cwd")
        if s.branch is None and r.get("gitBranch"): s.branch=r.get("gitBranch")
        ts=parse_ts(r.get("timestamp"))
        if ts:
            if s.ts_first is None or ts<s.ts_first: s.ts_first=ts
            if s.ts_last is None or ts>s.ts_last: s.ts_last=ts
        typ=r.get("type"); msg=r.get("message",{}) or {}
        if typ=="user" and s.first_user is None:
            c=msg.get("content")
            if isinstance(c,str): s.first_user=c[:8000]
            elif isinstance(c,list):
                for x in c:
                    if isinstance(x,dict) and x.get("type")=="text":
                        s.first_user=(x.get("text") or "")[:8000]; break
        if typ=="assistant":
            u=msg.get("usage")
            if not u: continue
            model=msg.get("model");
            if model and model!="<synthetic>": models[model]+=1
            fm=fam(model)
            if fm is None: continue
            s.turns+=1
            fin=u.get("input_tokens",0) or 0
            crd=u.get("cache_read_input_tokens",0) or 0
            out=u.get("output_tokens",0) or 0
            cc=u.get("cache_creation",{}) or {}
            w5=cc.get("ephemeral_5m_input_tokens",0) or 0
            w1=cc.get("ephemeral_1h_input_tokens",0) or 0
            cw_total=u.get("cache_creation_input_tokens",0) or 0
            if not (w5 or w1) and cw_total: w5=cw_total  # fall back: treat as 5m
            s.cls["fresh_in"]+=fin; s.cls["cache_read"]+=crd
            s.cls["cache_write"]+=(w5+w1); s.cls["output"]+=out
            rin,rrd,rw5,rw1,rout=RATES[fm]
            s.cost += fin*rin + crd*rrd + w5*rw5 + w1*rw1 + out*rout
    s.model = models.most_common(1)[0][0] if models else None
    s.cat = categorize(s.first_user, s.entry)
    return s

def in_window(s, start, end):
    t = s.ts_last or s.ts_first
    return t is not None and start <= t < end

def report(sessions, start, end, label):
    sel=[s for s in sessions if in_window(s,start,end)]
    by_model_cls=collections.defaultdict(lambda: collections.Counter())
    model_cost=collections.Counter(); cat_cost=collections.Counter(); cat_turns=collections.Counter()
    cat_sessions=collections.Counter(); total_cost=0.0
    for s in sel:
        fm=fam(s.model) or "other"
        for k,v in s.cls.items(): by_model_cls[fm][k]+=v
        model_cost[fm]+=s.cost; cat_cost[s.cat]+=s.cost; total_cost+=s.cost
        cat_turns[s.cat]+=s.turns; cat_sessions[s.cat]+=1
    return dict(label=label, n=len(sel), total_cost=total_cost, by_model_cls=by_model_cls,
                model_cost=model_cost, cat_cost=cat_cost, cat_turns=cat_turns,
                cat_sessions=cat_sessions, sessions=sel)

def main():
    files=glob.glob(os.path.join(BASE,"*","*.jsonl"))
    sessions=[process(f) for f in files]
    week=report(sessions,WEEK_START,WEEK_END,"CURRENT WEEK (2026-07-26 03:00Z .. 2026-08-02 03:00Z)")
    d30=report(sessions,D30_START,WEEK_END,"LAST 30 DAYS")
    out={}
    for tag,rep in (("week",week),("d30",d30)):
        top=sorted(rep["sessions"], key=lambda s:-s.cost)[:20]
        out[tag]=dict(
            label=rep["label"], n=rep["n"], total_cost=round(rep["total_cost"],2),
            model_cost={k:round(v,2) for k,v in rep["model_cost"].most_common()},
            by_model_cls={m:dict(c) for m,c in rep["by_model_cls"].items()},
            cat_cost={k:round(v,2) for k,v in rep["cat_cost"].most_common()},
            cat_turns=dict(rep["cat_turns"]), cat_sessions=dict(rep["cat_sessions"]),
            top=[dict(cost=round(s.cost,2), cat=s.cat, model=s.model, turns=s.turns,
                      proj=s.proj, entry=s.entry, branch=s.branch,
                      fresh_in=s.cls["fresh_in"], cache_read=s.cls["cache_read"],
                      cache_write=s.cls["cache_write"], output=s.cls["output"],
                      first=str(s.ts_first), file=os.path.basename(s.file)[:12],
                      firstuser=(s.first_user or "")[:90].replace("\n"," ")) for s in top],
        )
    print(json.dumps(out, indent=1))

if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""dl-tracker.py -- a tiny localhost webpage that shows the slskd downloader
state at a glance, so it never has to be asked for.

Everything on the page is read LIVE, every request -- nothing is hard-coded:

  * slskd itself, over its loopback API (home/prog/slskd.nix, base
    http://127.0.0.1:5030, key ~/.secrets/slskd-api-key): connection/login,
    the running vs latest version, and the live transfer list.
  * the missing-track WORK LIST -- ~/.local/share/spotify-dump/missing.tsv
    (the 3.5k tracks) diffed against soulseek-state.tsv (per-track status:
    have / queued / picked / nofind / error), so "never searched yet" is just
    the rows with no state entry.
  * the sweep feeder's health -- `systemctl --user is-active soulseek-sweep`
    and its start time; the pool it feeds is the live transfer count.
  * the one live GAP -- the sweep unit's import step fails under systemd (its
    pinned PATH lacks the player wrapper, so player-add falls back to a bare
    python3 with no mutagen). Counted straight from the unit's journal today.
    The player app's AutoScanner covers it while the player is open, so nothing
    is lost -- but the sweep import tail is dead, and the count surfaces it.
  * the two poison-row wedges -- tracks stuck "picked" by a past --dry-run
    (wanted() only retries "error", so a dry-run permanently parks those rows;
    one `soulseek-missing.py --retry` recovers them), and any zombie transfer
    parked deep in a peer's queue past the stall limit.
  * cosmetic -- how much duplicate content sits in the slskd downloads dir
    (files whose destination is already in aud/, which player-add skips).

Stdlib only (http.server + urllib), loopback-bound, one self-contained page
themed from the live wallpaper palette (~/.cache/wal/palette.inc). It is a
READ-ONLY observer: it never queues, cancels or mutates a transfer, so it can
never disturb a download he is watching. Served by slsk-tracker.service
(home/srvs/slsk-tracker.nix, top-only) at http://127.0.0.1:5040/.
"""

import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("SLSK_TRACKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("SLSK_TRACKER_PORT", "5040"))

SLSKD_BASE = "http://127.0.0.1:5030"
KEY_FILE = os.path.expanduser("~/.secrets/slskd-api-key")
DUMP_DIR = os.path.expanduser("~/.local/share/spotify-dump")
MISSING_TSV = os.path.join(DUMP_DIR, "missing.tsv")
STATE_TSV = os.path.join(DUMP_DIR, "soulseek-state.tsv")
DOWNLOAD_DIR = os.path.expanduser("~/.local/share/slskd/downloads")
PALETTE_INC = os.path.expanduser("~/.cache/wal/palette.inc")

SWEEP_UNIT = "soulseek-sweep.service"
SLSKD_UNIT = "slskd.service"

# A transfer waiting on the remote peer for an upload slot; matches
# soulseek-missing.py's STALLED_CANDIDATE_STATES.
QUEUED_STATES = ("Queued, Remotely", "Queued, Locally", "Requested")
# A transfer counts as a zombie exactly as soulseek-missing.py judges a stall:
# past QUEUE_PLACE_STALL_LIMIT in the peer's queue, or -- when the peer reports
# no position at all -- parked past the short NOPLACE bar, or otherwise sat past
# the generous daily bar with no progress.
STALL_PLACE = 1000
STALL_NOPLACE_HOURS = 8.0
STALL_HOURS = 24.0

# Palette used only if the live wallpaper palette can't be read.
FALLBACK_PALETTE = {
    "bg": "#0a0a0a", "bgAlt": "#141414", "border": "#2a2a2a",
    "accent": "#8fb8b8", "dim": "#5a7070", "text": "#8fb8b8",
    "textDim": "#6a8080", "highlight": "#1a2626", "ok": "#6fbf72",
    "warn": "#c9a95c", "crit": "#d05a5a", "info": "#5c8fb0",
}


# --------------------------------------------------------------------------
# live sources
# --------------------------------------------------------------------------

def read_key():
    try:
        with open(KEY_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def slskd_get(path, key, timeout=6):
    req = urllib.request.Request(SLSKD_BASE + path, method="GET")
    if key:
        req.add_header("X-API-Key", key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def palette():
    """The live wallpaper-derived palette. ~/.cache/wal/palette.inc is written
    by wal-set.sh alongside Theme.qml; both hold the same
    `readonly property color NAME: "#hex"` lines, so a plain regex is enough
    and there is no QML to parse."""
    pal = dict(FALLBACK_PALETTE)
    for src in (PALETTE_INC, os.path.expanduser("~/.config/quickshell/Theme.qml")):
        try:
            with open(src) as f:
                text = f.read()
        except OSError:
            continue
        found = dict(re.findall(r'property color (\w+):\s*"(#[0-9a-fA-F]+)"', text))
        if found:
            pal.update({k: v for k, v in found.items() if k in FALLBACK_PALETTE})
            return pal
    return pal


def unit_active(unit):
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", unit],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def unit_uptime(unit):
    """Seconds the unit has been active, tz-free: ActiveEnterTimestampMonotonic
    (us since boot) against /proc/uptime. 0 if not resolvable / not active."""
    try:
        out = subprocess.run(
            ["systemctl", "--user", "show", unit,
             "-p", "ActiveEnterTimestampMonotonic", "--value"],
            capture_output=True, text=True, timeout=5)
        mono_us = int((out.stdout or "0").strip() or "0")
        if mono_us <= 0:
            return 0
        with open("/proc/uptime") as f:
            boot_s = float(f.read().split()[0])
        return max(0, int(boot_s - mono_us / 1_000_000))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def import_failures_today():
    """The one live gap: how many times the sweep unit's import step failed
    today. Read straight from its own journal."""
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-u", SWEEP_UNIT, "--since", "today",
             "-o", "cat", "--no-pager"],
            capture_output=True, text=True, timeout=15)
        return sum(1 for ln in out.stdout.splitlines()
                   if "import step failed" in ln)
    except (OSError, subprocess.SubprocessError):
        return None


def downloads_dup_size():
    """Bytes sitting in the slskd downloads dir -- duplicate content whose
    destination is already in aud/ (player-add skips it forever)."""
    total = 0
    if not os.path.isdir(DOWNLOAD_DIR):
        return 0
    for root, _dirs, files in os.walk(DOWNLOAD_DIR):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def worklist():
    """missing.tsv total vs soulseek-state.tsv status counts. 'never searched'
    is total minus every row that has a state entry."""
    total = 0
    try:
        with open(MISSING_TSV) as f:
            total = max(0, sum(1 for _ in f) - 1)  # minus header
    except OSError:
        total = 0
    counts = {"have": 0, "queued": 0, "picked": 0, "nofind": 0, "error": 0}
    tracked = 0
    try:
        with open(STATE_TSV) as f:
            next(f, None)  # header
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                tracked += 1
                st = parts[2]
                counts[st] = counts.get(st, 0) + 1
    except OSError:
        pass
    never = max(0, total - tracked)
    return {"total": total, "never": never, **counts}


def _age_hours(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def transfers(key):
    """Flatten /transfers/downloads into live/completed/zombie views. Never
    mutates anything -- a read-only GET."""
    out = {"reachable": False, "in_pipe": 0, "completed": 0, "failed": 0,
           "target": 45, "states": {}, "zombies": [], "live": []}
    try:
        dl = slskd_get("/api/v0/transfers/downloads", key) or []
        out["reachable"] = True
    except (urllib.error.URLError, OSError, ValueError):
        return out
    for entry in dl:
        uname = entry.get("username", "")
        for d in entry.get("directories") or []:
            for f in d.get("files") or []:
                st = f.get("state") or ""
                out["states"][st] = out["states"].get(st, 0) + 1
                size = f.get("size", 0) or 0
                done = f.get("bytesTransferred", 0) or 0
                pct = int(done / size * 100) if size else 0
                fname = str(f.get("filename", "")).replace("\\", "/").rsplit("/", 1)[-1]
                if "Completed" in st or "Succeeded" in st:
                    if any(t in st for t in ("Rejected", "Cancelled", "TimedOut",
                                             "Errored", "Aborted")):
                        out["failed"] += 1
                    else:
                        out["completed"] += 1
                    continue
                # still in the pipe
                out["in_pipe"] += 1
                place = f.get("placeInQueue")
                age = _age_hours(f.get("enqueuedAt") or f.get("requestedAt"))
                if st not in QUEUED_STATES:
                    zombie = False
                elif place is not None and place >= STALL_PLACE:
                    zombie = True
                elif place is None:
                    zombie = age is not None and age >= STALL_NOPLACE_HOURS
                else:
                    zombie = age is not None and age >= STALL_HOURS
                row = {"user": uname, "file": fname, "state": st,
                       "pct": max(0, min(100, pct)), "place": place,
                       "age": round(age, 1) if age is not None else None}
                if zombie:
                    out["zombies"].append(row)
                else:
                    out["live"].append(row)
    out["live"].sort(key=lambda r: -r["pct"])
    return out


def gather():
    key = read_key()
    data = {"now": datetime.now().strftime("%H:%M:%S"),
            "slskd": {"reachable": False}}
    try:
        app = slskd_get("/api/v0/application", key)
        srv = app.get("server", {})
        ver = app.get("version", {})
        data["slskd"] = {
            "reachable": True,
            "state": srv.get("state", "?"),
            "loggedIn": bool(srv.get("isLoggedIn")),
            "username": (app.get("user") or {}).get("username", ""),
            "current": ver.get("current", "?"),
            "latest": ver.get("latest", ""),
            "updateAvailable": bool(ver.get("isUpdateAvailable")),
            "uptime": unit_uptime(SLSKD_UNIT),
        }
    except (urllib.error.URLError, OSError, ValueError):
        data["slskd"] = {"reachable": False, "uptime": unit_uptime(SLSKD_UNIT)}
    data["sweep"] = {"active": unit_active(SWEEP_UNIT),
                     "uptime": unit_uptime(SWEEP_UNIT)}
    data["transfers"] = transfers(key)
    data["work"] = worklist()
    data["importFails"] = import_failures_today()
    data["dupBytes"] = downloads_dup_size()
    return data


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def fmt_dur(sec):
    if not sec:
        return "-"
    h, m = divmod(sec // 60, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return "?"


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>slskd downloader</title>
<style>
:root {{
  --bg:{bg}; --bgAlt:{bgAlt}; --border:{border}; --accent:{accent};
  --dim:{dim}; --text:{text}; --textDim:{textDim}; --highlight:{highlight};
  --ok:{ok}; --warn:{warn}; --crit:{crit}; --info:{info};
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; padding:18px; background:var(--bg); color:var(--text);
  font-family:"DejaVu Sans Mono",ui-monospace,Menlo,Consolas,monospace;
  font-size:13px; line-height:1.5; letter-spacing:.02em;
}}
h1 {{ font-size:15px; font-weight:600; margin:0 0 2px; letter-spacing:.06em; text-transform:uppercase; }}
.sub {{ color:var(--textDim); font-size:11px; margin-bottom:16px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; }}
.card {{ border:1px solid var(--border); background:var(--bgAlt); padding:12px 14px; }}
.card h2 {{ font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.08em;
  color:var(--textDim); margin:0 0 10px; }}
.row {{ display:flex; justify-content:space-between; gap:10px; padding:2px 0; }}
.row .k {{ color:var(--textDim); }}
.row .v {{ color:var(--text); text-align:right; }}
.big {{ font-size:22px; font-weight:600; color:var(--accent); }}
.ok {{ color:var(--ok); }} .warn {{ color:var(--warn); }} .crit {{ color:var(--crit); }} .info {{ color:var(--info); }}
.dim {{ color:var(--dim); }}
.dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; vertical-align:middle; }}
.bar {{ height:14px; border:1px solid var(--border); background:var(--bg); display:flex; overflow:hidden; margin:6px 0 2px; }}
.bar span {{ display:block; height:100%; }}
.legend {{ display:flex; flex-wrap:wrap; gap:4px 12px; font-size:11px; margin-top:6px; }}
.legend i {{ width:8px; height:8px; display:inline-block; margin-right:4px; }}
table {{ width:100%; border-collapse:collapse; font-size:11px; }}
td {{ padding:2px 4px; border-top:1px solid var(--border); color:var(--textDim); }}
td.f {{ color:var(--text); max-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.note {{ font-size:11px; color:var(--textDim); margin-top:8px; line-height:1.45; }}
.pill {{ border:1px solid var(--border); padding:1px 6px; font-size:11px; }}
a {{ color:var(--info); }}
.wide {{ grid-column:1/-1; }}
.mini {{ font-size:11px; color:var(--dim); }}
</style></head>
<body>
<h1>slskd downloader</h1>
<div class="sub" id="stamp">loading&hellip;</div>
<div class="grid" id="root"></div>
<script>
const PAL = {palette_json};
function esc(s){{ return String(s??'').replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
function el(tag, cls, html){{ const e=document.createElement(tag); if(cls)e.className=cls; if(html!=null)e.innerHTML=html; return e; }}
function card(title){{ const c=el('div','card'); c.appendChild(el('h2',null,esc(title))); return c; }}
function row(c,k,v,cls){{ const r=el('div','row'); r.appendChild(el('span','k',esc(k))); r.appendChild(el('span','v '+(cls||''),v)); c.appendChild(r); return r; }}
function dur(s){{ if(!s)return '-'; let m=Math.floor(s/60),h=Math.floor(m/60),d=Math.floor(h/24); m%=60;h%=24; if(d)return d+'d '+h+'h'; if(h)return h+'h '+m+'m'; return m+'m'; }}
function bytes(n){{ n=Number(n||0); const u=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<4){{n/=1024;i++;}} return (i?n.toFixed(1):n)+' '+u[i]; }}

function render(d){{
  document.getElementById('stamp').textContent = 'live — refreshed '+d.now+' — reads slskd + the work list every load';
  const root=document.getElementById('root'); root.innerHTML='';
  const S=d.slskd, sw=d.sweep, T=d.transfers, W=d.work;

  // HEALTH
  let c=card('health');
  const up = S.reachable, li = S.loggedIn;
  row(c,'slskd', '<span class="dot" style="background:'+(up?PAL.ok:PAL.crit)+'"></span>'+
    (up?esc(S.state):'unreachable'), up?'ok':'crit');
  row(c,'logged in', li?('yes'+(S.username?' — '+esc(S.username):'')):'no', li?'ok':'crit');
  row(c,'slskd uptime', dur(S.uptime));
  const swa = sw.active==='active';
  row(c,'sweep feeder','<span class="dot" style="background:'+(swa?PAL.ok:PAL.crit)+'"></span>'+esc(sw.active), swa?'ok':'crit');
  row(c,'feeder uptime', dur(sw.uptime));
  root.appendChild(c);

  // POOL
  c=card('download pool');
  const pv=el('div'); pv.className='big'; pv.textContent=T.in_pipe+' / '+T.target;
  const pr=el('div','row'); pr.appendChild(el('span','k','live transfers')); const pw=el('span','v'); pw.appendChild(pv); pr.appendChild(pw); c.appendChild(pr);
  const frac=Math.min(1,T.in_pipe/(T.target||45));
  const bar=el('div','bar'); const seg=el('span'); seg.style.width=(frac*100)+'%'; seg.style.background=PAL.accent; bar.appendChild(seg); c.appendChild(bar);
  row(c,'completed (session)', T.completed, 'ok');
  row(c,'failed / rejected', T.failed, T.failed?'warn':'');
  c.appendChild(el('div','note','slskd pulls up to '+T.target+' at once; the feeder tops the pool back up whenever it drains.'));
  root.appendChild(c);

  // WORK LIST
  c=card('work list — '+W.total+' tracks');
  const segs=[['have',W.have,PAL.ok],['queued',W.queued,PAL.accent],['nofind',W.nofind,PAL.dim],
    ['error',W.error,PAL.crit],['picked',W.picked,PAL.warn],['never searched',W.never,PAL.border]];
  const wbar=el('div','bar');
  segs.forEach(([,n,col])=>{{ if(n>0){{ const s=el('span'); s.style.width=(100*n/(W.total||1))+'%'; s.style.background=col; s.title=n; wbar.appendChild(s); }} }});
  c.appendChild(wbar);
  const lg=el('div','legend');
  segs.forEach(([lab,n,col])=>{{ const s=el('span'); s.innerHTML='<i style="background:'+col+'"></i>'+lab+' '+n; lg.appendChild(s); }});
  c.appendChild(lg);
  c.appendChild(el('div','note','landed '+W.have+', terminal no-source '+W.nofind+
    '. the watch loop drains the '+W.never+' never-searched on its own.'));
  root.appendChild(c);

  // WEDGE: import gap
  c=card('import gap (live)');
  const iff=d.importFails;
  row(c,'sweep import fails today', iff==null?'?':iff, iff?'warn':'ok');
  c.appendChild(el('div','note','the sweep unit\\'s import step has no mutagen on its pinned PATH, so it '+
    'fails under systemd. the player app\\'s AutoScanner imports completed downloads while the '+
    'player is open, so nothing is lost — but the sweep\\'s own import tail is dead.'));
  root.appendChild(c);

  // WEDGE: picked / poisoned rows
  c=card('stuck "picked" rows');
  row(c,'poisoned by a past --dry-run', W.picked, W.picked?'warn':'ok');
  if(W.picked>0) c.appendChild(el('div','note','wanted() only retries "error", so a dry-run parks these permanently. '+
    'one `soulseek-missing.py --retry` recovers them.'));
  else c.appendChild(el('div','note','none parked.'));
  root.appendChild(c);

  // COSMETIC dup size + version
  c=card('housekeeping');
  row(c,'downloads dir (duplicates)', bytes(d.dupBytes), 'dim');
  row(c,'slskd version', esc(S.current||'?'));
  if(S.updateAvailable) row(c,'update available', esc(S.latest)+' (his call)', 'info');
  else row(c,'up to date', 'yes', 'ok');
  root.appendChild(c);

  // ZOMBIES
  const c2=card('zombie transfers');
  c2.className='card wide';
  if(T.zombies.length===0){{ c2.appendChild(el('div','mini','none past the stall limit.')); }}
  else {{
    const tbl=el('table');
    T.zombies.forEach(z=>{{
      const tr=el('tr');
      tr.appendChild(el('td','f',esc(z.file)));
      tr.appendChild(el('td',null,esc(z.user)));
      tr.appendChild(el('td',null,esc(z.state)));
      tr.appendChild(el('td',null, z.place!=null?('place '+z.place):''));
      tr.appendChild(el('td',null, z.age!=null?(z.age+'h'):''));
      tbl.appendChild(tr);
    }});
    c2.appendChild(tbl);
    c2.appendChild(el('div','note','parked deep in a peer\\'s queue past the stall bar — ~1 pool slot each, cosmetic. the watch loop re-sources them.'));
  }}
  root.appendChild(c2);
}}

async function tick(){{
  try {{ const r=await fetch('api',{{cache:'no-store'}}); render(await r.json()); }}
  catch(e){{ document.getElementById('stamp').textContent='cannot reach the tracker server'; }}
}}
tick(); setInterval(tick, 10000);
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # journald already stamps; no per-request noise

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("", "/index.html"):
            pal = palette()
            page = PAGE.format(palette_json=json.dumps(pal), **pal)
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif path == "/api":
            try:
                body = json.dumps(gather()).encode()
            except Exception as e:  # never 500 the page over one bad source
                body = json.dumps({"error": str(e)}).encode()
            self._send(200, body, "application/json")
        else:
            self._send(404, b"not found", "text/plain")


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"slsk dl-tracker on http://{HOST}:{PORT}/  (pid {os.getpid()})",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    sys.exit(main())

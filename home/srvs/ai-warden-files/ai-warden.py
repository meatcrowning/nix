#!/usr/bin/env python3
"""ai-warden — admission control for the two local AI backends.

THE PROBLEM. `top` has 31 GiB of RAM and 12 GiB of VRAM, and two things that
each want most of it: **ollama** (chatter, `apps/oracle`) and **ComfyUI**
(painter, `apps/painter`). Measured 2026-08-22 with nothing unusual running,
ollama alone held **24.7 GiB** for one `qwen3.6:35b-a3b`. Starting a painter
video render on top of that does not fail — it LIVELOCKS the machine, because a
box thrashing against swap never quite fails an allocation, so the kernel OOM
killer stays asleep while nothing gets scheduled and the compositor stops
drawing (the reasoning in full: `sys/oomd.nix`).

THE SHAPE OF THE FIX. Reacting to pressure is too late: the spike IS the load,
and by the time `MemAvailable` has fallen the pages are already committed. So
this is **admission control** — painter and chatter ask BEFORE they load or
queue anything, and the warden either makes room or says no:

    painter: queue a batch  -> POST /reserve {backend: comfy, bytes: N}
                               ollama holds 24.7G, would not fit
                               -> free ollama's weights, toast, ok
                            -> POST /prompt

    chatter: send a turn    -> POST /reserve {backend: ollama, model: M}
                               comfy is RENDERING -> refuse, with the reason
                            -> the refusal is drawn in chatter; the box lives

A passive watchdog runs behind that as the net, for the memory this cannot see
coming (an agent's `nix build`, a browser, cte).

THE THREE RULES, from him (2026-08-22):

  1. **Free, never stop.** Unloading weights is cheap and reloadable — ollama
     takes a zero `keep_alive`, ComfyUI takes `POST /free` — and both daemons
     stay up. Stopping a unit costs a cold start; the warden never does it.
     (`tools/heavy-gate.sh` may, for a rebuild, because he answers a toast.)
  2. **Never interrupt work in flight.** If the other backend is busy, the
     answer is a refusal with a reason, not a cut render or a killed reply.
  3. **Act on its own judgement, and say so.** Freeing is silent-until-done
     plus a normal toast naming what went (docs/DESIGN.md §10 — no silent
     change). No question; a toast per turn would be intolerable.

WHY THE CGROUP AND NOT `/api/ps`. ollama's `/api/ps` is the obvious reading and
it is NOT trustworthy for this: measured 2026-08-22, it returned
`{"models":[]}` while `llama-server` already held 14.4 GiB RSS and 10.7 GiB of
VRAM — i.e. it is blind for the whole duration of a model load, which is
precisely the window a freeze happens in. `memory.current` on the unit's cgroup
was correct throughout. So every footprint here is `max(what the API claims,
what the cgroup measures)`, and the cgroup is the one that decides.

RAM IS THE GATE; VRAM IS ONLY A REASON TO TIDY. A VRAM shortfall does not
freeze anything — ollama partially offloads to CPU and ComfyUI errors the job —
so running out of VRAM makes the warden free the other backend but NEVER refuse.
Only RAM can refuse, because only RAM can take the desktop with it.

FAIL-OPEN, ALWAYS. A warden that is down, wedged or switched off must never be
the reason he cannot work: the clients treat any error or timeout as "go", and
the kill switch below makes every reserve an immediate yes.

  Kill switch : ~/.local/state/ai-warden/off
  Log         : ~/.cache/ai-warden.log
  Endpoint    : http://127.0.0.1:8199   (loopback only, no auth, no LAN)

`top` only — it is the machine with the backends on it. On book the clients get
no answer and fail open, which is the correct behaviour there.

CLI:  ai-warden status | reserve <comfy|ollama> [--model M] [--bytes N]
                       | done <backend> | free <backend> | serve
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from glob import glob
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

GiB = 1024 ** 3

PORT = int(os.environ.get("AI_WARDEN_PORT", "8199"))
COMFY = os.environ.get("AI_WARDEN_COMFY_URL", "http://127.0.0.1:8188")
OLLAMA = os.environ.get("AI_WARDEN_OLLAMA_URL", "http://127.0.0.1:11434")

#: How much RAM the desktop keeps for itself, whatever the backends want. A
#: reserve that would leave less than this is refused; the watchdog fires below
#: CRIT_FLOOR. 6 GiB is Plasma/Hyprland + a browser + kitty + an agent, measured
#: rather than guessed — `free -m` with the session idle sits near 3.8 GiB.
RAM_FLOOR = int(float(os.environ.get("AI_WARDEN_RAM_FLOOR_GB", "6")) * GiB)
CRIT_FLOOR = int(float(os.environ.get("AI_WARDEN_CRIT_FLOOR_GB", "4")) * GiB)
#: The floor a REFUSAL is measured against, and deliberately far below
#: RAM_FLOOR. The two floors answer different questions. RAM_FLOOR is comfort —
#: "should I tidy up before this runs" — and it is right to be generous with it,
#: because the tidying is free. A refusal is not free: it is chatter telling him
#: no. So refusing waits until the request genuinely cannot fit at all.
#: Concretely, his own `qwen3.6:35b-a3b` is 23.9 GiB on a 31 GiB machine, and
#: measuring its refusal against a 6 GiB floor would have banned his main model
#: outright. (It fits in practice because ollama mmaps the gguf and the kernel
#: evicts what it is not using — which is also why the cgroup figure runs high.)
HARD_FLOOR = int(float(os.environ.get("AI_WARDEN_HARD_FLOOR_GB", "2.5")) * GiB)
#: PSI `some avg10` over this means the machine is ALREADY in the thrash the
#: freeze comes out of, whatever MemAvailable claims. sys/oomd.nix explains at
#: length why pressure, not free bytes, is the honest signal.
PSI_TRIP = float(os.environ.get("AI_WARDEN_PSI_TRIP", "20"))
VRAM_FLOOR = int(float(os.environ.get("AI_WARDEN_VRAM_FLOOR_GB", "0.7")) * GiB)

#: A weights figure is never the whole cost — a runner adds KV cache, a CUDA
#: context, python, and comfy adds the working tensors of whatever it is
#: sampling. These are the fudge factors, deliberately generous: over-estimating
#: costs an unnecessary unload, under-estimating costs the machine.
OLLAMA_OVERHEAD = 1.10
OLLAMA_FIXED = int(1.5 * GiB)
COMFY_OVERHEAD = 1.25
COMFY_FIXED = int(2 * GiB)
COMFY_DEFAULT = int(14 * GiB)      # no hint from painter: assume a big family

#: How long a reserve marks its backend busy without a `/done`. chatter releases
#: on reply end so its lease is only a crash backstop; painter's is short
#: because comfy's own queue takes over as the busy signal the moment it submits.
LEASE_DEFAULT = {"ollama": 900, "comfy": 120}

STATE_DIR = Path.home() / ".local" / "state" / "ai-warden"
OFF = STATE_DIR / "off"
LOG = Path.home() / ".cache" / "ai-warden.log"

BACKENDS = ("ollama", "comfy")
NICE = {"ollama": "chatter", "comfy": "painter"}


def log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    sys.stderr.write(line)
    sys.stderr.flush()
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 4 * 1024 * 1024:
            tail = LOG.read_text(errors="replace").splitlines()[-2000:]
            LOG.write_text("\n".join(tail) + "\n")
        with LOG.open("a") as f:
            f.write(line)
    except OSError:
        pass


def gb(n):
    return "%.1fG" % (n / GiB)


def notify(summary, body, urgency="normal"):
    """LOWERCASE, TERSE, NO EXPLAINING. Every string this desktop authors is
    lowercase (docs/DESIGN.md §7.2), and his correction on the first draft of
    these was that they read AI-written: a summary that is the fact
    (`unloaded chatter (24.0G)`) and a body that is the reason in four words
    (`painter needed the room`). No "it reloads its weights next time you use
    it" — he knows. Same voice for the refusals below."""
    if os.environ.get("AI_WARDEN_NO_NOTIFY") == "1":
        log("notify (suppressed): %s — %s" % (summary, body))
        return
    try:
        # `--` before the positionals: notify-send parses a leading dash in the
        # summary or body as an option and exits 1 with nothing shown.
        subprocess.run(["notify-send", "-a", "ai-warden", "-u", urgency,
                        "--", summary, body],
                       timeout=5, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


# ---------------------------------------------------------------------------
# reading the machine
# ---------------------------------------------------------------------------

def _get(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _post(url, payload, timeout=15):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def mem_available():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def psi_some_avg10():
    try:
        for line in Path("/proc/pressure/memory").read_text().splitlines():
            if line.startswith("some "):
                for tok in line.split():
                    if tok.startswith("avg10="):
                        return float(tok.split("=", 1)[1])
    except (OSError, ValueError):
        pass
    return 0.0


def cgroup_bytes(path):
    """`memory.current` for a unit's cgroup, or 0. This is the honest footprint:
    it counts the runner children ollama forks, and it is correct DURING a load,
    which `/api/ps` is not (see the module docstring)."""
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return 0


def ollama_cgroup():
    return cgroup_bytes("/sys/fs/cgroup/system.slice/ollama.service/memory.current")


def comfy_cgroup():
    # A home-manager user unit lands under user@<uid>.service, in app.slice on
    # some systemd versions and directly under it on others — glob rather than
    # hardcode, and take whichever exists.
    uid = os.getuid()
    for p in glob("/sys/fs/cgroup/user.slice/user-%d.slice/user@%d.service/"
                  "**/comfy-painter.service/memory.current" % (uid, uid),
                  recursive=True):
        return cgroup_bytes(p)
    return 0


def vram():
    """(free, total) bytes on the display GPU, or (0, 0) with no nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        f, t = out[0].split(",")
        return int(f) * 1024 * 1024, int(t) * 1024 * 1024
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0, 0


def gpu_util():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        return int(out[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return -1


def unit_active(unit, user=False):
    cmd = ["systemctl"] + (["--user"] if user else []) + ["is-active", "--quiet", unit]
    try:
        return subprocess.run(cmd, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ollama_ps():
    doc = _get(OLLAMA + "/api/ps") or {}
    return doc.get("models") or []


def ollama_tag_size(name):
    """Bytes on disk for a model name, from the daemon's own catalogue. Matches
    `qwen3.6:35b-a3b` and a bare `qwen3.6` alike, longest name first so a
    prefix cannot shadow the exact tag."""
    doc = _get(OLLAMA + "/api/tags") or {}
    models = doc.get("models") or []
    for m in sorted(models, key=lambda m: -len(m.get("name", ""))):
        n = m.get("name", "")
        if n == name or n.split(":")[0] == name or name.startswith(n):
            return int(m.get("size") or 0)
    return 0


def comfy_queue():
    """Jobs running plus queued, or None when comfy answers nothing. A backend
    that is merely still starting has nothing in flight to protect, so None is
    read as `not busy` — the same rule tools/heavy-gate.sh uses."""
    doc = _get(COMFY + "/prompt")
    if not isinstance(doc, dict):
        return None
    q = doc.get("exec_info", {}).get("queue_remaining", doc.get("queue_remaining"))
    try:
        return int(q)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# the warden
# ---------------------------------------------------------------------------

class Warden:
    def __init__(self):
        self.lock = threading.RLock()
        self.leases = {}          # backend -> unix ts the lease expires
        self.last_free = {}       # backend -> unix ts we last freed it
        self.last_watchdog = 0.0

    # -- state ------------------------------------------------------------

    def footprint(self, backend):
        """RAM bytes the backend is holding, by the most pessimistic reading we
        have. `max` on purpose: the API under-reports during a load and the
        cgroup over-reports page cache, and over-reporting is the safe error."""
        if backend == "ollama":
            api = sum(int(m.get("size") or 0) for m in ollama_ps())
            return max(api, ollama_cgroup())
        return comfy_cgroup()

    def busy(self, backend):
        """(bool, why). Work in flight is never interrupted, so this is the one
        reading that can turn a reserve into a refusal."""
        with self.lock:
            until = self.leases.get(backend, 0)
        if until > time.time():
            return True, "%s is mid-reply" % NICE[backend]
        if backend == "comfy":
            q = comfy_queue()
            if q:
                return True, "painter is rendering (%d in the queue)" % q
            return False, ""
        # ollama has no "am I generating" endpoint at all. A resident model
        # under sustained GPU load is the only hint there is, and it is
        # advisory — say so in the reason rather than claiming certainty.
        if ollama_ps() and gpu_util() >= 40:
            return True, "chatter looks busy (gpu %d%%)" % gpu_util()
        return False, ""

    def snapshot(self):
        vf, vt = vram()
        snap = {
            "mem_available": mem_available(),
            "psi_some_avg10": psi_some_avg10(),
            "vram_free": vf, "vram_total": vt, "gpu_util": gpu_util(),
            "ram_floor": RAM_FLOOR, "crit_floor": CRIT_FLOOR,
            "off": OFF.exists(),
            "backends": {},
        }
        for b in BACKENDS:
            up = unit_active("ollama.service") if b == "ollama" \
                else unit_active("comfy-painter.service", user=True)
            bsy, why = self.busy(b)
            with self.lock:
                lease = max(0, int(self.leases.get(b, 0) - time.time()))
            snap["backends"][b] = {
                "app": NICE[b], "up": up, "held": self.footprint(b),
                "busy": bsy, "busy_why": why, "lease_s": lease,
            }
        return snap

    # -- estimating -------------------------------------------------------

    def estimate(self, backend, model="", hint=0):
        """(need, hard) RAM bytes this request wants, ON TOP of what the backend
        already holds.

        TWO NUMBERS, because one cannot do both jobs without lying in one
        direction or the other:

          need  the generous figure — weights plus a runner, a CUDA context and
                whatever the sampler allocates. It decides whether to FREE the
                other backend. Over-estimating here costs an unnecessary unload,
                which is cheap.
          hard  the floor — the weights themselves and nothing optimistic. It is
                the ONLY number allowed to produce a refusal. Estimating `need`
                and refusing on it would turn "painter wants a big model on an
                empty machine" into a no, which is the warden being the problem
                instead of the fix.

        Already-resident work costs nothing either way: re-sending to the model
        that is loaded, or re-queueing at a comfy already warm with the same
        weights, needs no room made for it."""
        held = self.footprint(backend)
        if backend == "ollama":
            if model:
                for m in ollama_ps():
                    if m.get("name") == model or m.get("model") == model:
                        return 0, 0     # already loaded — this turn is free
            raw = int(hint) if hint else ollama_tag_size(model)
            if not raw:
                raw = int(6 * GiB)      # unknown model: assume a middling one
            want = int(raw * OLLAMA_OVERHEAD + OLLAMA_FIXED)
            # Swapping model A for model B frees A first (OLLAMA_NUM_PARALLEL
            # and OLLAMA_MAX_LOADED_MODELS are both 1), so only the difference
            # is genuinely new.
            return max(0, want - held), max(0, raw - held)
        raw = int(hint) if hint else int(COMFY_DEFAULT / COMFY_OVERHEAD)
        want = int(raw * COMFY_OVERHEAD + COMFY_FIXED)
        # A comfy already holding at least this much has the weights it needs or
        # will swap them internally; charge only the sampling headroom.
        if held >= want * 0.8:
            return int(2 * GiB), int(1 * GiB)
        return max(0, want - held), max(0, raw + GiB - held)

    # -- freeing ----------------------------------------------------------

    def free(self, backend, wait=25):
        """Drop a backend's weights, leaving the daemon up. Returns bytes
        released, measured rather than assumed."""
        before = self.footprint(backend)
        if backend == "ollama":
            for m in ollama_ps():
                name = m.get("name") or m.get("model")
                if name:
                    _post(OLLAMA + "/api/generate", {"model": name, "keep_alive": 0})
        else:
            _post(COMFY + "/free", {"unload_models": True, "free_memory": True})
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(1)
            now = self.footprint(backend)
            if now <= max(before * 0.4, 2 * GiB):
                break
        with self.lock:
            self.last_free[backend] = time.time()
        released = max(0, before - self.footprint(backend))
        log("freed %s: %s -> %s (released %s)"
            % (backend, gb(before), gb(self.footprint(backend)), gb(released)))
        return released

    # -- the answer -------------------------------------------------------

    def reserve(self, backend, model="", hint=0, lease=None):
        if backend not in BACKENDS:
            return {"ok": True, "reason": "unknown backend %r — not gated" % backend,
                    "freed": []}
        if OFF.exists():
            return {"ok": True, "reason": "warden is off", "freed": []}

        other = "comfy" if backend == "ollama" else "ollama"
        need, hard = self.estimate(backend, model, hint)
        avail = mem_available()
        vf, vt = vram()
        freed = []

        ram_ok = need == 0 or (avail - need) >= RAM_FLOOR
        # VRAM is tidiness, never a veto: a shortfall degrades a job, it does
        # not livelock the box (module docstring).
        vram_ok = vt == 0 or need == 0 or (vf - min(need, vt)) >= VRAM_FLOOR

        # When painter wants to start on top of a WARM, IDLE ollama, free it
        # up front even if nominal free RAM looks OK. On top's 31 GiB a 15 GiB
        # comfy load alongside ollama's ~18 GiB model nearly always thrashes the
        # box into a livelock before avail ever dips below the floor, and by
        # then it is too late to react (2026-08-22: comfy loaded beside warm
        # ollama, avail crashed to 2G, he stopped ollama by hand). A free is
        # cheap and reloadable (keep_alive=0, daemon stays up); a late one costs
        # a manual stop. This never interrupts chatter — busy() guards below.
        #
        # This runs for comfy reserves only (chatter's own swap is handled by
        # estimate()). We mark ollama as already-freed here so the existing free
        # path below does not free it a second time.
        freed_other = False
        held = self.footprint(other)
        if backend == "comfy" and held >= 1 * GiB and ram_ok:
            bsy, _ = self.busy(other)
            if not bsy:
                released = self.free(other)
                if released:
                    freed.append(other)
                    freed_other = True
                    notify("unloaded %s (%s)" % (NICE[other], gb(released)),
                           "%s needed the room" % NICE[backend])
                avail = mem_available()
                ram_ok = need == 0 or (avail - need) >= RAM_FLOOR

        if ram_ok and vram_ok:
            self._take_lease(backend, lease)
            return {"ok": True, "reason": "", "freed": freed,
                    "need": need, "available": avail}

        held = self.footprint(other)
        if held < 1 * GiB:
            # Nothing of ours to give back. Refuse only if RAM is the problem —
            # a VRAM squeeze still goes ahead.
            if ram_ok:
                self._take_lease(backend, lease)
                return {"ok": True, "reason": "", "freed": freed, "need": need,
                        "available": avail}
            if (avail - hard) >= HARD_FLOOR:
                self._take_lease(backend, lease)
                return {"ok": True, "reason": "", "freed": freed, "need": need,
                        "available": avail}
            return self._refuse(
                "not enough memory: needs %s, %s free, nothing to unload"
                % (gb(hard), gb(avail)), need, avail, freed)

        bsy, why = self.busy(other)
        if bsy:
            if ram_ok:
                self._take_lease(backend, lease)
                return {"ok": True, "reason": "", "freed": freed, "need": need,
                        "available": avail}
            if (avail - hard) >= HARD_FLOOR:
                self._take_lease(backend, lease)
                return {"ok": True, "reason": "", "freed": freed, "need": need,
                        "available": avail}
            return self._refuse(
                "%s, %s stuck under it" % (why, gb(held)), need, avail, freed)

        released = self.free(other)
        if released and not freed_other:
            freed.append(other)
            notify("unloaded %s (%s)" % (NICE[other], gb(released)),
                   "%s needed the room" % NICE[backend])
        avail = mem_available()
        # Refuse on `hard`, never on `need` — see estimate(). Everything of ours
        # has already been given back at this point, so a shortfall here means
        # something outside the two backends is holding the machine.
        if hard and (avail - hard) < HARD_FLOOR:
            return self._refuse(
                "still short after unloading %s: needs %s, %s free"
                % (NICE[other], gb(hard), gb(avail)), need, avail, freed)
        self._take_lease(backend, lease)
        return {"ok": True, "reason": "", "freed": freed, "need": need,
                "available": avail}

    def _refuse(self, reason, need, avail, freed=None):
        log("REFUSED: " + reason)
        return {"ok": False, "reason": reason, "freed": freed or [],
                "need": need, "available": avail}

    def _take_lease(self, backend, lease=None):
        secs = LEASE_DEFAULT.get(backend, 300) if lease is None else int(lease)
        if secs > 0:
            with self.lock:
                self.leases[backend] = time.time() + secs

    def done(self, backend):
        with self.lock:
            self.leases.pop(backend, None)
        return {"ok": True}

    # -- the net behind it ------------------------------------------------

    def watchdog(self):
        """For the memory admission control cannot see coming — an agent's nix
        build, a browser, cte. Frees the idle backend when the machine is
        already in trouble; never touches a busy one."""
        if OFF.exists():
            return
        avail, psi = mem_available(), psi_some_avg10()
        if avail >= CRIT_FLOOR and psi < PSI_TRIP:
            return
        if time.time() - self.last_watchdog < 120:
            return
        cands = []
        for b in BACKENDS:
            held = self.footprint(b)
            if held < 1 * GiB:
                continue
            bsy, _ = self.busy(b)
            if bsy:
                continue
            cands.append((held, b))
        if not cands:
            log("watchdog: pressure (avail=%s psi=%.1f) but nothing idle to free"
                % (gb(avail), psi))
            self.last_watchdog = time.time()
            return
        cands.sort(reverse=True)
        held, b = cands[0]
        log("watchdog: avail=%s psi=%.1f — freeing idle %s (%s)"
            % (gb(avail), psi, b, gb(held)))
        self.last_watchdog = time.time()
        released = self.free(b)
        if released:
            notify("unloaded %s (%s)" % (NICE[b], gb(released)),
                   "only %s was left" % gb(avail))


WARDEN = Warden()


def watchdog_loop():
    while True:
        try:
            WARDEN.watchdog()
        except Exception as exc:              # a net must not die of its own bug
            log("watchdog error: %r" % (exc,))
        time.sleep(10)


# ---------------------------------------------------------------------------
# the endpoint
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                 # not into the journal, per request
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/status", ""):
            self._send(WARDEN.snapshot())
        else:
            self._send({"error": "no such path"}, 404)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            doc = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (ValueError, OSError):
            doc = {}
        path = self.path.rstrip("/")
        backend = str(doc.get("backend") or "")
        if path == "/reserve":
            self._send(WARDEN.reserve(backend, str(doc.get("model") or ""),
                                      int(doc.get("bytes") or 0),
                                      doc.get("lease")))
        elif path == "/done":
            self._send(WARDEN.done(backend))
        elif path == "/free":
            self._send({"ok": True, "released": WARDEN.free(backend)})
        else:
            self._send({"error": "no such path"}, 404)


def serve():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=watchdog_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    log("ai-warden listening on 127.0.0.1:%d (ram floor %s, crit %s)"
        % (PORT, gb(RAM_FLOOR), gb(CRIT_FLOOR)))
    srv.serve_forever()


def cli(argv):
    if not argv or argv[0] == "serve":
        serve()
        return 0
    cmd = argv[0]
    if cmd == "status":
        s = WARDEN.snapshot()
        print("available %s   psi(some,10s) %.1f   vram %s/%s   gpu %d%%%s"
              % (gb(s["mem_available"]), s["psi_some_avg10"],
                 gb(s["vram_free"]), gb(s["vram_total"]), s["gpu_util"],
                 "   WARDEN OFF" if s["off"] else ""))
        for b, d in s["backends"].items():
            print("  %-7s (%-7s) %-4s held %-7s %s%s"
                  % (b, d["app"], "up" if d["up"] else "down", gb(d["held"]),
                     "BUSY: " + d["busy_why"] if d["busy"] else "idle",
                     "  lease %ds" % d["lease_s"] if d["lease_s"] else ""))
        return 0
    args = {"backend": argv[1] if len(argv) > 1 else ""}
    rest = argv[2:]
    while rest:
        if rest[0] == "--model" and len(rest) > 1:
            args["model"] = rest[1]; rest = rest[2:]
        elif rest[0] == "--bytes" and len(rest) > 1:
            args["bytes"] = int(rest[1]); rest = rest[2:]
        else:
            rest = rest[1:]
    if cmd == "reserve":
        r = WARDEN.reserve(args["backend"], args.get("model", ""),
                           args.get("bytes", 0))
        print(json.dumps(r, indent=2))
        return 0 if r["ok"] else 1
    if cmd == "done":
        print(json.dumps(WARDEN.done(args["backend"])))
        return 0
    if cmd == "free":
        print("released %s" % gb(WARDEN.free(args["backend"])))
        return 0
    sys.stderr.write(__doc__.split("CLI:")[-1].strip() + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))

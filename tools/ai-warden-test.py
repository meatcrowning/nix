#!/usr/bin/env python3
"""Harness for `home/srvs/ai-warden-files/ai-warden.py`.

Every reading the warden makes — meminfo, PSI, the two cgroups, nvidia-smi,
ollama's two endpoints, comfy's queue — is stubbed here, so the whole decision
table can be driven without a model, a render or a machine under pressure.
Nothing in this file touches the live backends, raises a toast, or listens on a
port (AGENTS.md, "Testing without interfering with the user").

Re-run it after touching the estimator, the floors, or the free/refuse
branches: those are the parts that decide whether he loses a reply or loses the
machine, and neither failure is visible until it happens.

    python3 tools/ai-warden-test.py
"""
import os
import sys
from pathlib import Path

os.environ["AI_WARDEN_NO_NOTIFY"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "home" / "srvs" / "ai-warden-files"))

import importlib.util

# The module's filename has a dash in it, so it cannot simply be imported.
_SRC = (Path(__file__).resolve().parent.parent / "home" / "srvs"
        / "ai-warden-files" / "ai-warden.py")
_spec = importlib.util.spec_from_file_location("aiwarden", _SRC)
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

GiB = W.GiB
FAILS = []


class World:
    """One made-up machine. The warden reads it through the stubs below."""

    def __init__(self, avail_gb=28, psi=0.0, ollama_gb=0.0, comfy_gb=0.0,
                 comfy_queue=0, gpu=0, ollama_models=None, tags=None,
                 vram_free_gb=11.0, working=False):
        self.avail = int(avail_gb * GiB)
        self.psi = psi
        self.ollama = int(ollama_gb * GiB)
        self.comfy = int(comfy_gb * GiB)
        self.queue = comfy_queue
        self.gpu = gpu
        self.models = ollama_models or []
        self.tags = tags or {}
        self.vram_free = int(vram_free_gb * GiB)
        self.working = working
        self.freed = []

    def install(self):
        W.mem_available = lambda: self.avail
        W.psi_some_avg10 = lambda: self.psi
        W.ollama_cgroup = lambda: self.ollama
        W.comfy_cgroup = lambda: self.comfy
        W.comfy_queue = lambda: self.queue
        W.gpu_util = lambda: self.gpu
        # ollama's OWN cpu clock, not the device's GPU number — see busy().
        W.ollama_working = lambda *a, **k: self.working
        W.vram = lambda: (self.vram_free, int(12 * GiB))
        W.unit_active = lambda *a, **k: True
        W.ollama_ps = lambda: [
            {"name": n, "model": n, "size": int(s * GiB)}
            for n, s in self.models]
        W.ollama_tag_size = lambda name: int(self.tags.get(name, 0) * GiB)
        W.notify = lambda *a, **k: None

        def fake_free(backend, wait=0):
            held = self.ollama if backend == "ollama" else self.comfy
            self.freed.append(backend)
            if backend == "ollama":
                self.ollama, self.models = 0, []
            else:
                self.comfy = 0
            self.avail += held          # the memory really does come back
            return held

        self.warden = W.Warden()
        self.warden.free = fake_free
        return self.warden


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


print("estimate: two numbers, not one")
w = World(tags={"big:35b": 23.0}).install()
need, hard = w.estimate("ollama", "big:35b")
check("need is generous", need > 23 * GiB, "need=%s" % W.gb(need))
# `hard` is what will sit in RAM: the file, minus what free VRAM can hold, plus
# the runtime. 23G of weights with 11G of VRAM free is ~13G of RAM, not 23.
check("hard discounts what the GPU will hold",
      int(12.5 * GiB) < hard < int(14 * GiB), "hard=%s" % W.gb(hard))
w = World(tags={"big:35b": 23.0}, vram_free_gb=0.2).install()
check("...and charges the whole file when the GPU is full",
      w.estimate("ollama", "big:35b")[1] >= int(23 * GiB),
      "hard=%s" % W.gb(w.estimate("ollama", "big:35b")[1]))

print("a model that fits, on a machine painter is not using")
# HIS case, 2026-08-23: painter shut for hours (its daemon up but holding only
# its own 1.1G baseline, so freeing it releases nothing), 24.4G available, a
# 22.2G model — refused for being 0.3G short of `raw + HARD_FLOOR`, which is a
# bill it should never have been sent.
w = World(avail_gb=24.4, comfy_gb=1.1, tags={"his:35b": 22.2},
          vram_free_gb=10.8).install()
r = w.reserve("ollama", "his:35b")
check("his own model is not refused for a painter that holds nothing",
      r["ok"], r["reason"])
check("hard < need", hard < need)

print("\na resident model costs nothing to talk to again")
w = World(ollama_gb=23, ollama_models=[("big:35b", 23.0)],
          tags={"big:35b": 23.0}).install()
check("need is zero", w.estimate("ollama", "big:35b") == (0, 0))
r = w.reserve("ollama", "big:35b")
check("reserve says go", r["ok"] and not r["freed"])

print("\nan empty machine never needs anything freed")
world = World(avail_gb=28)
w = world.install()
r = w.reserve("comfy", hint=int(12 * GiB))
check("comfy goes ahead", r["ok"], r.get("reason", ""))
check("nothing was freed", world.freed == [], str(world.freed))

print("\nan empty ollama cgroup cache is pressure, not loaded weights")
world = World(avail_gb=28, ollama_gb=3, ollama_models=[])
w = world.install()
r = w.reserve("comfy", hint=int(12 * GiB))
check("painter does not unload an empty ollama", world.freed == [], str(world.freed))
check("the snapshot still counts its reclaimable file cache",
      w.footprint("ollama") == int(3 * GiB), W.gb(w.footprint("ollama")))
check("but no weights are attributed to it", w.reclaimable("ollama") == 0)

# Exercise the real free loop, not World's decision-table replacement. An
# empty /api/ps must return without even one sleep; with a model, /api/ps going
# empty ends the wait although the cgroup's inactive file cache remains 3G.
posts, sleeps = [], []
old_post, old_sleep, old_log = W._post, W.time.sleep, W.log
try:
    W.log = lambda *_a, **_k: None
    W._post = lambda *_a, **_k: posts.append((_a, _k))
    W.time.sleep = lambda seconds: sleeps.append(seconds)
    real = W.Warden()
    check("freeing an empty ollama returns immediately",
          real.free("ollama") == 0 and posts == [] and sleeps == [],
          (posts, sleeps))

    world.models = [("mid:12b", 9.0)]

    def unload(url, body):
        posts.append((url, body))
        world.models = []

    W._post = unload
    check("a real model unload ends when /api/ps is empty",
          real.free("ollama") == int(9 * GiB) and len(sleeps) == 1,
          (posts, sleeps))
finally:
    W._post, W.time.sleep, W.log = old_post, old_sleep, old_log

print("\nHIS CASE: chatter holds 24G, painter wants a 12G model")
world = World(avail_gb=6, ollama_gb=24, ollama_models=[("big:35b", 24.0)],
              tags={"big:35b": 24.0})
w = world.install()
r = w.reserve("comfy", hint=int(12 * GiB))
check("ollama was freed", world.freed == ["ollama"], str(world.freed))
check("painter goes ahead", r["ok"], r.get("reason", ""))
check("the answer names what went", r["freed"] == ["ollama"])

print("\nNEW: RAM looks OK but ollama is warm — free it anyway, don't wait")
world = World(avail_gb=20, ollama_gb=18, ollama_models=[("mid:20b", 18.0)],
              tags={"mid:20b": 18.0})
w = world.install()
r = w.reserve("comfy", hint=int(12 * GiB))
check("ollama was freed up front", world.freed == ["ollama"], str(world.freed))
check("painter goes ahead", r["ok"], r.get("reason", ""))
check("the answer names it", r["freed"] == ["ollama"])

print("\nthe reverse: painter is warm and idle, chatter wants a big model")
world = World(avail_gb=8, comfy_gb=16, tags={"mid:20b": 14.0})
w = world.install()
r = w.reserve("ollama", "mid:20b")
check("comfy was freed", world.freed == ["comfy"], str(world.freed))
check("chatter goes ahead", r["ok"], r.get("reason", ""))

print("\nwork in flight is never cut")
world = World(avail_gb=6, comfy_gb=16, comfy_queue=2, tags={"big:35b": 23.0})
w = world.install()
r = w.reserve("ollama", "big:35b")
check("nothing was freed", world.freed == [], str(world.freed))
check("refused", not r["ok"])
check("the reason names the render", "rendering" in r["reason"], r["reason"])

print("\na lease is work in flight too, and /done ends it")
world = World(avail_gb=6, ollama_gb=24, ollama_models=[("big:35b", 24.0)],
              tags={"big:35b": 24.0})
w = world.install()
w.leases["ollama"] = W.time.time() + 300
r = w.reserve("comfy", hint=int(12 * GiB))
check("refused under a lease", not r["ok"], str(r))
check("nothing was freed", world.freed == [], str(world.freed))
w.done("ollama")
r = w.reserve("comfy", hint=int(12 * GiB))
check("goes ahead once the lease is released", r["ok"], r.get("reason", ""))
check("and it freed ollama to do it", world.freed == ["ollama"])

print("\nrefusal is on `hard`, so a big ask on an EMPTY machine is not refused")
world = World(avail_gb=27, ollama_gb=0)
w = world.install()
r = w.reserve("comfy", hint=int(19 * GiB))     # need ~26G, hard ~20G
check("goes ahead", r["ok"], r.get("reason", ""))

print("\nHIS BIGGEST MODEL still fits once painter has given its memory back")
# 23.9G of weights on a 31G box: refused against RAM_FLOOR, allowed against
# HARD_FLOOR — which is the whole reason the two floors are separate.
world = World(avail_gb=5, comfy_gb=23, tags={"qwen3.6:35b-a3b": 23.9})
w = world.install()
r = w.reserve("ollama", "qwen3.6:35b-a3b")
check("goes ahead", r["ok"], r.get("reason", ""))
check("after freeing painter", world.freed == ["comfy"], str(world.freed))

print("\nsomething else is holding the machine: refuse, and say so")
world = World(avail_gb=2, ollama_gb=0, comfy_gb=0, tags={"big:35b": 23.0})
w = world.install()
r = w.reserve("ollama", "big:35b")
check("refused", not r["ok"])
check("names that there is nothing to give back",
      "nothing" in r["reason"], r["reason"])

print("\nVRAM alone never refuses — it only tidies")
world = World(avail_gb=28, vram_free_gb=0.2, comfy_gb=8)
w = world.install()
r = w.reserve("ollama", "small:3b", )
check("goes ahead despite no VRAM", r["ok"], r.get("reason", ""))
check("but comfy was freed to make room", world.freed == ["comfy"],
      str(world.freed))

print("\na full GPU is a reason to free, even when RAM is fine")
# 2026-08-25: llama-server held 9.7 GiB of an 11.5 GiB card, RAM was fine, comfy
# was admitted on RAM alone and the render died 0.74s later on
# `Free (according to CUDA): 9.62 MiB`. GPU load made ollama read as busy — and
# a busy GUESS was protecting the very thing standing in the render's way.
world = World(avail_gb=26, ollama_gb=9, vram_free_gb=0.1, gpu=70,
              ollama_models=[("big:12b", 9.0)], tags={"big:12b": 9.0})
w = world.install()
r = w.reserve("comfy", hint=int(9 * GiB))
check("admitted", r["ok"], r.get("reason", ""))
check("...and the gpu was cleared for it", world.freed == ["ollama"],
      str(world.freed))
check("a busy DEVICE is not a busy ollama — one gpu, two tenants",
      not w.busy("ollama")[0], str(w.busy("ollama")))

print("\n...a working ollama is waited out, not cut")
world = World(avail_gb=26, ollama_gb=9, vram_free_gb=0.1, working=True,
              ollama_models=[("big:12b", 9.0)], tags={"big:12b": 9.0})
w = world.install()
W.IDLE_WAIT = 0                                # do not really sit for 20s
r = w.reserve("comfy", hint=int(9 * GiB))
check("its own cpu clock is what says busy", w.busy("ollama")[0],
      str(w.busy("ollama")))
check("admitted anyway — VRAM never refuses", r["ok"], r.get("reason", ""))
check("...and a reply in flight keeps its weights", world.freed == [],
      str(world.freed))

print("\n...but a LEASE is still work in flight, whatever the GPU says")
world = World(avail_gb=26, ollama_gb=9, vram_free_gb=0.1, working=True,
              ollama_models=[("big:12b", 9.0)], tags={"big:12b": 9.0})
w = world.install()
W.IDLE_WAIT = 0
w.leases["ollama"] = W.time.time() + 300
r = w.reserve("comfy", hint=int(9 * GiB))
check("still admitted — VRAM never refuses", r["ok"], r.get("reason", ""))
check("...and nothing was taken from a live lease", world.freed == [],
      str(world.freed))
check("`leased` is the hard half of busy — a claim, not an inference",
      w.leased("ollama"))

print("\nthe kill switch makes every reserve an immediate yes")
world = World(avail_gb=1, ollama_gb=24, comfy_queue=3)
w = world.install()
W.OFF = Path("/proc/self/exe")                 # a path that certainly exists
try:
    r = w.reserve("comfy", hint=int(20 * GiB))
    check("ok", r["ok"] and r["reason"] == "warden is off", str(r))
    check("nothing freed", world.freed == [])
finally:
    W.OFF = W.STATE_DIR / "off"

print("\nthe watchdog frees the biggest IDLE backend under pressure")
world = World(avail_gb=2, ollama_gb=20, comfy_gb=6,
              ollama_models=[("big:20b", 20.0)])
w = world.install()
w.watchdog()
check("freed ollama", world.freed == ["ollama"], str(world.freed))

print("\n...and never a genuinely generating one")
# A busy ollama is protected only while it is actually emitting tokens (gpu
# >= 40). Here ollama is mid-reply AND generating, comfy is rendering: the
# watchdog must freeze nobody out.
world = World(avail_gb=2, ollama_gb=20, comfy_gb=6, comfy_queue=1, gpu=80)
w = world.install()
w.leases["ollama"] = W.time.time() + 300
w.watchdog()
check("froze nobody out", world.freed == [], str(world.freed))

print("\n...but a busy-but-LOADING ollama under pressure IS freed")
# A lease held with the GPU not yet generating is a model mid-load: a reload
# is cheap and re-runnable where a freeze is not, so the watchdog frees it.
world = World(avail_gb=2, ollama_gb=20, comfy_gb=6, comfy_queue=1,
              ollama_models=[("big:20b", 20.0)])
w = world.install()
w.leases["ollama"] = W.time.time() + 300
w.watchdog()
check("freed the loading ollama", world.freed == ["ollama"], str(world.freed))

print("\nPSI trips the watchdog even with bytes apparently free")
world = World(avail_gb=20, psi=45.0, ollama_gb=18,
              ollama_models=[("mid:18b", 18.0)])
w = world.install()
w.watchdog()
check("freed on pressure alone", world.freed == ["ollama"], str(world.freed))

print("\na long render keeps its lease alive by saying so, and only that way")
world = World(avail_gb=6, comfy_gb=20)
w = world.install()
check("renewing what is not held takes nothing",
      not w.renew("comfy")["ok"] and "comfy" not in w.leases, str(w.leases))
w.leases["comfy"] = W.time.time() + 10
check("a held lease is pushed out", w.renew("comfy", 300)["ok"]
      and w.leases["comfy"] - W.time.time() > 200, str(w.leases))
# The whole point: a heartbeat must not re-run ADMISSION. A re-reserve every
# couple of minutes decides all over again whether to free the other side —
# unloading it, and toasting that it did, once per beat — and can refuse, which
# would let the lease lapse under a render in flight.
world = World(avail_gb=6, ollama_gb=24, comfy_gb=20,
              ollama_models=[("big:35b", 24.0)], tags={"big:35b": 24.0})
w = world.install()
w.leases["comfy"] = W.time.time() + 10
check("a heartbeat frees nothing", w.renew("comfy", 300)["ok"]
      and world.freed == [], str(world.freed))
w.reserve("comfy", hint=int(14 * GiB))
check("...where a re-reserve would have unloaded the other side",
      world.freed == ["ollama"], str(world.freed))
check("an unknown backend cannot be renewed", not w.renew("nope")["ok"])

print("\nan unknown backend is not gated at all")
w = World().install()
check("passes through", w.reserve("something-else")["ok"])

print()
if FAILS:
    print("FAILED: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("all good")

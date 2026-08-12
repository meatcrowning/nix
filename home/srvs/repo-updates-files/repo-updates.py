#!/usr/bin/env python3
"""repo-updates — "the other machine pushed; want it?", as a toast you can act on.

`~/nix` is the one thing on this desktop that does NOT sync itself. `docs/` and
`~/.claude` are on 5-minute timers (nix-docs.nix, claude-state.nix), but the
flake is a git repo both machines push to and neither pulls, so a change landed
on one host sat there until he remembered to `git pull` and rebuild on the
other. That is the whole job here: notice, say what it will cost, and — if he
clicks — pull, rebuild and reload without him typing anything.

WHAT IT WATCHES: `origin/main` of ~/nix only. Nothing else in this repo needs
it; docs and claude-state have their own syncs, and this deliberately does not
touch them.

WHEN IT LOOKS
  * at session start — the unit is started from hyprland.lua, so that covers
    both a boot and a plain login;
  * on resume from suspend, detected WITHOUT D-Bus: CLOCK_MONOTONIC stops while
    the machine is asleep and CLOCK_BOOTTIME does not, so a tick where boottime
    ran further ahead than monotonic IS a resume. That needs no system-bus
    match rule (book has home-manager only and cannot install one), no
    privileges, and nothing to keep alive but this loop;
  * every PEEK_SEC (60s) it PEEKS: one `git ls-remote` round trip, no object
    transfer, no local writes. The full survey — fetch, diff, flake.lock
    comparison — only runs when that sha is one we have not already looked at.
    This is what makes the toast prompt: the poll below used to be the only
    thing that noticed a push, so a commit landed on the other machine could sit
    unmentioned for the better part of half an hour;
  * every POLL_MIN minutes regardless, as the backstop for a peek that has been
    failing quietly (no network, no credentials, a remote that moved).

WHAT IT SAYS. The toast carries the commit count, the first couple of subjects
and a COST line, because "there are updates" is useless if applying them means a
seven-minute compile. The cost is read off the diff: which flake inputs moved
(the compositor pin is the expensive one — book has no aarch64 cache for
Hyprland and builds it from source), whether the plugin's own source changed,
whether anything under home/ or sys/ needs a switch at all, or whether it is
only `apps/` live source that a rebuild would not touch in the first place.

An estimate off a path list is a guess, so the honest number is taken at APPLY
time instead — off the build's OWN plan ("these 37 derivations will be built"),
which nix prints before it starts. That used to be a separate
`nix build --dry-run` pass ahead of the rebuild; it cost a whole extra
evaluation (minutes on book) during which the toast sat on the previous step
saying nothing, and the rebuild then printed the same numbers anyway.

WHAT IT LOOKS LIKE WHILE IT WORKS. One toast, from the click to the last word,
morphing in place: never expiring (`-t 0`), naming the step it is on, and
carrying a **progress bar** — the `value` hint, which the panel's
NotificationCard draws (docs/DESIGN.md §8.1's bar). The bar is that STEP's own
fraction, and the body says which step of how many, because those are two
different denominators and §10.5 says so. Where a step can be measured it is:
git's own "Receiving objects: N%" for the pull, and built+fetched store paths
counted against the plan for the rebuild. Where it cannot — the evaluation
before nix prints a plan — the bar eases toward 90% of the step on elapsed time
and never claims to be finished, exactly as player's systheme toast does across
its render.

WHAT IT DOES NOT DO. It never applies anything on its own. It never stashes,
resets or checks out — if the tree has work in it that blocks a fast-forward,
that is reported and the pull is abandoned. And a dismissed update stays
dismissed until a NEWER commit arrives (the fetched sha is the dedupe key), so
this cannot nag.

THE BUTTONS are freedesktop notification actions, drawn by the panel's
NotificationCard. That rendering is gated on the `notifActions` setting, so when
it is off this sends a plain toast that names `nix-pull` instead — a toast whose
buttons the server was told not to draw would be a dead end.

TESTING — everything is overridable, so the classifier, the dedupe and the apply
can be exercised without touching his session or his repo:

    REPO_UPDATES_REPO     checkout to watch     (default ~/nix)
    REPO_UPDATES_STATE    state dir             (default ~/.local/state/repo-updates)
    REPO_UPDATES_LOG      log file              (default ~/.cache/repo-updates.log)
    REPO_UPDATES_NOTIFY   command instead of notify-send ('' = log only)
    REPO_UPDATES_POLL_MIN backstop poll minutes (default 30)
    REPO_UPDATES_PEEK_SEC ls-remote peek seconds (default 60; 0 = off)
    REPO_UPDATES_NO_FETCH 1 = never touch the network (compare what is there)
    REPO_UPDATES_NO_APPLY 1 = print the apply plan, run nothing
    REPO_UPDATES_NO_RELOAD 1 = never bump Theme.qml or hyprctl reload
    REPO_UPDATES_REBUILD_CMD  run this instead of the host's rebuild wrapper
    REPO_UPDATES_HOST     pretend to be this host ("top" / "book")
    REPO_UPDATES_SETTINGS panel settings.json   (default ~/.config/quickshell/settings.json)

Subcommands: `--daemon` (default), `--check` (classify and print, exit 10 when
behind), `--apply` (pull + rebuild + reload; what `nix-pull` runs), `--demo`
(raise the toast with its buttons, wired to nothing — for HIM to run when he
wants to see it, since nothing here may put a notification on his screen to
check its own work).
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

HOME = Path.home()
REPO = Path(os.environ.get("REPO_UPDATES_REPO", HOME / "nix"))
STATE = Path(os.environ.get("REPO_UPDATES_STATE", HOME / ".local/state/repo-updates"))
LOG = Path(os.environ.get("REPO_UPDATES_LOG", HOME / ".cache/repo-updates.log"))
SETTINGS = Path(os.environ.get("REPO_UPDATES_SETTINGS",
                               HOME / ".config/quickshell/settings.json"))
POLL_MIN = int(os.environ.get("REPO_UPDATES_POLL_MIN", "30"))
PEEK_SEC = int(os.environ.get("REPO_UPDATES_PEEK_SEC", "60"))
NO_FETCH = os.environ.get("REPO_UPDATES_NO_FETCH") == "1"
NO_APPLY = os.environ.get("REPO_UPDATES_NO_APPLY") == "1"
# The harness points the rebuild at `true` and switches the reloads off: a test
# that ran the real switch, bumped his live Theme.qml or reloaded his compositor
# would be reaching straight into the session it is supposed to stay out of.
REBUILD_CMD = os.environ.get("REPO_UPDATES_REBUILD_CMD", "")
NO_RELOAD = os.environ.get("REPO_UPDATES_NO_RELOAD") == "1"
BRANCH = os.environ.get("REPO_UPDATES_BRANCH", "main")

# A suspend shows up as boottime outrunning monotonic. Anything under this is
# ordinary scheduling jitter, not a sleep.
RESUME_GAP_SEC = 30
TICK_SEC = 60
# How soon to look again when a check found commits but could not put a toast on
# screen (no notification server yet — a boot races the panel).
RETRY_SEC = 120

# Cross-call state the loop reads: `retry` is set by a pass that found something
# to say and had nowhere to say it.
FLAGS = {"retry": False}


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 262144:
            tail = LOG.read_bytes()[-131072:]
            LOG.write_bytes(tail)
        with LOG.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    if not sys.stdout.isatty():
        return
    print(line, flush=True)


def host():
    """`top` or `book` — the OS hostname, never the flake attribute.

    Every runtime writer here has only the hostname (the flake calls the laptop
    `air` and the machine calls itself `book`), so this is the one that can be
    read at runtime, exactly as boardparse.board_path() does it.
    """
    forced = os.environ.get("REPO_UPDATES_HOST")
    if forced:
        return forced
    return (socket.gethostname() or "").split(".")[0]


def git(*args, timeout=60, cwd=None):
    """Run git in the watched checkout. Returns (rc, stdout, stderr), never raises."""
    try:
        p = subprocess.run(["git", "-C", str(cwd or REPO)] + list(args),
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


# ---------------------------------------------------------------------------
# what is waiting, and what it will cost
# ---------------------------------------------------------------------------

def locked_revs(ref):
    """flake.lock input -> locked rev, at `ref`. {} when it cannot be read."""
    rc, out, _ = git("show", f"{ref}:flake.lock")
    if rc != 0:
        return {}
    try:
        nodes = json.loads(out).get("nodes", {})
    except ValueError:
        return {}
    revs = {}
    for name, node in nodes.items():
        locked = node.get("locked") or {}
        rev = locked.get("rev") or locked.get("narHash")
        if rev:
            revs[name] = rev
    return revs


def classify(files, moved_inputs, hostname):
    """What applying these changes actually costs.

    Returns a dict: `needs_rebuild`, `needs_relog` (a live plugin hot-swap is
    impossible across a compositor bump), `reload` (what to run afterwards) and
    `cost` (the one line the toast shows).
    """
    nixish = [f for f in files if f.endswith(".nix") or f == "flake.lock"
              or f == "flake.nix"]
    panel = [f for f in files if f.startswith("home/prog/quickshell-files/")]
    hypr_lua = [f for f in files if f.startswith("home/prog/hypr-files/")]
    plugin = [f for f in files if f.startswith("home/prog/hyprvtb/")]
    seeded = [f for f in files
              if f.startswith("home/") or f.startswith("sys/") or f.startswith("hosts/")]
    apps_only = files and all(f.startswith("apps/") for f in files)

    compositor = [i for i in moved_inputs if i in ("hyprland", "hyprland-air")]
    laptop = hostname == "book"

    needs_rebuild = bool(nixish or seeded)
    needs_relog = bool(compositor)

    reload_steps = []
    if panel:
        reload_steps.append("panel")
    if hypr_lua or (plugin and not compositor):
        reload_steps.append("hyprctl")

    if compositor:
        if laptop:
            cost = ("compositor pin moved — Hyprland builds from source here "
                    "(no aarch64 cache, ~7 min); plugin lands at next login")
        else:
            cost = "compositor pin moved — the plugin lands at next login, not live"
    elif "nixpkgs" in moved_inputs:
        cost = "nixpkgs moved — expect a large download, possibly builds"
    elif plugin:
        cost = "plugin rebuild, hot-swapped live"
    elif needs_rebuild:
        cost = "a rebuild"
    elif apps_only:
        cost = "no rebuild — app live source, relaunch to pick it up"
    else:
        cost = "no rebuild needed"

    return {
        "needs_rebuild": needs_rebuild,
        "needs_relog": needs_relog,
        "reload": reload_steps,
        "cost": cost,
        "compositor": bool(compositor),
        "moved_inputs": sorted(moved_inputs),
    }


def peek():
    """The sha `origin/BRANCH` points at, for one round trip and no local writes.

    ls-remote asks the remote for its refs and stops there: no objects come
    down, no ref is updated, nothing in .git changes. Cheap enough to run every
    minute, which is the point — the full survey below fetches, and fetching
    every minute forever to notice a push every few days is not a trade worth
    making. Returns None on any failure (offline, no credentials, no remote):
    the caller treats that as "no news", and the POLL_MIN backstop still runs.
    """
    rc, out, _ = git("ls-remote", "--exit-code", "origin",
                     f"refs/heads/{BRANCH}", timeout=25)
    if rc != 0 or not out:
        return None
    sha = out.split()[0]
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None


def head_sha():
    rc, out, _ = git("rev-parse", "HEAD")
    return out if rc == 0 else ""


def survey(fetch=True):
    """Fetch and describe what `origin/BRANCH` has that we do not.

    `behind` 0 means nothing to do. `ahead` is reported too: local commits that
    were never pushed are the one case where a fast-forward cannot happen, and
    saying so beats a pull that fails.
    """
    if fetch and not NO_FETCH:
        rc, _, err = git("fetch", "--quiet", "origin", BRANCH, timeout=90)
        if rc != 0:
            return {"ok": False, "why": f"fetch failed: {err.splitlines()[-1] if err else rc}"}

    rc, sha, _ = git("rev-parse", f"origin/{BRANCH}")
    if rc != 0:
        return {"ok": False, "why": "no origin/%s" % BRANCH}

    _, counts, _ = git("rev-list", "--left-right", "--count",
                       f"HEAD...origin/{BRANCH}")
    try:
        ahead, behind = (int(x) for x in counts.split())
    except ValueError:
        ahead = behind = 0

    _, names, _ = git("diff", "--name-only", f"HEAD...origin/{BRANCH}")
    files = [f for f in names.split("\n") if f]
    _, subjects, _ = git("log", "--format=%s", "--reverse",
                         f"HEAD..origin/{BRANCH}")
    subjects = [s for s in subjects.split("\n") if s]

    moved = set()
    if "flake.lock" in files:
        before, after = locked_revs("HEAD"), locked_revs(f"origin/{BRANCH}")
        moved = {k for k in after if before.get(k) != after[k]}

    out = {"ok": True, "sha": sha, "ahead": ahead, "behind": behind,
           "files": files, "subjects": subjects}
    out.update(classify(files, moved, host()))
    return out


# ---------------------------------------------------------------------------
# the toast
# ---------------------------------------------------------------------------

def actions_drawn():
    """Does the panel draw notification action buttons right now?

    NotificationCard gates them on the same `notifActions` setting the server
    advertises capability from, so a toast that ships buttons while it is off
    would be a toast he cannot act on. Unreadable settings: assume yes — the
    default on a fresh profile is what the panel ships, and a missing file means
    no panel to draw anything anyway.
    """
    try:
        return bool(json.loads(SETTINGS.read_text()).get("notifActions", False))
    except (OSError, ValueError):
        return False


def notify(summary, body, actions=(), replace_id=0, wait=False, urgency="normal",
           expire="0", value=None):
    """Raise (or replace) the toast. Returns (id, action_key).

    `action_key` is only ever set when `wait` is on — notify-send -w blocks
    until the toast closes and prints the invoked action, which is how a click
    on a panel button gets back to this process. With -p it prints the id first,
    so the two arrive as two lines in order.
    """
    override = os.environ.get("REPO_UPDATES_NOTIFY")
    if override == "":
        keys = " ".join(k for k, _ in actions)
        # One log line per toast, so a multi-line body (every progress step has
        # one) stays greppable as the single event it is.
        log(f"notify (dry): {summary} | " + body.replace("\n", " / ")
            + (f" | {value}%" if value is not None else "")
            + (f" | actions: {keys}" if keys else ""))
        return 0, None
    cmd = (override.split() if override else ["notify-send"])
    # -i repo-updates: the Gaap seal (home/prog/app-icons/repo-updates.svg,
    # installed into hicolor by repo-updates.nix). The panel's NotificationCard
    # resolves the name and tints the currentColor sigil to the header colour.
    cmd += ["-a", "nix", "-i", "repo-updates", "-u", urgency, "-t", str(expire), "-p"]
    if replace_id:
        cmd += ["-r", str(replace_id)]
    # The de-facto progress hint: an int 0-100 that KDE, dunst and our own
    # NotificationCard all read as "draw a bar this full". A toast without it
    # draws no bar at all, which is every toast that is not this one applying.
    if value is not None:
        cmd += ["-h", "int:value:%d" % max(0, min(100, int(value)))]
    for key, label in actions:
        cmd += [f"--action={key}={label}"]
    if wait:
        cmd += ["-w"]
    # `--` OR NOTHING IS EVER SHOWN. The body's first line is a commit subject
    # bullet, "- curate: ...", and notify-send parses its argv with GOption:
    # a positional that starts with a dash is read as a flag, so it died with
    # "Unknown option - curate: ..." and exit 1, printing no id. That is
    # indistinguishable here from a boot racing the panel, so every pass since
    # this shipped logged "no notification server answered" and retried forever
    # against a server that was up and listening.
    cmd += ["--", summary, body]

    try:
        if not wait:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            first = (p.stdout or "").strip().split("\n")[0]
            return (int(first) if first.isdigit() else 0), None
        # Waiting: the id lands immediately, the action whenever he clicks.
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        nid = 0
        line = p.stdout.readline().strip()
        if line.isdigit():
            nid = int(line)
        return nid, p
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log(f"notify failed: {e}")
        return 0, None


def toast_text(s):
    """The summary/body a survey deserves. Body is capped: the card draws 4 lines."""
    n = s["behind"]
    summary = f"{n} commit{'s' if n != 1 else ''} waiting in ~/nix"
    lines = []
    for subj in s["subjects"][-2:]:
        lines.append("- " + (subj[:38] + "..." if len(subj) > 41 else subj))
    lines.append(s["cost"])
    if s["ahead"]:
        lines.append(f"({s['ahead']} local commit(s) unpushed — pull will not fast-forward)")
    return summary, "\n".join(lines)


# ---------------------------------------------------------------------------
# applying it
# ---------------------------------------------------------------------------

def _stream_lines(fd):
    """Yield output lines as they arrive, split on \\r as well as \\n.

    A buffered read(n) would block until n bytes exist, which for a build that
    prints one line a second means the progress toast learns about it a minute
    late. os.read returns whatever the pipe has. The \\r matters for git, which
    redraws "Receiving objects:  42%" in place and never sends a newline until
    it is done.
    """
    buf = ""
    while True:
        try:
            chunk = os.read(fd, 8192)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk.decode("utf-8", "replace")
        parts = re.split(r"[\r\n]", buf)
        buf = parts.pop()
        for part in parts:
            if part.strip():
                yield part.rstrip()
    if buf.strip():
        yield buf.rstrip()


def run(cmd, timeout=3600, env=None, on_line=None):
    """Run a command, tee its tail into the log, return (rc, tail).

    Streamed rather than collected, so `on_line` can drive the progress bar
    while the command is still running — a rebuild is the longest thing this
    program does and reading its output only after it finished is precisely the
    silence the toast exists to end.
    """
    log("run: " + " ".join(cmd))
    if NO_APPLY:
        return 0, "(REPO_UPDATES_NO_APPLY)"
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=env, cwd=str(REPO))
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  failed to start: {e}")
        return 1, str(e)
    tail = deque(maxlen=40)
    killer = threading.Timer(timeout, p.kill)
    killer.start()
    try:
        for line in _stream_lines(p.stdout.fileno()):
            tail.append(line)
            if on_line:
                try:
                    on_line(line)
                except Exception as e:      # a progress bar may never kill a build
                    log(f"  (progress: {e})")
        p.wait()
    finally:
        killer.cancel()
        try:
            p.stdout.close()
        except OSError:
            pass
    for line in tail:
        log("  | " + line)
    return p.returncode, "\n".join(list(tail)[-6:])


# ---------------------------------------------------------------------------
# the progress toast
# ---------------------------------------------------------------------------

# What a build tells us about itself. nix prints its plan before it starts
# ("these 12 derivations will be built:" / "these 40 paths will be fetched"),
# then one line per store path it builds or substitutes — which is a real,
# countable denominator and numerator, not an estimate.
RE_PLAN_BUILD = re.compile(r"these? (\d+) derivations? will be built")
RE_PLAN_FETCH = re.compile(r"these? (\d+) paths? will be fetched")
RE_BUILDING = re.compile(r"^building '/nix/store/[a-z0-9]+-(.+?)(?:\.drv)?'")
RE_COPYING = re.compile(r"^copying path '/nix/store/[a-z0-9]+-(.+?)'")
RE_GIT_PCT = re.compile(r"(Receiving objects|Resolving deltas):\s+(\d+)%")


class Progress:
    """ONE toast, from the click to the last word, morphing in place.

    docs/DESIGN.md §10.4: a status toast for an ongoing operation stays on
    screen until it finishes and is replaced in place — it does not re-fire. So
    this is raised the instant the button is clicked (before the fetch, which is
    itself a wait worth showing) and every update after that is a --replace-id
    on the same notification id, at `-t 0` so nothing expires it underneath us.

    The bar is the CURRENT STEP's fraction and the body says which step of how
    many: §10.5 — two percentages on one screen must not share a `%` sign
    without sharing a denominator, and these two do not.

    A step that cannot be measured (an evaluation, before nix has a plan to
    print) CREEPS: the bar eases toward 90% of the step on elapsed time and
    stops there. It is honest about being unfinished, and it moves, which is the
    whole difference between "working" and "hung".
    """

    TICK = 1.5          # how often the creep and any pending change is drawn
    CREEP_CEIL = 0.9

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.nid = 0
        self.steps = [("check", "checking what is waiting")]
        self.i = 0
        self.frac = 0.0
        self.detail = ""
        self._creep_from = None
        self._creep_half = 30.0
        self._lock = threading.RLock()
        self._last = None
        self._stop = threading.Event()
        self._thread = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        self._draw(force=True)
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(self.TICK):
            self._draw()

    def finish(self, ok, summary, body):
        """The terminal toast, in the same slot. Never silent — §7.2."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.TICK * 2)
        if not self.enabled:
            return
        notify(summary, body, replace_id=self.nid,
               urgency="normal" if ok else "critical",
               # Success expires like any other toast; a failure is urgency 2,
               # which the card keeps up until he clicks it.
               expire="-1" if ok else "0",
               value=100 if ok else None)

    # -- what it is doing --------------------------------------------------
    def plan(self, steps):
        """Fix the step list once the survey says which steps there are."""
        with self._lock:
            self.steps = list(steps)
            self.i = 0

    def step(self, key, detail="", creep=None):
        with self._lock:
            for n, (k, _) in enumerate(self.steps):
                if k == key:
                    self.i = n
                    break
            self.frac = 0.0
            self.detail = detail
            self._creep_from = time.monotonic() if creep else None
            self._creep_half = float(creep or 30.0)
            label = self.steps[self.i][1]
        log("STEP: " + label + (f" · {detail}" if detail else ""))
        self._draw(force=True)

    def set(self, frac=None, detail=None, stop_creep=True):
        with self._lock:
            if frac is not None:
                self.frac = max(0.0, min(1.0, frac))
                if stop_creep:
                    self._creep_from = None
            if detail is not None:
                self.detail = detail
        self._draw()

    # -- drawing -----------------------------------------------------------
    def _state(self):
        with self._lock:
            label = self.steps[self.i][1]
            frac = self.frac
            if self._creep_from is not None:
                e = time.monotonic() - self._creep_from
                frac = max(frac, self.CREEP_CEIL * e / (e + self._creep_half))
            return self.i, len(self.steps), label, self.detail, \
                int(round(100 * max(0.0, min(1.0, frac))))

    def _draw(self, force=False):
        i, n, label, detail, pct = self._state()
        key = (i, label, detail, pct)
        if not force and key == self._last:
            return
        self._last = key
        if not self.enabled:
            return
        body = label + (" · " + detail if detail else "")
        if n > 1:
            body += f"\nstep {i + 1} of {n}"
        nid, _ = notify("applying ~/nix", body, replace_id=self.nid, value=pct)
        if nid:
            self.nid = nid


def reload_panel():
    """Force Quickshell's hot reload after a switch.

    The documented bump: append a comment to the LIVE Theme.qml and take it
    straight back off. That file is runtime-mutable and reconciled from the nix
    source on every switch, so this touches nothing the next rebuild will not
    rewrite anyway — and it is a bump, not an edit.
    """
    theme = HOME / ".config/quickshell/Theme.qml"
    if NO_RELOAD or not theme.exists():
        return
    if NO_APPLY:
        log("would bump Theme.qml")
        return
    try:
        original = theme.read_text()
        theme.write_text(original + "\n// repo-updates reload bump\n")
        time.sleep(1.0)
        theme.write_text(original)
        log("bumped Theme.qml to force the panel's hot reload")
    except OSError as e:
        log(f"panel reload bump failed: {e}")


def reload_hypr():
    """`hyprctl reload`, through the session-env resolver.

    A user unit inherits whatever HYPRLAND_INSTANCE_SIGNATURE the manager last
    had, which is routinely a dead nested test compositor — hyprctl then fails
    while exiting 0. hypr-session-env.sh resolves the live instance instead.
    """
    if NO_RELOAD:
        return False
    wrapper = HOME / ".config/scripts/hypr-session-env.sh"
    cmd = ([str(wrapper), "hyprctl", "reload"] if wrapper.exists()
           else ["hyprctl", "reload"])
    rc, tail = run(cmd, timeout=120)
    if rc != 0:
        log(f"hyprctl reload failed: {tail}")
    return rc == 0


def build_watcher(prog):
    """An on_line for the rebuild: turns nix's chatter into a real fraction.

    The wrapper runs preflight, then nix evaluates (nothing countable to say),
    then it prints its plan and starts working through it. Only the last of
    those three has a denominator, so the first two creep and this switches to
    the honest number the moment the plan appears.
    """
    st = {"total": 0, "done": 0, "planned": False}

    def on_line(line):
        line = line.strip()
        m = RE_PLAN_BUILD.search(line) or RE_PLAN_FETCH.search(line)
        if m:
            st["total"] += int(m.group(1))
            st["planned"] = True
            prog.set(frac=0.0, detail=f"0/{st['total']} paths")
            return
        m = RE_BUILDING.match(line) or RE_COPYING.match(line)
        if m:
            st["done"] += 1
            name = m.group(1)[:24]
            if st["planned"] and st["total"]:
                prog.set(frac=min(0.99, st["done"] / st["total"]),
                         detail=f"{st['done']}/{st['total']} · {name}")
            else:
                # No plan line (a tiny build prints none): the count is all we
                # have, so show it and keep the bar creeping.
                prog.set(detail=f"{st['done']} paths · {name}", stop_creep=False)
            return
        if "preflight" in line.lower() and not st["planned"]:
            prog.set(detail="preflight checks", stop_creep=False)
        elif line.startswith("Activating ") or "activation" in line.lower():
            prog.set(frac=0.99, detail="activating")

    return on_line


def apply(prog=None, progress=True):
    """Pull, rebuild, reload. Returns (ok, message).

    `prog` is the toast already on screen — settle() raises it the instant the
    button is clicked, because the first thing this does is a fetch and a
    survey, and on a slow link that was a good ten seconds of nothing after a
    click that visibly dismissed the offer. Owning it here instead would put a
    gap in the one guarantee the toast makes: something is on screen, saying
    what is happening, from the click until it is done.

    It cannot reuse the OFFER's id — the card dismissed that notification the
    moment its button was invoked, and a --replace-id naming a notification the
    server no longer holds opens a brand new toast instead of updating (the same
    bug that made surfer's downloads toast on every whole percent).
    """
    # No caller owns a VISIBLE toast here — `--apply` is the by-hand route and
    # passes progress=False, so the steps go to the terminal and nothing is
    # raised over what he is already looking at. A future caller that wants both
    # must raise it and call finish() itself, the way settle() does; otherwise
    # the last step's toast would sit there at -t 0 with nothing to retire it.
    own = prog is None
    if own:
        prog = Progress(enabled=progress)
        prog.start()
    try:
        prog.step("check", "fetching origin", creep=8)
        s = survey()
        if not s["ok"]:
            return False, s["why"]
        if s["behind"] == 0:
            return True, "already up to date"
        if s["ahead"]:
            return False, (f"{s['ahead']} local commit(s) are not pushed — "
                           "fast-forward impossible, land them first")

        steps = [("pull", "pulling")]
        if s["needs_rebuild"]:
            steps.append(("build", "rebuilding"))
        if "panel" in s["reload"]:
            steps.append(("panel", "reloading the panel"))
        if "hyprctl" in s["reload"] and not s["needs_relog"]:
            steps.append(("hypr", "reloading hyprland"))
        prog.plan(steps)

        prog.step("pull", f"{s['behind']} commits", creep=6)

        def pull_line(line):
            m = RE_GIT_PCT.search(line)
            if m:
                # Receiving is the bulk of it; resolving is the tail.
                base, span = (0.0, 0.8) if m.group(1).startswith("Receiving") \
                    else (0.8, 0.2)
                prog.set(frac=base + span * int(m.group(2)) / 100.0)

        rc, tail = run(["git", "pull", "--ff-only", "--progress",
                        "origin", BRANCH], timeout=180, on_line=pull_line)
        if rc != 0:
            return False, "pull refused: " + tail.split("\n")[-1]
        prog.set(frac=1.0, detail=f"{s['behind']} commits")

        if s["needs_rebuild"]:
            # Creeps until nix prints its plan; build_watcher takes over then.
            prog.step("build", "evaluating", creep=90)
            cmd = (REBUILD_CMD.split() if REBUILD_CMD
                   else (["sudo", "rebuild-top"] if host() == "top" else ["rebuild-air"]))
            rc, tail = run(cmd, timeout=7200, on_line=build_watcher(prog))
            if rc != 0:
                return False, "rebuild FAILED: " + tail.split("\n")[-1]
            prog.set(frac=1.0, detail="done")

        done = ["pulled"]
        if s["needs_rebuild"]:
            done.append("rebuilt")
        if "panel" in s["reload"]:
            prog.step("panel")
            reload_panel()
            prog.set(frac=1.0)
            done.append("panel reloaded")
        if "hyprctl" in s["reload"] and not s["needs_relog"]:
            prog.step("hypr")
            if reload_hypr():
                done.append("hyprctl reload")
            prog.set(frac=1.0)
        if s["needs_relog"]:
            done.append("compositor bumped — the plugin swaps at next login")
        if not s["needs_rebuild"]:
            done.append("no rebuild was needed")

        return True, ", ".join(done)
    finally:
        if own:
            prog._stop.set()


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------

def load_state():
    try:
        return json.loads((STATE / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(st):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "state.json").write_text(json.dumps(st, indent=1))
    except OSError as e:
        log(f"state write failed: {e}")


def off():
    return (STATE / "off").exists()


def check_and_offer(pending):
    """One pass. `pending` holds the toast we are still waiting on, if any."""
    if off():
        return pending
    s = survey()
    if not s["ok"]:
        log(s["why"])
        return pending
    if s["behind"] == 0:
        return pending

    st = load_state()
    if st.get("dismissed") == s["sha"]:
        return pending
    if pending and pending.get("sha") == s["sha"] and pending["proc"].poll() is None:
        return pending          # already on screen, still waiting on him
    if pending and pending["proc"].poll() is None:
        pending["proc"].kill()  # superseded by newer commits

    summary, body = toast_text(s)
    dry = os.environ.get("REPO_UPDATES_NOTIFY") == ""
    if not actions_drawn():
        # No buttons will be drawn, so do not ship any: name the command instead.
        notify(summary, body + "\nrun nix-pull to apply")
        log(f"offered (no actions, notifActions off): {s['sha'][:8]} {s['cost']}")
        st["dismissed"] = s["sha"]
        save_state(st)
        return None

    nid, proc = notify(summary, body, wait=True,
                       actions=[("apply", "Pull & apply"), ("dismiss", "Dismiss")])

    # NOTHING WAS SHOWN — retry, never record it as answered. The unit is
    # WantedBy default.target, so at a boot it can easily be surveying before
    # the panel has bound org.freedesktop.Notifications, and notify-send then
    # exits non-zero without ever printing an id. Treating that as "dismissed"
    # would swallow the update until the NEXT push. A real notification id is
    # always nonzero, so `nid == 0` is the whole test — it catches both a
    # notify-send that could not start and one that started and failed.
    if not hasattr(proc, "poll") or nid == 0:
        if hasattr(proc, "poll"):
            proc.kill()
        if dry:
            log(f"offered {s['behind']} commits ({s['sha'][:8]}): {s['cost']}")
            st["dismissed"] = s["sha"]
            save_state(st)
            return None
        log("no notification server answered — retrying shortly")
        FLAGS["retry"] = True
        return None

    log(f"offered {s['behind']} commits ({s['sha'][:8]}): {s['cost']}")
    return {"sha": s["sha"], "id": nid, "proc": proc}


def settle(pending):
    """Has he answered the toast we are holding? Act on it if so."""
    if not pending or pending["proc"].poll() is None:
        return pending
    key = (pending["proc"].stdout.readline() or "").strip()
    st = load_state()
    if key == "apply":
        log("apply: he clicked")
        # Raised HERE, not inside apply(): the card dismissed the offer the
        # instant the button was invoked, and the survey that follows can take
        # ten seconds. Nothing on screen in between reads as a button that did
        # nothing.
        prog = Progress()
        prog.start()
        ok, msg = apply(prog=prog)
        log(("applied: " if ok else "apply failed: ") + msg)
        prog.finish(ok, "~/nix applied" if ok else "~/nix apply failed",
                    msg + f"\nlog: {LOG}")
        if ok:
            st.pop("dismissed", None)
    else:
        # Dismissed, or closed some other way. Same meaning: not now — and not
        # again until something newer lands.
        log(f"dismissed {pending['sha'][:8]}")
        st["dismissed"] = pending["sha"]
    save_state(st)
    return None


def daemon():
    log(f"repo-updates: watching {REPO} on {host()}, "
        f"peek {PEEK_SEC}s, poll {POLL_MIN}m")
    pending = check_and_offer(None)
    last_check = time.monotonic()
    last_peek = time.monotonic()
    # The remote sha the last peek reported. A peek that says the same thing
    # twice is not news, so the full survey does not run again for it — that is
    # what lets the peek be cheap enough to run every minute.
    peeked = None
    mono, boot = time.monotonic(), time.clock_gettime(time.CLOCK_BOOTTIME)
    while True:
        time.sleep(TICK_SEC)
        pending = settle(pending)

        now_mono = time.monotonic()
        now_boot = time.clock_gettime(time.CLOCK_BOOTTIME)
        slept = (now_boot - boot) - (now_mono - mono)
        mono, boot = now_mono, now_boot

        why = None
        if slept > RESUME_GAP_SEC:
            why = f"resumed from {int(slept)}s of suspend"
        elif FLAGS["retry"] and now_mono - last_check > RETRY_SEC:
            why = "retry — the last toast never reached a server"
            FLAGS["retry"] = False
        elif now_mono - last_check > POLL_MIN * 60:
            why = "poll"
        elif PEEK_SEC and now_mono - last_peek >= PEEK_SEC and not off():
            last_peek = now_mono
            sha = peek()
            if sha and sha != peeked:
                peeked = sha
                if sha != head_sha():
                    why = f"origin/{BRANCH} is at {sha[:8]}"
        if why:
            log("checking: " + why)
            last_check = now_mono
            pending = check_and_offer(pending)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "--daemon"
    if cmd == "--check":
        s = survey()
        if not s["ok"]:
            print(s["why"], file=sys.stderr)
            return 1
        if s["behind"] == 0:
            print("~/nix is up to date with origin/%s" % BRANCH)
            return 0
        print(f"{s['behind']} commit(s) waiting ({s['sha'][:8]}):")
        for subj in s["subjects"]:
            print("  - " + subj)
        print("cost: " + s["cost"])
        if s["moved_inputs"]:
            print("flake inputs moved: " + ", ".join(s["moved_inputs"]))
        if s["ahead"]:
            print(f"WARNING: {s['ahead']} local commit(s) unpushed — no fast-forward")
        return 10
    if cmd == "--apply":
        # By hand (`nix-pull apply`): the steps go to the terminal via log(),
        # so no toast is raised over whatever he is already looking at.
        ok, msg = apply(progress=False)
        print(msg)
        return 0 if ok else 1
    if cmd == "--demo":
        # The toast, with its buttons, wired to nothing. This exists because the
        # real one only appears when the other machine has actually pushed, and
        # nothing else here may put a notification on his screen to check the
        # buttons render and come back — that is his call to make, so it is a
        # command he runs, not a test anything else fires.
        nid, proc = notify("2 commits waiting in ~/nix",
                           "- panel: gate cava on audio playing\n"
                           "- flake: bump hyprland\ndemo only — nothing will be pulled",
                           wait=True,
                           actions=[("apply", "Pull & apply"), ("dismiss", "Dismiss")])
        if not hasattr(proc, "poll"):
            print("could not raise the toast (is notify-send on PATH?)")
            return 1
        proc.wait()
        key = (proc.stdout.readline() or "").strip()
        print(f"toast {nid} closed; button: {key or '(dismissed without a button)'}")
        return 0
    if cmd == "--demo-progress":
        # The APPLY toast — the bar, the steps, the in-place morph — with
        # nothing pulled and nothing built. Same reason as --demo: this is the
        # only way to look at it without waiting for the other machine to push,
        # and putting a notification on his screen is his call, not ours.
        prog = Progress()
        prog.plan([("pull", "pulling"), ("build", "rebuilding"),
                   ("panel", "reloading the panel")])
        prog.start()
        prog.step("pull", "3 commits")
        for pct in range(0, 101, 10):
            prog.set(frac=pct / 100.0)
            time.sleep(0.15)
        prog.step("build", "evaluating", creep=6)
        time.sleep(4)
        for n in range(0, 41):
            prog.set(frac=n / 40.0, detail=f"{n}/40 · demo-package")
            time.sleep(0.12)
        prog.step("panel")
        prog.set(frac=1.0)
        time.sleep(1)
        prog.finish(True, "~/nix applied", "pulled, rebuilt, panel reloaded (demo)")
        return 0
    if cmd in ("--daemon", ""):
        daemon()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

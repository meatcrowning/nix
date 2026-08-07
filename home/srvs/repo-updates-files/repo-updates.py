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
  * every POLL_MIN minutes as a backstop, so a push that lands while he is
    working is noticed the same day rather than at the next reboot.

WHAT IT SAYS. The toast carries the commit count, the first couple of subjects
and a COST line, because "there are updates" is useless if applying them means a
seven-minute compile. The cost is read off the diff: which flake inputs moved
(the compositor pin is the expensive one — book has no aarch64 cache for
Hyprland and builds it from source), whether the plugin's own source changed,
whether anything under home/ or sys/ needs a switch at all, or whether it is
only `apps/` live source that a rebuild would not touch in the first place.

An estimate off a path list is a guess, so the honest number is taken at APPLY
time instead: `nix build --dry-run` on the pulled config prints exactly how many
derivations will be built rather than substituted, and that count goes in the
progress toast.

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
import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
REPO = Path(os.environ.get("REPO_UPDATES_REPO", HOME / "nix"))
STATE = Path(os.environ.get("REPO_UPDATES_STATE", HOME / ".local/state/repo-updates"))
LOG = Path(os.environ.get("REPO_UPDATES_LOG", HOME / ".cache/repo-updates.log"))
SETTINGS = Path(os.environ.get("REPO_UPDATES_SETTINGS",
                               HOME / ".config/quickshell/settings.json"))
POLL_MIN = int(os.environ.get("REPO_UPDATES_POLL_MIN", "30"))
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
           expire="0"):
    """Raise (or replace) the toast. Returns (id, action_key).

    `action_key` is only ever set when `wait` is on — notify-send -w blocks
    until the toast closes and prints the invoked action, which is how a click
    on a panel button gets back to this process. With -p it prints the id first,
    so the two arrive as two lines in order.
    """
    override = os.environ.get("REPO_UPDATES_NOTIFY")
    if override == "":
        keys = " ".join(k for k, _ in actions)
        log(f"notify (dry): {summary} | {body}" + (f" | actions: {keys}" if keys else ""))
        return 0, None
    cmd = (override.split() if override else ["notify-send"])
    cmd += ["-a", "nix", "-u", urgency, "-t", str(expire), "-p"]
    if replace_id:
        cmd += ["-r", str(replace_id)]
    for key, label in actions:
        cmd += [f"--action={key}={label}"]
    if wait:
        cmd += ["-w"]
    cmd += [summary, body]

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

def run(cmd, timeout=3600, env=None):
    """Run a command, tee its tail into the log, return (rc, tail)."""
    log("run: " + " ".join(cmd))
    if NO_APPLY:
        return 0, "(REPO_UPDATES_NO_APPLY)"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env, cwd=str(REPO))
    except (OSError, subprocess.SubprocessError) as e:
        log(f"  failed to start: {e}")
        return 1, str(e)
    tail = ((p.stdout or "") + (p.stderr or "")).strip().split("\n")
    for line in tail[-40:]:
        log("  | " + line)
    return p.returncode, "\n".join(tail[-6:])


def dry_run_count():
    """How many derivations the pulled config will BUILD (not substitute).

    The honest version of the toast's cost guess. `nix build --dry-run` prints
    its plan on stderr; a line count off the "will be built" section is all we
    want. Any failure here is non-fatal — it only costs the progress toast a
    number.
    """
    if REBUILD_CMD:
        return None
    attr = ("nixosConfigurations.top.config.system.build.toplevel"
            if host() == "top" else "homeConfigurations.air.activationPackage")
    try:
        p = subprocess.run(["nix", "build", "--dry-run", "--no-link",
                            f"{REPO}#{attr}"],
                           capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError):
        return None
    txt = p.stderr or ""
    section = None
    built = 0
    for line in txt.split("\n"):
        stripped = line.strip()
        if "will be built" in stripped:
            section = "build"
            continue
        if "will be fetched" in stripped or "will be copied" in stripped:
            section = None
            continue
        if section == "build" and stripped.startswith("/nix/store/"):
            built += 1
    return built


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


def apply(progress=True):
    """Pull, rebuild, reload. Returns (ok, message).

    The progress toast morphs in place: the first step opens one, every step
    after it replaces that id. It cannot reuse the OFFER's id — the card
    dismissed that notification the moment its button was invoked, and a
    --replace-id naming a notification the server no longer holds opens a brand
    new toast instead of updating (the same bug that made surfer's downloads
    toast on every whole percent).
    """
    prog = {"id": 0}
    s = survey()
    if not s["ok"]:
        return False, s["why"], prog["id"]
    if s["behind"] == 0:
        return True, "already up to date", prog["id"]

    def step(text):
        log("STEP: " + text)
        if not progress:
            return
        nid, _ = notify("applying ~/nix", text, replace_id=prog["id"])
        if nid:
            prog["id"] = nid

    if s["ahead"]:
        return False, (f"{s['ahead']} local commit(s) are not pushed — "
                       "fast-forward impossible, land them first"), prog["id"]

    step(f"pulling {s['behind']} commits...")
    rc, tail = run(["git", "pull", "--ff-only", "origin", BRANCH], timeout=180)
    if rc != 0:
        return False, "pull refused: " + tail.split("\n")[-1], prog["id"]

    if s["needs_rebuild"]:
        n = dry_run_count()
        step("building..." if n is None else f"building, {n} derivation(s)...")
        cmd = (REBUILD_CMD.split() if REBUILD_CMD
               else (["sudo", "rebuild-top"] if host() == "top" else ["rebuild-air"]))
        rc, tail = run(cmd, timeout=7200)
        if rc != 0:
            return False, "rebuild FAILED: " + tail.split("\n")[-1], prog["id"]

    done = ["pulled"]
    if s["needs_rebuild"]:
        done.append("rebuilt")
    if "panel" in s["reload"]:
        step("reloading the panel...")
        reload_panel()
        done.append("panel reloaded")
    if "hyprctl" in s["reload"] and not s["needs_relog"]:
        step("reloading hyprland...")
        if reload_hypr():
            done.append("hyprctl reload")
    if s["needs_relog"]:
        done.append("compositor bumped — the plugin swaps at next login")
    if not s["needs_rebuild"]:
        done.append("no rebuild was needed")

    return True, ", ".join(done), prog["id"]


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
    if not actions_drawn():
        # No buttons will be drawn, so do not ship any: name the command instead.
        notify(summary, body + "\nrun nix-pull to apply")
        log(f"offered (no actions, notifActions off): {s['sha'][:8]} {s['cost']}")
        st["dismissed"] = s["sha"]
        save_state(st)
        return None

    nid, proc = notify(summary, body, wait=True,
                       actions=[("apply", "Pull & apply"), ("dismiss", "Dismiss")])
    log(f"offered {s['behind']} commits ({s['sha'][:8]}): {s['cost']}")
    if not hasattr(proc, "poll"):
        # notify-send never started (or a dry run): there is nothing to wait on,
        # and re-offering every tick would be the nag this must not become.
        st["dismissed"] = s["sha"]
        save_state(st)
        return None
    return {"sha": s["sha"], "id": nid, "proc": proc}


def settle(pending):
    """Has he answered the toast we are holding? Act on it if so."""
    if not pending or pending["proc"].poll() is None:
        return pending
    key = (pending["proc"].stdout.readline() or "").strip()
    st = load_state()
    if key == "apply":
        log("apply: he clicked")
        ok, msg, pid = apply()
        log(("applied: " if ok else "apply failed: ") + msg)
        # Success expires like any other toast; a failure is urgency 2, which
        # the card keeps on screen until he clicks it.
        notify("~/nix applied" if ok else "~/nix apply failed",
               msg + f"\nlog: {LOG}", replace_id=pid,
               urgency="normal" if ok else "critical",
               expire="-1" if ok else "0")
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
    log(f"repo-updates: watching {REPO} on {host()}, poll {POLL_MIN}m")
    pending = check_and_offer(None)
    last_check = time.monotonic()
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
        elif now_mono - last_check > POLL_MIN * 60:
            why = "poll"
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
        ok, msg, _ = apply(progress=False)
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
    if cmd in ("--daemon", ""):
        daemon()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

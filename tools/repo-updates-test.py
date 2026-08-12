#!/usr/bin/env python3
"""repo-updates-test — the harness for home/srvs/repo-updates-files/repo-updates.py.

Everything runs against THROWAWAY git repos in a temp dir, with the toast
replaced by a log line, the rebuild replaced by `true` and both reloads switched
off. Nothing here fetches over the network, touches ~/nix, raises a
notification, rebuilds anything, bumps his Theme.qml or reloads his compositor —
the module's REPO_UPDATES_* overrides exist for exactly this.

    ./tools/repo-updates-test.py            # all cases
    ./tools/repo-updates-test.py -v         # ... and the module's own log

Re-run it after touching the classifier (what a change is going to cost), the
dedupe (a dismissed update must stay dismissed until something NEWER lands), the
peek (the cheap ls-remote that is what makes the toast prompt), the progress
toast (one notification, morphed in place, a bar per step) or the apply flow
(the ff-only pull and its refusals).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent / "home/srvs/repo-updates-files/repo-updates.py"
VERBOSE = "-v" in sys.argv

FAILS = []


def sh(*args, cwd=None, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"{args} -> {p.returncode}\n{p.stderr}")
    return p


def check(name, got, want):
    ok = want(got) if callable(want) else got == want
    print(("  ok   " if ok else "  FAIL ") + name)
    if not ok:
        print(f"         got: {got!r}")
        FAILS.append(name)


class Sandbox:
    """A bare origin plus a local clone, standing in for ~/nix and its remote."""

    def __init__(self, root):
        self.root = root
        self.origin = root / "origin.git"
        self.repo = root / "checkout"
        self.state = root / "state"
        self.log = root / "log"
        sh("git", "init", "--quiet", "--bare", "-b", "main", str(self.origin))
        seed = root / "seed"
        seed.mkdir()
        self._write(seed, "flake.nix", "{}\n")
        self._write(seed, "flake.lock", json.dumps(self._lock("rev-a", "rev-b")))
        self._write(seed, "home/prog/quickshell-files/Theme.qml", "// theme\n")
        sh("git", "init", "--quiet", "-b", "main", str(seed))
        self._commit(seed, "seed")
        sh("git", "remote", "add", "origin", str(self.origin), cwd=seed)
        sh("git", "push", "--quiet", "origin", "main", cwd=seed)
        sh("git", "clone", "--quiet", str(self.origin), str(self.repo))
        self.upstream = root / "other-machine"
        sh("git", "clone", "--quiet", str(self.origin), str(self.upstream))

    @staticmethod
    def _lock(hypr_rev, nixpkgs_rev):
        return {"nodes": {
            "hyprland": {"locked": {"rev": hypr_rev}},
            "nixpkgs": {"locked": {"rev": nixpkgs_rev}},
        }, "root": {}}

    @staticmethod
    def _write(repo, rel, text):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _commit(self, repo, msg):
        sh("git", "add", "-A", cwd=repo)
        sh("git", "-c", "user.email=t@t", "-c", "user.name=t",
           "commit", "--quiet", "-m", msg, cwd=repo)

    def push(self, files, msg):
        """The other machine lands a commit."""
        for rel, text in files.items():
            self._write(self.upstream, rel, text)
        self._commit(self.upstream, msg)
        sh("git", "push", "--quiet", "origin", "main", cwd=self.upstream)

    def local_commit(self, files, msg):
        """He commits here and does not push — the diverged case."""
        for rel, text in files.items():
            self._write(self.repo, rel, text)
        self._commit(self.repo, msg)

    def env(self, **extra):
        e = dict(os.environ)
        e.update({
            "REPO_UPDATES_REPO": str(self.repo),
            "REPO_UPDATES_STATE": str(self.state),
            "REPO_UPDATES_LOG": str(self.log),
            "REPO_UPDATES_NOTIFY": "",          # log the toast, raise nothing
            "REPO_UPDATES_REBUILD_CMD": "true",  # never switch the machine
            "REPO_UPDATES_NO_RELOAD": "1",       # never touch his panel/compositor
            "REPO_UPDATES_HOST": "book",
            "REPO_UPDATES_SETTINGS": str(self.root / "settings.json"),
        })
        e.update(extra)
        return e

    def run(self, *args, **envextra):
        p = subprocess.run([sys.executable, str(MODULE)] + list(args),
                           capture_output=True, text=True, env=self.env(**envextra))
        if VERBOSE:
            print("    --- " + " ".join(args))
            print("    " + (p.stdout or "").replace("\n", "\n    "))
        return p

    def logtext(self):
        return self.log.read_text() if self.log.exists() else ""

    def pyrun(self, code, **envextra):
        """Run `code` against the module loaded as `m`. Returns (proc, log tail)."""
        before = len(self.logtext())
        p = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util,sys;"
             f"spec=importlib.util.spec_from_file_location('ru', r'{MODULE}');"
             "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
             + code],
            capture_output=True, text=True, env=self.env(**envextra))
        if VERBOSE:
            print("    --- " + code)
            print("    " + (p.stdout + p.stderr).replace("\n", "\n    "))
        return p, self.logtext()[before:]

    def offer(self, **envextra):
        """One daemon pass: survey, decide, 'toast'. Returns the log tail."""
        return self.pyrun("m.check_and_offer(None)", **envextra)[1]


def case(title):
    print(title)


def main():
    if not MODULE.exists():
        print(f"missing {MODULE}")
        return 1
    root = Path(tempfile.mkdtemp(prefix="repo-updates-test."))
    try:
        # ---- classification -------------------------------------------------
        case("a checkout level with its remote")
        sb = Sandbox(root)
        (root / "settings.json").write_text(json.dumps({"notifActions": True}))
        p = sb.run("--check")
        check("exit 0, nothing waiting", (p.returncode, "up to date" in p.stdout),
              (0, True))
        check("no toast", "offered" in sb.offer(), False)

        case("an apps/-only push")
        sb.push({"apps/painter/main.py": "print(1)\n"}, "painter: tweak")
        p = sb.run("--check")
        check("exit 10", p.returncode, 10)
        check("costs no rebuild", "no rebuild" in p.stdout, True)
        check("toast offered", "offered 1 commits" in sb.offer(), True)

        case("the compositor pin moves (book)")
        sb2 = Sandbox(root / "b")
        (root / "b" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sb2.push({"flake.lock": json.dumps(Sandbox._lock("rev-NEW", "rev-b"))},
                 "flake: bump hyprland")
        p = sb2.run("--check")
        check("names the source build", "from source" in p.stdout, True)
        check("lists the moved input", "hyprland" in p.stdout, True)
        p = sb2.run("--check", REPO_UPDATES_HOST="top")
        check("top gets the relog warning, not the compile",
              ("next login" in p.stdout, "from source" in p.stdout), (True, False))

        case("a panel QML push")
        sb3 = Sandbox(root / "c")
        (root / "c" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sb3.push({"home/prog/quickshell-files/Media.qml": "// x\n"}, "panel: x")
        p = sb3.run("--check")
        check("wants a rebuild", "cost: a rebuild" in p.stdout, True)

        # ---- dedupe ---------------------------------------------------------
        case("dismissal, and what re-arms it")
        sb4 = Sandbox(root / "d")
        (root / "d" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sb4.push({"apps/x.py": "1\n"}, "one")
        check("first pass offers", "offered" in sb4.offer(), True)
        check("second pass is quiet", "offered" in sb4.offer(), False)
        sb4.push({"apps/x.py": "2\n"}, "two")
        check("a newer commit re-offers", "offered" in sb4.offer(), True)

        case("notification actions switched off in the panel")
        sb5 = Sandbox(root / "e")
        (root / "e" / "settings.json").write_text(json.dumps({"notifActions": False}))
        sb5.push({"apps/x.py": "1\n"}, "one")
        tail = sb5.offer()
        check("still toasts", "notify (dry)" in tail, True)
        check("names nix-pull instead of shipping dead buttons",
              ("nix-pull" in tail, "actions:" in tail), (True, False))

        case("a toast that never reaches a server is retried, not swallowed")
        sb9 = Sandbox(root / "i")
        (root / "i" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sb9.push({"apps/x.py": "1\n"}, "one")
        # `false` stands in for notify-send with nothing on the bus yet: it exits
        # non-zero having printed no id, which is what a boot racing the panel
        # looks like. Recording that as answered would lose the update until the
        # NEXT push.
        tail = sb9.offer(REPO_UPDATES_NOTIFY="false")
        check("says so", "no notification server" in tail, True)
        check("records no dismissal",
              json.loads((sb9.state / "state.json").read_text()).get("dismissed")
              if (sb9.state / "state.json").exists() else None, None)
        check("the next pass offers it again", "offered" in sb9.offer(), True)

        case("the real notify-send accepts a body that starts with a dash")
        # Every case above stubs the notifier, which is how the toast shipped
        # broken: notify-send parses argv with GOption, so a body whose first
        # line is a commit-subject bullet ("- curate: ...") was read as a flag
        # — "Unknown option", exit 1, no id — and the daemon could only report
        # it as "no notification server answered". `--` is the fix; this runs
        # the REAL binary to prove the argv still parses. The bus address names
        # a socket that does not exist and every fallback route is unset, so it
        # cannot reach his session: the parse happens long before any connect.
        nsend = shutil.which("notify-send")
        if not nsend:
            print("  skip  notify-send is not on PATH")
        else:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR")}
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent/repo-updates-test"
            p = subprocess.run(
                [nsend, "-a", "nix", "-i", "repo-updates", "-u", "normal",
                 "-t", "0", "-p", "-h", "int:value:42",
                 "--action=apply=Pull & apply",
                 "--action=dismiss=Dismiss", "--",
                 "2 commits waiting in ~/nix",
                 "- curate: verify dupes union-finds\nplugin rebuild"],
                capture_output=True, text=True, env=env, timeout=30)
            check("argv parses", "Unknown option" not in p.stderr, True)
            check("it got as far as the bus", "connect" in p.stderr.lower(), True)

        # ---- applying -------------------------------------------------------
        case("apply, the happy path")
        sb6 = Sandbox(root / "f")
        (root / "f" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sb6.push({"home/prog/quickshell-files/Media.qml": "// y\n"}, "panel: y")
        p = sb6.run("--apply")
        check("exit 0", p.returncode, 0)
        check("says what it did", "pulled" in p.stdout and "rebuilt" in p.stdout, True)
        _, behind, _ = (0, sh("git", "rev-list", "--count", "HEAD..origin/main",
                              cwd=sb6.repo).stdout.strip(), 0)
        check("checkout is level afterwards", behind, "0")

        case("the peek sees a push without fetching anything")
        # The peek is what makes the toast prompt: one ls-remote a minute
        # instead of a full fetch, so the poll is no longer the only thing that
        # notices. It must see the new sha AND leave the checkout alone — a peek
        # that quietly fetched would be the expensive thing it exists to avoid.
        sbp = Sandbox(root / "p")
        (root / "p" / "settings.json").write_text(json.dumps({"notifActions": True}))
        before_ref = sh("git", "rev-parse", "origin/main", cwd=sbp.repo).stdout.strip()
        sbp.push({"apps/x.py": "1\n"}, "one")
        pushed = sh("git", "rev-parse", "HEAD", cwd=sbp.upstream).stdout.strip()
        p, _ = sbp.pyrun("print(m.peek());print(m.head_sha())")
        seen, head = (p.stdout.strip().split("\n") + ["", ""])[:2]
        check("peek reports the pushed sha", seen, pushed)
        check("and it is not what we have", head != seen, True)
        check("nothing was fetched",
              sh("git", "rev-parse", "origin/main", cwd=sbp.repo).stdout.strip(),
              before_ref)
        sh("git", "-C", str(sbp.repo), "config", "remote.origin.url", "/nonexistent")
        p, _ = sbp.pyrun("print(repr(m.peek()))")
        check("an unreachable remote is 'no news', not a crash",
              p.stdout.strip(), "None")

        # ---- the progress toast ---------------------------------------------
        case("applying reports every step on one toast, with a bar")
        sbq = Sandbox(root / "q")
        (root / "q" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sbq.push({"home/prog/quickshell-files/Media.qml": "// z\n"}, "panel: z")
        _, tail = sbq.pyrun("pr=m.Progress();pr.start();"
                            "ok,msg=m.apply(prog=pr);pr.finish(ok,'~/nix applied',msg)")
        steps = [ln for ln in tail.split("\n") if "notify (dry): applying ~/nix" in ln]
        check("the toast is up before the survey is done",
              "checking what is waiting" in tail, True)
        check("every step draws on it", len(steps) >= 3, True)
        check("each carries a bar value",
              all("%" in s for s in steps), True)
        check("and says which step of how many", "step 1 of 3" in tail, True)
        check("the pull, the rebuild and the panel are all named",
              ("pulling" in tail, "rebuilding" in tail,
               "reloading the panel" in tail), (True, True, True))
        check("it ends on a result, at 100%",
              "~/nix applied" in tail and "| 100%" in tail, True)

        case("a build's own plan drives the bar")
        # nix prints its plan before it starts and one line per path as it
        # goes — a real numerator over a real denominator, which is why the
        # separate dry-run pass (a whole extra evaluation, minutes on book) is
        # gone.
        sbr = Sandbox(root / "r")
        (root / "r" / "settings.json").write_text(json.dumps({"notifActions": True}))
        p, _ = sbr.pyrun(
            "pr=m.Progress(enabled=False);pr.plan([('build','rebuilding')]);"
            "pr.step('build','evaluating',creep=90);w=m.build_watcher(pr);"
            "w('these 3 derivations will be built:');"
            "w(\"building '/nix/store/aaaa-hyprvtb-2.98.drv'\");"
            "print(pr._state()[4]);"
            "w(\"copying path '/nix/store/bbbb-foo' from 'https://cache.nixos.org'\");"
            "w(\"copying path '/nix/store/cccc-bar' from 'https://cache.nixos.org'\");"
            "print(pr._state()[3], pr._state()[4])")
        out = p.stdout.strip().split("\n")
        check("one of three is a third of the way", out[0], "33")
        check("three of three is capped short of done — it is not over yet",
              out[-1], "3/3 · bar 99")

        case("apply refuses a diverged checkout")
        sb7 = Sandbox(root / "g")
        (root / "g" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sb7.push({"apps/x.py": "1\n"}, "theirs")
        sb7.local_commit({"apps/y.py": "1\n"}, "mine")
        p = sb7.run("--apply")
        check("exit 1", p.returncode, 1)
        check("names the unpushed commit", "not pushed" in p.stdout, True)
        check("pulled nothing", sh("git", "rev-list", "--count", "HEAD..origin/main",
                                   cwd=sb7.repo).stdout.strip(), "1")

        case("apply refuses when a dirty file is in the way")
        sb8 = Sandbox(root / "h")
        (root / "h" / "settings.json").write_text(json.dumps({"notifActions": True}))
        sb8.push({"apps/x.py": "theirs\n"}, "theirs")
        (sb8.repo / "apps").mkdir(parents=True, exist_ok=True)
        (sb8.repo / "apps/x.py").write_text("HIS UNCOMMITTED WORK\n")
        p = sb8.run("--apply")
        check("exit 1", p.returncode, 1)
        check("his edit is untouched",
              (sb8.repo / "apps/x.py").read_text(), "HIS UNCOMMITTED WORK\n")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS))
        return 1
    print("all cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

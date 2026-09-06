#!/usr/bin/env python3
"""Headless contract test for the askpass dialog — no screen, no user.

Runs the REAL apps/askpass/main.py under QT_QPA_PLATFORM=offscreen, drives the
QML from Python, and asserts the only three things that matter:

  accept  -> exit 0, stdout is EXACTLY the typed password + "\n", nothing else
  cancel  -> exit 1, stdout EMPTY
  broken  -> exit 3 (so the wrapper falls back to ksshaskpass instead of
             leaving `sudo -A` with no way to authenticate)

Run it as a whole:  python3 apps/askpass/tools/askpass-selftest.py
Internally it re-execs itself per case (`--case accept|cancel|broken`) because
Sudo.accept/cancel end the process with os._exit, which is the behaviour under
test.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "main.py"
SECRET = "correct horse battery staple"


def reexec_with_pyside():
    """Re-exec under an interpreter that HAS PySide6, if this one doesn't.

    On `top` a bare `python3` is the nix interpreter with no PySide6 at all, so
    the invocation this file's docstring and askpass/AGENTS.md both prescribe
    reported two spurious FAILs (accept) and three misleading PASSes — `cancel`
    and `broken` "passed" only because a missing PySide6 is what `broken` is
    testing for. A verification command that fails on the machine agents run it
    on is worse than none: the whole point of this file is that the askpass path
    can be checked WITHOUT firing a real `sudo -A` at the user's screen.

    The interpreter that has PySide6 is the one baked into the `vista-askpass`
    wrapper by home/prog/askpass.nix — the same one the dialog really runs
    under, which is the right one to test with anyway. book never reaches here:
    Fedora's /usr/bin/python3 imports PySide6 directly.
    """
    if importlib.util.find_spec("PySide6") or os.environ.get("ASKPASS_SELFTEST_REEXEC"):
        return
    wrapper = shutil.which("vista-askpass")
    interp = None
    if wrapper:
        try:
            m = re.search(r'^exec "([^"]+/bin/python3[^"]*)"',
                          Path(os.path.realpath(wrapper)).read_text(), re.M)
            interp = m.group(1) if m else None
        except OSError:
            interp = None
    if not interp or not os.access(interp, os.X_OK) or interp == sys.executable:
        print("askpass-selftest: no PySide6 here and no vista-askpass wrapper to "
              "borrow an interpreter from; results below are not meaningful.",
              file=sys.stderr)
        return
    env = dict(os.environ, ASKPASS_SELFTEST_REEXEC="1")
    os.execve(interp, [interp, os.path.abspath(__file__)] + sys.argv[1:], env)


def run_case(case):
    """Child half: load main.py as a module, swap its engine for one that drives
    the dialog once loaded, then hand control to its real main()."""
    from PySide6.QtCore import QObject, QTimer, QMetaObject
    from PySide6.QtQml import QQmlApplicationEngine

    spec = importlib.util.spec_from_file_location("askpass_main", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # top level only; main() is under __main__

    class DrivenEngine(QQmlApplicationEngine):
        def load(self, url):
            super().load(url)
            QTimer.singleShot(50, self._drive)

        def _drive(self):
            roots = self.rootObjects()
            if not roots:
                os._exit(9)
            root = roots[0]
            if case == "cancel":
                mod_sudo = self.rootContext().contextProperty("Sudo")
                QMetaObject.invokeMethod(mod_sudo, "cancel")
                return
            field = root.findChild(QObject, "pwField")
            if field is None:
                print("selftest: pwField not found", file=sys.stderr)
                os._exit(9)
            field.setProperty("text", SECRET)
            QMetaObject.invokeMethod(root, "submit")

    mod.QQmlApplicationEngine = DrivenEngine
    sys.argv = ["main.py", "[sudo] password for lam:"]
    mod.main()


NOPYSIDE = None   # tempdir shadowing PySide6, set up in main()


def child_env(case):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    # and no display for it to fall back to: a real askpass dialog on his screen
    # would be a password prompt he did not ask for.
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    # book's system PySide6 must not load Qt plugins exported by a Nix-launched
    # terminal. Those are a different Qt build and abort before offscreen is
    # created. top re-execs under the packaged interpreter and keeps its paths.
    if Path(sys.executable).resolve() == Path("/usr/bin/python3").resolve():
        for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
            env.pop(key, None)
        env["QT_QPA_PLATFORMTHEME"] = ""
        env["QT_STYLE_OVERRIDE"] = ""
    if case == "broken":
        # Make `import PySide6` fail the way a broken Fedora python3-pyside6
        # would, and assert the exit code the wrapper's fallback keys off.
        env["PYTHONPATH"] = NOPYSIDE
    return env


def run_sampled_case(case):
    """Run one synthetic dialog and sample only that short-lived child.

    The accept child still receives the fixed, non-secret test phrase used by
    the contract suite. Nothing invokes sudo and nothing reaches a display.
    """
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, __file__, "--case", case],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=child_env(case))
    peak_rss = peak_pss = 0
    rollup = Path(f"/proc/{proc.pid}/smaps_rollup")
    while proc.poll() is None:
        try:
            values = {}
            for line in rollup.read_text().splitlines():
                if line.startswith(("Rss:", "Pss:")):
                    key, value, _unit = line.split()
                    values[key.rstrip(":")] = int(value)
            peak_rss = max(peak_rss, values.get("Rss", 0))
            peak_pss = max(peak_pss, values.get("Pss", 0))
        except (OSError, ValueError):
            pass
        time.sleep(0.002)
    stdout, stderr = proc.communicate()
    return proc, stdout, stderr, {
        "elapsed_ms": (time.monotonic() - started) * 1000,
        "peak_rss_kib": peak_rss,
        "peak_pss_kib": peak_pss,
    }


def main():
    global NOPYSIDE
    if "--case" in sys.argv:
        run_case(sys.argv[sys.argv.index("--case") + 1])
        return

    # Before anything is spawned: the children inherit sys.executable, so this
    # has to happen in the parent and only in the parent (a `--case` child must
    # keep whatever interpreter it was handed, and the `broken` child's whole
    # job is to run without PySide6).
    reexec_with_pyside()

    # A tempdir, not a directory in the repo: this tree is a live checkout with
    # a shared git index and nothing here should leave droppings in it.
    NOPYSIDE = tempfile.mkdtemp(prefix="askpass-selftest-")
    Path(NOPYSIDE, "PySide6.py").write_text('raise ImportError("simulated")\n')

    fails = []

    def check(name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
        if not ok:
            fails.append(name)

    # --- accept ---
    resource = "--resource" in sys.argv
    if resource:
        p, pout, perr, accept_sample = run_sampled_case("accept")
    else:
        p = subprocess.run([sys.executable, __file__, "--case", "accept"],
                           capture_output=True, env=child_env("accept"))
        pout, perr = p.stdout, p.stderr
    check("accept: exit 0", p.returncode == 0, f"rc={p.returncode} err={perr[-300:]!r}")
    check("accept: stdout is exactly the password",
          pout == (SECRET + "\n").encode(), f"stdout={pout!r}")

    # --- cancel ---
    if resource:
        p, pout, perr, cancel_sample = run_sampled_case("cancel")
    else:
        p = subprocess.run([sys.executable, __file__, "--case", "cancel"],
                           capture_output=True, env=child_env("cancel"))
        pout = p.stdout
    check("cancel: exit 1", p.returncode == 1, f"rc={p.returncode}")
    check("cancel: stdout empty", pout == b"", f"stdout={pout!r}")

    if resource:
        for case, sample in (("accept", accept_sample), ("cancel", cancel_sample)):
            print("RESOURCE %s elapsed_ms=%.1f peak_pss_kib=%d peak_rss_kib=%d" %
                  (case, sample["elapsed_ms"], sample["peak_pss_kib"],
                   sample["peak_rss_kib"]))

    # --- broken (no PySide6) -> exit 3 so the wrapper falls back ---
    p = subprocess.run([sys.executable, str(APP), "prompt:"],
                       capture_output=True, env=child_env("broken"))
    check("broken: exit 3", p.returncode == 3, f"rc={p.returncode}")
    check("broken: stdout empty", p.stdout == b"", f"stdout={p.stdout!r}")

    # --- sanitize(): the untrusted-text defence, tested directly ---
    spec = importlib.util.spec_from_file_location("askpass_main", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = mod.sanitize

    # NUL/BEL/ESC are dropped outright (only \n \r \t become spaces), so the ANSI
    # colour escape survives as inert literal text "[31m" — shown, never obeyed.
    check("sanitize: strips control chars", s("a\x00\x07b\x1b[31m") == "ab[31m",
          repr(s("a\x00\x07b\x1b[31m")))
    check("sanitize: collapses newlines/tabs", s("one\ntwo\t\tthree") == "one two three",
          repr(s("one\ntwo\t\tthree")))
    check("sanitize: strips C1 block", s("a\x85\x9fb") == "ab", repr(s("a\x85\x9fb")))
    long = s("x" * 500)
    check("sanitize: clamps length", len(long) <= 240 and long.endswith("..."), f"len={len(long)}")
    check("sanitize: ASCII ellipsis only", "…" not in long)
    check("sanitize: empty stays empty", s("") == "" and s(None) == "")
    check("sanitize: markup is NOT stripped (QML renders PlainText)",
          s("<b>hi</b>") == "<b>hi</b>", repr(s("<b>hi</b>")))

    check("sanitize: ascii_only replaces non-ASCII (pixel font has no glyph)",
          s("café — x", ascii_only=True) == "caf? ? x",
          repr(s("café — x", ascii_only=True)))

    # --- the derived command line: sudo's flags off, the command intact ---
    # The /proc walk itself needs a real sudo parent and is verified live (a stub
    # $SUDO_ASKPASS under `sudo -k -A <cmd>`, which prompts nobody and submits no
    # password); what is testable here is the argv parsing it feeds.
    strip = mod._strip_sudo_options
    cases = [
        (["-k", "-A", "nixos-rebuild", "switch", "--flake", "/home/lam/nix#top"],
         "nixos-rebuild switch --flake /home/lam/nix#top"),
        (["-A", "-u", "root", "--", "/bin/ls", "-la", "/root"], "/bin/ls -la /root"),
        (["-A", "sh", "-c", "rm -rf /tmp/x && echo done"],
         "sh -c 'rm -rf /tmp/x && echo done'"),
        (["-k", "-A", "-v"], "sudo -k -A -v"),          # flags only: show the flags
    ]
    for argv, want in cases:
        check(f"sudo_command: {' '.join(argv)!r}", strip(argv) == want, repr(strip(argv)))

    print("\n" + ("ALL PASS" if not fails else f"FAILED: {', '.join(fails)}"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

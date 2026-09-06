#!/usr/bin/env python3
"""Hold a deterministic Chatter state for read-only resource sampling.

The child is always Chatter's real ``--selftest`` window on Qt's offscreen
platform. All writable state lives below a fresh temporary directory and the
model endpoint is a closed local port, so this cannot contact Ollama, external
services, or the live desktop session.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


APP = Path(__file__).resolve().parents[1]


def chatter_python():
    """Use book's packaged PySide runtime; top's wrapper already supplies it."""
    system = Path("/usr/bin/python3")
    if system.exists():
        probe = subprocess.run([str(system), "-c", "import PySide6"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            return str(system)
    return sys.executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=("blank", "fake", "clear"),
                        default="blank")
    parser.add_argument("--seconds", type=float, default=60.0,
                        help="retention window, at most 3600 seconds")
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        parser.error("--seconds must be in (0, 3600]")

    with tempfile.TemporaryDirectory(prefix="chatter-resource-") as scratch:
        env = os.environ.copy()
        env.update({
            "QT_QPA_PLATFORM": "offscreen",
            "TMPDIR": scratch,
            "ORACLE_CONFIG": str(Path(scratch) / "config"),
            "ORACLE_SESSIONS": str(Path(scratch) / "sessions"),
            "ORACLE_IMAGES": str(Path(scratch) / "images"),
            "ORACLE_AUDIO": str(Path(scratch) / "audio"),
            "ORACLE_MEMORY": str(Path(scratch) / "memory"),
            "ORACLE_JOBS": str(Path(scratch) / "jobs"),
            "ORACLE_TOOLS": str(Path(scratch) / "tools"),
            "ORACLE_SKILLS": str(Path(scratch) / "skills"),
            "ORACLE_AGENTS": str(Path(scratch) / "agents"),
            "ORACLE_SANDBOX": str(Path(scratch) / "sandbox"),
            "ORACLE_READ_ROOT": scratch,
            "ORACLE_WRITE_ROOT": scratch,
            "ORACLE_EXEC_NET": "0",
            "OLLAMA_HOST": "http://127.0.0.1:9",
            "ORACLE_RESOURCE_STATE": args.state,
            "ORACLE_RESOURCE_RETAIN": str(args.seconds),
        })
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                     "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                     "ALL_PROXY", "all_proxy"):
            env.pop(name, None)
        if args.state in ("fake", "clear"):
            env["ORACLE_FAKE"] = "1"

        python = chatter_python()
        # A Codex shell on book can inherit Nix Qt plugin paths from Konsole.
        # Fedora's PySide must use Fedora's matching plugins; mixing the two Qt
        # builds aborts before QApplication exists. Top's wrapped Python needs
        # its Nix paths, so only scrub them for book's system interpreter.
        if python == "/usr/bin/python3":
            for name in tuple(env):
                if name.startswith(("QT_", "QML", "NIXPKGS_QT")):
                    env.pop(name, None)
            env["QT_QPA_PLATFORM"] = "offscreen"
        child = subprocess.Popen(
            [python, str(APP / "main.py"), "--selftest", "--face=hypr"],
            env=env,
        )
        try:
            return child.wait()
        except KeyboardInterrupt:
            child.terminate()
            return child.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())

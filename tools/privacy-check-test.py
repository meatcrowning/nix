#!/usr/bin/env python3
"""Focused tests for privacy-check.py."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "tools/privacy-check.py"


class PrivacyCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "docs/private-config").mkdir(parents=True)
        config = {
            "location": {"timeZone": "Test/Zone", "place": "Testville", "plasmaPlace": "Test Airport"},
            "devices": {"root": "/dev/disk/by-uuid/abc-123"},
            "repositories": {"claudeState": "https://private.example/state.git", "sounds": "sounds"},
            "lanCidr": "192.0.2.0/24", "bluetoothAddress": "AA:BB:CC:DD:EE:FF",
            "builderKeys": ["ssh-ed25519 AAAATESTKEY builder"],
            "smartDevices": ["/dev/disk/by-id/disk-unique"],
            "audit": {"privateEmail": "secret@example.test", "previousHandle": "old-handle"},
        }
        (self.repo / "docs/private-config/settings.json").write_text(json.dumps(config))
        (self.repo / ".gitignore").write_text("ignored.txt\ngenerated/\n")
        (self.repo / "generated").mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Public User"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "public@example.test"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self):
        return subprocess.run([str(CHECK), "--repo", str(self.repo)], text=True, capture_output=True)

    def test_reports_category_without_value_and_ignores_untracked(self):
        (self.repo / "tracked.txt").write_text("old-handle at Test/Zone AA:BB:CC:DD:EE:FF\n")
        (self.repo / "ignored.txt").write_text("secret@example.test\n")
        (self.repo / "generated/wip.txt").write_text("secret@example.test\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "tracked.txt"], check=True)
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("tracked.txt:1 previousHandle", result.stdout)
        self.assertNotIn("secret@example.test", result.stdout)
        self.assertNotIn("old-handle", result.stdout)
        self.assertNotIn("ignored.txt", result.stdout)

    def test_public_identity_is_allowed(self):
        (self.repo / "tracked.txt").write_text("Public User public@example.test\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "tracked.txt"], check=True)
        result = self.run_check()
        self.assertEqual(result.returncode, 0)

    def test_private_git_identity_fails_without_file_leak(self):
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "secret@example.test"], check=True)
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("git-config:1 gitIdentity", result.stdout)
        self.assertNotIn("secret@example.test", result.stdout)

    def test_private_input_must_keep_public_fallback(self):
        (self.repo / "flake.lock").write_text(json.dumps({"nodes": {
            "private-config": {"locked": {"path": "/private/location"},
                               "original": {"path": "./lib/private-defaults"}}
        }}))
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("flake.lock:1 privateInput", result.stdout)
        self.assertNotIn("/private/location", result.stdout)

    def test_missing_config_fails_closed(self):
        (self.repo / "docs/private-config/settings.json").unlink()
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read valid private config", result.stderr)


if __name__ == "__main__":
    unittest.main()

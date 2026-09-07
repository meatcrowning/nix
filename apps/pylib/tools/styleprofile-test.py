#!/usr/bin/env python3
"""Pure-stdlib regression harness for the StyleProfile apply contract.

It uses only a temporary directory and a deterministic monotonic clock; it
does not inspect or alter the live desktop, profile, wallpaper, or session.
"""

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from styleprofile import ApplyTrace, ProfileError, StyleProfile, read_profile, write_profile  # noqa: E402

DIGEST = "a" * 64
PROFILE = StyleProfile(7, "/wallpapers/night.png", DIGEST, "scale", "b" * 64,
                       "#Cc4400", "OxygenDarkFlat", "c" * 64)
fails = []


def check(name, condition):
    print(("  ok   " if condition else "  FAIL ") + name)
    if not condition:
        fails.append(name)


def rejects(name, data):
    try:
        StyleProfile.from_dict(data)
    except ProfileError:
        check(name, True)
    else:
        check(name, False)


print("canonical profile")
raw = PROFILE.canonical_json()
check("canonical JSON ends with one newline", raw.endswith(b"\n") and raw.count(b"\n") == 1)
check("digest is stable", PROFILE.digest == PROFILE.digest)
decoded = json.loads(raw)
check("round trip preserves all fields", StyleProfile.from_dict(decoded) == PROFILE)
check("schema version is explicit", decoded["schemaVersion"] == 1)

print("validation")
bad = PROFILE.to_dict()
bad["wallpaper"]["path"] = "relative.png"
rejects("relative wallpaper path is rejected", bad)
bad = PROFILE.to_dict()
bad["palette"]["sha256"] = "UPPER" * 13
rejects("non-canonical digest is rejected", bad)
bad = PROFILE.to_dict()
bad["generation"] = 0
rejects("zero generation is rejected", bad)

print("atomic profile store")
with tempfile.TemporaryDirectory(prefix="styleprofile-test-") as temporary:
    path = Path(temporary) / "state" / "active.json"
    write_profile(path, PROFILE)
    check("read returns what was written", read_profile(path) == PROFILE)
    check("store is private", (path.stat().st_mode & 0o777) == 0o600)

print("monotonic baseline trace")
ticks = iter((1_000_000_000, 1_012_500_000, 1_040_000_000))
trace = ApplyTrace(lambda: next(ticks))
trace.mark("prepared", "cache hit")
trace.mark("complete", "all required participants acknowledged")
report = trace.report()
check("trace measures phases from one monotonic origin", report["events"][0]["elapsedMs"] == 12.5)
check("trace reports final duration", report["totalMs"] == 40.0)

if fails:
    print(f"styleprofile-test: {len(fails)} failure(s)", file=sys.stderr)
    raise SystemExit(1)
print("styleprofile-test: all checks passed")

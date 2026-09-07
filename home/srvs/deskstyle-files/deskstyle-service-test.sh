#!/usr/bin/env bash
# Static contract check: deliberately does not start a user D-Bus service.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SERVICE="$ROOT/home/srvs/deskstyle-files/deskstyle-service.py"

temp="$(mktemp)"
trap 'rm -f "$temp"' EXIT
python3 "$SERVICE" --print-interface > "$temp"
for term in Apply GetStatus Progress Completed Superseded Failed; do
    rg -F "$term" "$temp" >/dev/null
done

# The controller must warm and validate side-effect-free cache data before it
# reaches the live writer.  The actual D-Bus service is deliberately not
# started in this harness.
rg -F 'prepared_profile(wallpaper)' "$SERVICE" >/dev/null
rg -F '"--prepared", str(wallpaper)' "$SERVICE" >/dev/null
rg -F '"preparing"' "$SERVICE" >/dev/null

WAL="$ROOT/home/srvs/wal-files/wal-set.sh"
SCHEME="$ROOT/home/srvs/wal-files/plasma-scheme.py"
bash -n "$WAL"
python3 -m py_compile "$SCHEME"
rg -F -- '--apply-file' "$WAL" "$SCHEME" >/dev/null
rg -F 'prepared scheme unavailable, re-minting' "$WAL" >/dev/null

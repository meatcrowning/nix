#!/usr/bin/env bash
# Static contract check: deliberately does not start a user D-Bus service.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SERVICE="$ROOT/home/srvs/deskstyle-files/deskstyle-service.py"

temp="$(mktemp)"
trap 'rm -f "$temp"' EXIT
python3 "$SERVICE" --print-interface > "$temp"
for term in Apply SetScheme GetStatus Progress Completed Superseded Failed; do
    rg -F "$term" "$temp" >/dev/null
done

# The controller must warm and validate side-effect-free cache data before it
# reaches the live writer.  The actual D-Bus service is deliberately not
# started in this harness.
rg -F 'prepared_profile(wallpaper, selected_scheme)' "$SERVICE" >/dev/null
rg -F '"--prepared", "--scheme", selected_scheme, str(wallpaper)' "$SERVICE" >/dev/null
rg -F '"preparing"' "$SERVICE" >/dev/null
rg -F 'Path.home() / "Pictures" / "Wallpapers"' "$SERVICE" >/dev/null
rg -F 'LIVE_SCHEMES = frozenset(("OxygenDarkFlat", "OxygenLightFlat", "OxygenMixed"))' "$SERVICE" >/dev/null
rg -F 'read_profile(PROFILE_PATH).wallpaper_path' "$SERVICE" >/dev/null
rg -F 'shutil.which("kreadconfig6")' "$SERVICE" >/dev/null

WAL="$ROOT/home/srvs/wal-files/wal-set.sh"
SCHEME="$ROOT/home/srvs/wal-files/plasma-scheme.py"
bash -n "$WAL"
python3 -m py_compile "$SCHEME"
rg -F -- '--apply-file' "$WAL" "$SCHEME" >/dev/null
rg -F 'prepared scheme unavailable, re-minting' "$WAL" >/dev/null
rg -F 'systemctl --user start plasma-panel-surface.service' "$WAL" >/dev/null
rg -F 'org.kde.PlasmaShell.evaluateScript' "$WAL" >/dev/null
rg -F 'deskstyle-wallpaper-ok:' "$WAL" >/dev/null
rg -F '"$HOME/.nix-profile/bin/qdbus"' "$WAL" >/dev/null
rg -F '/usr/bin/qdbus6' "$WAL" >/dev/null
rg -F 'systemd-run --user --quiet --no-block --collect' "$WAL" >/dev/null
rg -F 'LIVE_SCHEME="$PREPARED_SCHEME"' "$WAL" >/dev/null
rg -F '.plasma-scheme.lock' "$WAL" "$ROOT/home/srvs/wal-files/plasma-scheme-watch.sh" >/dev/null
if rg -F 'selected color scheme changed during preparation' "$WAL" >/dev/null; then
    echo "wal-set still rejects an explicit Style scheme switch" >&2
    exit 1
fi

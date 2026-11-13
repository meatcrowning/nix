#!/usr/bin/env bash
# Offscreen UI harness: both faces, both backends, fixture CLIs only.
#
#   apps/coder/tools/ui-test.sh [OUTDIR]
#
# Runs main.py --selftest under QT_QPA_PLATFORM=offscreen with scratch HOME
# state, a scratch Claude store and CODER_FIXTURES, so no CLI, account,
# session store, notification or window on the real screen is touched. Each
# run prints CODER_REPORT JSON and writes a PNG into OUTDIR for the user's
# visual check. QML warnings fail the run.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
APP=$(dirname "$HERE")
REPO=$(cd "$APP/../.." && pwd)
OUT=${1:-$(mktemp -d -t coder-ui-XXXXXX)}
mkdir -p "$OUT"

export QT_QPA_PLATFORM=offscreen
unset WAYLAND_DISPLAY DISPLAY
if [ -f /etc/fedora-release ]; then
  # Fedora's Qt aborts on the Nix plugin paths a Nix-wrapped parent (Konsole)
  # exports; the book wrapper clears the same set.
  unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QML2_IMPORT_PATH QML_IMPORT_PATH \
        NIXPKGS_QT6_QML_IMPORT_PATH LD_LIBRARY_PATH
fi
# A private session bus: the KDE platform theme segfaults building a menubar
# offscreen against the live bus, and nothing here may reach his bus anyway.
unset DBUS_SESSION_BUS_ADDRESS
# shellcheck source=/dev/null
. "$REPO/tools/lib/session-guard.sh"
sg_require_offscreen

SCRATCH=$(mktemp -d -t coder-ui-state-XXXXXX)
trap 'rm -rf "$SCRATCH"' EXIT
mkdir -p "$SCRATCH/xdg-runtime" "$SCRATCH/claude-projects"
chmod 700 "$SCRATCH/xdg-runtime"
export XDG_RUNTIME_DIR="$SCRATCH/xdg-runtime"
export XDG_STATE_HOME="$SCRATCH/state"
export CODER_STATE="$SCRATCH/state/coder/state.json"
export CODER_CLAUDE_PROJECTS="$SCRATCH/claude-projects"
export CODER_FIXTURES="$APP/fixtures"
export CODER_NO_NOTIFY=1
export CODER_FAKE_MS=1
export KDESHELL_STATE="$SCRATCH/kdeshell.ini"

if [ -x /usr/bin/python3 ] && [ -f /etc/fedora-release ]; then
  PY=/usr/bin/python3                  # book: the app's own interpreter
else
  PY=${CODER_PY:-$(command -v coder-qtenv >/dev/null && echo "coder-qtenv python3" || echo python3)}
fi

fail=0
run() {   # face backend prompts fixture
  local face=$1 backend=$2 prompts=$3 fixture=${4:-}
  local shot="$OUT/$face-$backend${fixture:+-${fixture%.jsonl}}.png"
  local log="$OUT/$face-$backend${fixture:+-${fixture%.jsonl}}.log"
  if ! env CODER_DRIVE="$backend" CODER_PROMPTS="$prompts" CODER_SHOT="$shot" CODER_MENUS=1 \
       ${fixture:+CODER_FIXTURE_${backend^^}=$fixture} \
       dbus-run-session -- $PY "$APP/main.py" --selftest --face="$face" >"$log" 2>&1; then
    echo "FAIL $face $backend ${fixture:-}: see $log"
    fail=1
  fi
  if ! grep -q '^CODER_REPORT ' "$log"; then
    echo "FAIL $face $backend: no report"; tail -20 "$log"; fail=1; return
  fi
  grep '^CODER_REPORT ' "$log" | sed 's/^CODER_REPORT //' > "$log.json"
  $PY - "$log.json" "$backend" "${fixture:-}" <<'EOF' || fail=1
import json, sys
r = json.load(open(sys.argv[1]))
backend, fixture = sys.argv[2], sys.argv[3]
kinds = [i[0] for i in r.get("items", [])]
bad = []
if r.get("warnings"):
    bad.append("qml warnings: %s" % r["warnings"][:3])
if "assistant" not in kinds and "error" not in kinds:
    bad.append("no reply row: %s" % kinds)
if r.get("state") != "idle":
    bad.append("state %s" % r.get("state"))
if fixture == "" and "approval" not in kinds:
    bad.append("no approval row")
print(("FAIL " if bad else "ok   ") + "%s %s %s: %d rows, %s" % (
    r.get("face"), backend, fixture, len(kinds), "; ".join(bad) or r.get("usage", "")))
sys.exit(1 if bad else 0)
EOF
}

for face in plasma hypr; do
  run "$face" claude "Create b.txt with hi, then run rm a.txt"
  run "$face" codex "Create a file c.txt containing the word hi, then run the shell command ls.||Run the shell command: rm a.txt"
done
run plasma codex "Create a file c.txt containing the word hi, then run the shell command ls." codex-usage-limit.jsonl
run plasma claude "Write the numbers" claude-two-turns.jsonl

echo "shots and logs: $OUT"
exit $fail

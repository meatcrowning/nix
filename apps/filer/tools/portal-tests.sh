#!/usr/bin/env bash
# Regression suite for filer's FileChooser portal backend (../portal.py) and
# picker mode (../pick.py). Run it after touching either.
#
#   apps/filer/tools/portal-tests.sh
#
# NOTHING HERE TOUCHES THE USER'S DESKTOP, and that is a requirement, not a
# nicety: the way you would "obviously" test a file-picker backend — open a real
# dialog — is the one thing you must not do, because a malformed response hangs
# the application that asked. So:
#
#   portal-test.py   the D-Bus contract, on a PRIVATE bus (dbus-run-session)
#                    against a stub delegate backend and a stub `filer`.
#   pick-test.py     the real qml/Main.qml + real Picker, loaded under
#                    QT_QPA_PLATFORM=offscreen. No window is ever mapped.
#   e2e-test.py      the real portal.py spawning the real `filer --pick`
#                    (offscreen), to cover the seam between the two — that a
#                    live OpenFile starts the picker and that Close() aborts it
#                    into a clean "cancelled" rather than a hang.
#
# The suite is deliberately heavy on the failure paths (cancel, crash, missing
# binary, Close mid-flight), because every one of them is a potential hang and a
# hang is worse than a wrong answer.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${FILER_TEST_PYTHON:-/usr/bin/python3}"
TMP="$(mktemp -d -t filer-portal-tests-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

fail=0
run() {
  local name="$1"; shift
  echo
  echo "=== $name ==="
  if "$@"; then :; else fail=1; echo "--- $name FAILED ---"; fi
}

run "picker (offscreen QML)"    env T_TMP="$TMP" "$PY" "$HERE/pick-test.py"
run "portal backend (private bus)" \
    env T_TMP="$TMP" dbus-run-session -- "$PY" "$HERE/portal-test.py"
run "end-to-end seam (private bus)" \
    env T_TMP="$TMP" dbus-run-session -- "$PY" "$HERE/e2e-test.py"

echo
if [ "$fail" -ne 0 ]; then
  echo "PORTAL SUITE FAILED"
  exit 1
fi
echo "portal suite OK"

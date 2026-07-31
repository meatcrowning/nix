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
# TWO interpreters, because the two halves need different modules and on top
# they live in different wrappers: the picker needs PySide6 (`filer`'s), the
# portal needs gi (`filer-portal`'s). `/usr/bin/python3` is book's answer to
# both and does not exist on top, so hardcoding it made the suite unrunnable
# there — borrow from the wrappers, exactly as the surfer harnesses do, and keep
# the Fedora path as the fallback.
_wrapped_python() {   # $1 = wrapper on PATH
  local w; w="$(command -v "$1")" || return 1
  sed -n 's|^exec "\{0,1\}\(/nix/store/[^" ]*/bin/python3\)"\{0,1\} .*|\1|p' \
      "$(readlink -f "$w")" | head -1
}
PY="${FILER_TEST_PYTHON:-$(_wrapped_python filer)}"; PY="${PY:-/usr/bin/python3}"
PYGI="${FILER_TEST_PYTHON_GI:-$(_wrapped_python filer-portal)}"; PYGI="${PYGI:-/usr/bin/python3}"
for p in "$PY" "$PYGI"; do
  [ -x "$p" ] || { echo "no usable python3 ($p) — set FILER_TEST_PYTHON[_GI]"; exit 1; }
done
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
    env T_TMP="$TMP" dbus-run-session -- "$PYGI" "$HERE/portal-test.py"
run "end-to-end seam (private bus)" \
    env T_TMP="$TMP" FILER_TEST_PYTHON="$PY" dbus-run-session -- "$PYGI" "$HERE/e2e-test.py"

echo
if [ "$fail" -ne 0 ]; then
  echo "PORTAL SUITE FAILED"
  exit 1
fi
echo "portal suite OK"

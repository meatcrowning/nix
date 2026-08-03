#!/bin/sh
# Exercise home/prog/ly-files/hypr-supervise (book's session crash net)
# against stub compositors in an isolated HOME. Never touches the live
# session, the real compositor, or ~/.local/state. Run after editing the
# wrapper: the supervisor is what decides whether a bad plugin build costs a
# relog, so a regression here is invisible until the next crash.
set -u
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sup="$here/../home/prog/ly-files/hypr-supervise"
[ -x "$sup" ] || { echo "harness: $sup not executable" >&2; exit 2; }

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT INT TERM
mkdir -p "$T/home" "$T/bin"

# stub compositor: pops one exit code per run from "$STUB_RCS", records runs
cat > "$T/bin/compositor" <<'EOF'
#!/bin/sh
echo run >> "$STUB_COUNT"
code=$(head -1 "$STUB_RCS")
tail -n +2 "$STUB_RCS" > "$STUB_RCS.tmp" && mv "$STUB_RCS.tmp" "$STUB_RCS"
exit "${code:-0}"
EOF
chmod +x "$T/bin/compositor"

# stub watchdog: records that it was handed the session, with the args
cat > "$T/bin/watchdog" <<'EOF'
#!/bin/sh
echo "watchdog:$*" > "$STUB_WATCHDOG_CALL"
exit 0
EOF
chmod +x "$T/bin/watchdog"

fails=0
ok()  { printf 'ok:   %s\n' "$1"; }
bad() { printf 'FAIL: %s\n' "$1"; fails=$((fails + 1)); }
check() { # label expected actual
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected [$2], got [$3])"; fi
}
st() { echo "$T/home/.local/state/hyprvtb"; }
run_sup() { # runs the supervisor with the given exit-code list; captures $?
  : > "$T/count"; printf '%s\n' "$1" > "$T/rcs"; : > "$T/watchdog-call"
  HOME="$T/home" STUB_RCS="$T/rcs" STUB_COUNT="$T/count" \
    STUB_WATCHDOG_CALL="$T/watchdog-call" \
    HYPR_SUPERVISE_BIN="$T/bin/compositor" HYPR_SUPERVISE_WATCHDOG="$T/bin/watchdog" \
    "$sup" --some-arg
  SUP_RC=$?
}

# --- clean exit (rc=0) ends the session, no breadcrumb -----------------------
run_sup 0
check "clean exit returns 0"           0 "$SUP_RC"
check "clean exit ran compositor once" 1 "$(wc -l < "$T/count")"
check "clean exit leaves no crashed-with" no "$([ -e "$(st)/crashed-with" ] && echo yes || echo no)"
check "clean exit logged session over"  1 "$(grep -c 'clean exit — session over' "$(st)/supervise.log")"

# --- one crash then a clean exit: restarts, blames the plugin, survives ------
printf '/nix/store/xxxx-libhyprvtb.so\n' > "$T/loaded"
: > "$(st)/loaded"
cp "$T/loaded" "$(st)/loaded"
run_sup "1
0"
check "mixed restarts then exits 0"    0 "$SUP_RC"
check "mixed ran compositor twice"     2 "$(wc -l < "$T/count")"
check "mixed wrote crashed-with"       1 "$([ -e "$(st)/crashed-with" ] && echo 1 || echo 0)"
check "mixed blamed the loaded plugin" "$(cat "$T/loaded")" "$(cat "$(st)/crashed-with")"
check "mixed never handed to watchdog" 0 "$(wc -c < "$T/watchdog-call")"
check "mixed logged the blame"         1 "$(grep -c 'UNCLEAN exit (rc=1) — blaming plugin' "$(st)/supervise.log")"

# --- three crashes: hands over to start-hyprland (safe mode), args intact ----
rm -f "$(st)/crashed-with"
run_sup "1
1
1"
check "3 crashes ran compositor 3 times" 3 "$(wc -l < "$T/count")"
check "3 crashes handed to watchdog"     "watchdog:--some-arg" "$(cat "$T/watchdog-call")"
check "3 crashes wrote crashed-with"     1 "$([ -e "$(st)/crashed-with" ] && echo 1 || echo 0)"
check "3 crashes logged the handover"    1 "$(grep -c '3 crashes in one session — handing over' "$(st)/supervise.log")"

# --- crash with no plugin recorded: no breadcrumb, but still supervised -------
rm -f "$(st)/loaded" "$(st)/crashed-with"
run_sup "1
1
1"
check "no-loaded ran compositor 3 times"  3 "$(wc -l < "$T/count")"
check "no-loaded left no crashed-with"    no "$([ -e "$(st)/crashed-with" ] && echo yes || echo no)"
check "no-loaded logged the gap"          3 "$(grep -c 'no plugin was recorded as loaded' "$(st)/supervise.log")"
check "no-loaded still handed to watchdog" "watchdog:--some-arg" "$(cat "$T/watchdog-call")"

echo
if [ "$fails" -eq 0 ]; then
  echo "hypr-supervise: all checks passed"
  exit 0
fi
echo "hypr-supervise: $fails check(s) FAILED"
exit 1

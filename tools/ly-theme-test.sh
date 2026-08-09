#!/usr/bin/env bash
# ly-theme-test.sh — the greeter theming must never take the login down.
#
# ly-theme.sh is the runtime half of "the greeter follows the wallpaper": it
# rewrites the six colour keys wal-set owns in /var/lib/ly/config.ini (itself
# a lam-writable copy of the NixOS module's config, symlinked at
# /etc/ly/config.ini). The contract this harness pins:
#
#   1. the six colour keys become the palette-derived 0xSSRRGGBB values, and
#      ONLY those keys change — the load-bearing session keys (setup_cmd,
#      waylandsessions, ...) must survive byte-for-byte, because a greeter
#      that loses its session paths is a login that cannot complete;
#   2. a missing or unwritable config is a benign skip (exit 0) — book, or a
#      machine whose activation never seeded the file — never an error;
#   3. a key absent from the file is NOT added: ly-theme.sh must never grow
#      the module-owned config.
#
# Usage: tools/ly-theme-test.sh   (exit 0 = every check passed)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../home/srvs/wal-files/ly-theme.sh"
[ -f "$SCRIPT" ] || { echo "FATAL: $SCRIPT not found" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/ly-theme-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

FAILS=0
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILS=$((FAILS + 1)); }

# A faithful slice of the NixOS module's output (the generated config.ini is
# plain `key=value` lines — see /etc/ly/config.ini on top).
cat > "$WORK/config.ini" <<'INI'
animation=colormix
border_fg=0x00CC4400
brightness_down_cmd=/nix/store/ghfvmywa3hp31f2pglr2d39iy8b7hgai-brightnessctl-0.5.1/bin/brightnessctl -q -n s 10%-
colormix_col1=0x00CC4400
colormix_col2=0x0054382A
colormix_col3=0x20000000
error_fg=0x01FA5C0C
fg=0x00E08E65
path=/run/current-system/sw/bin
setup_cmd=/nix/store/rdwccx96nwc32n4a36pkcy851j4jclww-xsession-wrapper
waylandsessions=/nix/store/4z2v9hvgyj86msx9knfsrh576rva6ma5-desktops/share/wayland-sessions
INI
cp "$WORK/config.ini" "$WORK/expected.ini"

# --- case 1: colours rewritten, load-bearing keys untouched ------------------
LY_CONFIG="$WORK/config.ini" "$SCRIPT" ebcd9b 544c3a df8964 >/dev/null
ok=1
for kv in "border_fg=0x00EBCD9B" "colormix_col1=0x00EBCD9B" "colormix_col2=0x00544C3A" \
          "colormix_col3=0x20000000" "error_fg=0x01DF8964" "fg=0x00EBCD9B"; do
    grep -qx "$kv" "$WORK/config.ini" || { ok=0; echo "  missing: $kv"; }
done
[ "$ok" = 1 ] && pass "case 1: six colour keys rewritten from the palette" \
             || fail "case 1: colour keys"
# load-bearing keys must match the seeded file exactly
grep -q "^setup_cmd=/nix/store/rdwccx96nwc32n4a36pkcy851j4jclww-xsession-wrapper$" "$WORK/config.ini" \
    && grep -q "^waylandsessions=/nix/store/4z2v9hvgyj86msx9knfsrh576rva6ma5-desktops/share/wayland-sessions$" "$WORK/config.ini" \
    && grep -q "^animation=colormix$" "$WORK/config.ini" \
    && pass "case 1: load-bearing keys untouched" \
    || fail "case 1: load-bearing keys"

# --- case 2: missing config is a benign skip ---------------------------------
out="$(LY_CONFIG="$WORK/nonexistent.ini" "$SCRIPT" ebcd9b 544c3a df8964 2>&1)"
[ $? -eq 0 ] && echo "$out" | grep -q "skipping" \
    && pass "case 2: missing config skips, exit 0" \
    || fail "case 2: missing config ($out)"

# --- case 2b: unwritable config is a benign skip ------------------------------
chmod 444 "$WORK/config.ini"
out="$(LY_CONFIG="$WORK/config.ini" "$SCRIPT" ebcd9b 544c3a df8964 2>&1)"
[ $? -eq 0 ] && echo "$out" | grep -q "skipping" \
    && pass "case 2b: unwritable config skips, exit 0" \
    || fail "case 2b: unwritable config ($out)"
chmod 644 "$WORK/config.ini"

# --- case 3: never adds a key the module file does not have -------------------
cp "$WORK/expected.ini" "$WORK/min.ini"
grep -v "^colormix_col3=" "$WORK/min.ini" > "$WORK/min.ini.tmp" && mv "$WORK/min.ini.tmp" "$WORK/min.ini"
LY_CONFIG="$WORK/min.ini" "$SCRIPT" ebcd9b 544c3a df8964 >/dev/null
if grep -q "^colormix_col3=" "$WORK/min.ini"; then
    fail "case 3: added a key that was not in the module file"
else
    pass "case 3: absent key is not added"
fi

# --- case 4: missing args are an error ----------------------------------------
LY_CONFIG="$WORK/config.ini" "$SCRIPT" ebcd9b 544c3a >/dev/null 2>&1
[ $? -eq 1 ] && pass "case 4: missing args exit 1" || fail "case 4: missing args"

# --- case 5: idempotence ------------------------------------------------------
cp "$WORK/expected.ini" "$WORK/idem.ini"
LY_CONFIG="$WORK/idem.ini" "$SCRIPT" ebcd9b 544c3a df8964 >/dev/null
cp "$WORK/idem.ini" "$WORK/idem.after1.ini"
LY_CONFIG="$WORK/idem.ini" "$SCRIPT" ebcd9b 544c3a df8964 >/dev/null
cmp -s "$WORK/idem.ini" "$WORK/idem.after1.ini" \
    && pass "case 5: second run is a no-op" \
    || fail "case 5: idempotence"

echo
if [ "$FAILS" -eq 0 ]; then
    echo "ly-theme-test: all checks passed"
    exit 0
else
    echo "ly-theme-test: $FAILS check(s) FAILED"
    exit 1
fi

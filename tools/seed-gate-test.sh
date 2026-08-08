#!/usr/bin/env bash
# seed-gate-test.sh — the seed-once pair must never deadlock the rebuild again.
#
# THE BUG THIS EXISTS FOR (2026-08-07). tools/seed-reconcile.sh runs from
# home.activation, so the switch itself brings a live seed-once file up to its
# nix source. That makes "source ahead of live" the normal state of every commit
# that touches hyprland.lua or Theme.qml. tools/preflight.sh nonetheless treated
# any drift as a hard FAIL — and preflight gates `sudo rebuild-top`, and the
# switch was the only thing that could clear the drift. So:
#
#   commit touches hyprland.lua -> drift -> preflight FAILS -> no switch
#                               -> no reconcile -> drift, forever
#
# Commit 4c1ed09 sat unlandable on top for a day for exactly that reason, and
# `nix-pull apply` — which rebuilds unattended through the same wrapper — could
# never have landed such a commit at all.
#
# The fix is a distinction, and this harness is what keeps it: benign drift the
# switch will resolve (exit 1) is REPORTED, and only a reconciler that cannot
# run (exit 2 — activation calls it with `|| true`, so it would silently skip
# the file) is fatal. Re-run this after touching seed-drift.sh, seed-reconcile.sh
# or preflight's seed block; collapsing the two codes back into one restores the
# deadlock with no error anywhere.
#
#   tools/seed-gate-test.sh            # hermetic exit-code contract + preflight
#   tools/seed-gate-test.sh --quick    # skip the two preflight runs (~30s)
#
# Touches nothing outside its own temp dir: every case runs against a throwaway
# XDG_CONFIG_HOME, never the live ~/.config.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIFT="$REPO/tools/seed-drift.sh"
RECON="$REPO/tools/seed-reconcile.sh"

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

TMP="$(mktemp -d)" || exit 1
trap 'rm -rf "$TMP"' EXIT

LUA_SRC="$REPO/home/prog/hypr-files/hyprland.lua"
QML_SRC="$REPO/home/prog/quickshell-files/Theme.qml"

fails=0
sec()  { printf '\n%s\n' "$*"; }
ok()   { printf '  ok   %s\n' "$*"; }
bad()  { printf '  FAIL %s\n' "$*"; fails=$((fails + 1)); }
want() { # want <label> <got> <expected>
    if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (exit $2, wanted $3)"; fi
}

# A fresh fake config root with both live files in whatever state we ask for.
# `sync` = byte-identical to source; the caller mutates from there.
mkcfg() {
    local d="$TMP/cfg.$1"
    rm -rf "$d"; mkdir -p "$d/hypr" "$d/quickshell"
    cp "$LUA_SRC" "$d/hypr/hyprland.lua"
    cp "$QML_SRC" "$d/quickshell/Theme.qml"
    printf '%s' "$d"
}

drift() { XDG_CONFIG_HOME="$1" "$DRIFT" "${@:2}" >"$TMP/out" 2>&1; echo "$?"; }

# --------------------------------------------------------------------------
sec "seed-reconcile's exit codes are a three-way distinction"

printf 'a\nb\n' >"$TMP/s"; printf 'a\n' >"$TMP/l"
bash "$RECON" --dry-run hyprland-lua "$TMP/s" "$TMP/l" >/dev/null 2>&1
want "would reconcile -> 1" "$?" 1

cp "$TMP/s" "$TMP/l"
bash "$RECON" --dry-run hyprland-lua "$TMP/s" "$TMP/l" >/dev/null 2>&1
want "in sync -> 0" "$?" 0

rm -f "$TMP/l"
bash "$RECON" --dry-run hyprland-lua "$TMP/s" "$TMP/l" >/dev/null 2>&1
want "never seeded -> 1" "$?" 1

bash "$RECON" --dry-run hyprland-lua "$TMP/absent" "$TMP/l" >/dev/null 2>&1
want "missing source -> 2" "$?" 2

printf 'a\n' >"$TMP/l"
bash "$RECON" --dry-run no-such-kind "$TMP/s" "$TMP/l" >/dev/null 2>&1
want "unknown kind -> 2" "$?" 2

# The one that actually bit: book's activation had no awk, so the carry failed
# and every switch silently left the live Theme.qml behind.
printf 'x\n// >>> wal palette\nc: "#112233"\n// <<< wal palette\ny\n' >"$TMP/qs"
printf 'x\n// >>> wal palette\n// <<< wal palette\ny\nEXTRA\n'        >"$TMP/ql"
bash "$RECON" --dry-run theme-qml "$TMP/qs" "$TMP/ql" >/dev/null 2>&1
want "live wal block empty -> 2" "$?" 2

# --------------------------------------------------------------------------
sec "runtime-owned values survive a real reconcile"

# THE 2026-08-08 REGRESSION. carry()'s sed used `|` as its delimiter, which the
# alternation in `(true|false)` terminated — so both boolean carries errored
# (stderr only) and carried nothing, and every switch reverted title_rotated
# in the live hyprland.lua to the seed's value. Hyprland autoreloads that file,
# so the user's "horizontal" pick undid itself on every rebuild, silently:
# seed-drift masks these values on both sides, so no tripwire ever fired.
d="$TMP/carry"; rm -rf "$d"; mkdir -p "$d"
cp "$LUA_SRC" "$d/live.lua"
sed -i -E \
    -e 's/(\["title_rotated"\][[:space:]]*=[[:space:]]*)(true|false)/\1true/' \
    -e 's/(\["font_smooth"\][[:space:]]*=[[:space:]]*)(true|false)/\1true/' \
    -e 's/(\["shadow_alpha"\][[:space:]]*=[[:space:]]*)[0-9.]+/\10.35/' \
    -e 's/(\["font"\][[:space:]]*=[[:space:]]*)"[^"]*"/\1"Botis"/' \
    "$d/live.lua"
# Something structural only the source has, so the reconcile genuinely rewrites.
grep -v 'repo-updates.service' "$d/live.lua" >"$d/live2.lua" && mv "$d/live2.lua" "$d/live.lua"
XDG_CACHE_HOME="$d/cache" bash "$RECON" hyprland-lua "$LUA_SRC" "$d/live.lua" >/dev/null 2>&1
want "reconcile ran -> 0" "$?" 0
for probe in '\["title_rotated"\][[:space:]]*=[[:space:]]*true,' \
             '\["font_smooth"\][[:space:]]*=[[:space:]]*true,' \
             '\["shadow_alpha"\][[:space:]]*=[[:space:]]*0\.35,' \
             '\["font"\][[:space:]]*=[[:space:]]*"Botis",'; do
    grep -qE "$probe" "$d/live.lua" \
        && ok "carried: $probe" \
        || bad "NOT carried (or line corrupted): $probe"
done
grep -q 'repo-updates.service' "$d/live.lua" \
    && ok "structure still comes from the source" \
    || bad "source line missing after reconcile"

# --------------------------------------------------------------------------
sec "--pre-switch: benign drift is reported, not blocked"

cfg=$(mkcfg sync)
want "both files in sync -> 0" "$(drift "$cfg" --pre-switch)" 0

# THE REGRESSION. A pulled commit adds lines to the nix source; the live copy
# has not caught up because the switch that would catch it up is what we are
# gating. This must not be fatal.
cfg=$(mkcfg behind)
grep -v 'repo-updates.service' "$LUA_SRC" >"$cfg/hypr/hyprland.lua"
want "source ahead of live -> 1" "$(drift "$cfg" --pre-switch)" 1
grep -q 'will reconcile' "$TMP/out" \
    && ok "says the switch will reconcile it" \
    || bad "does not say the switch will reconcile it"

cfg=$(mkcfg liveonly)
printf '\n-- a hand edit on the wrong side\n' >>"$cfg/hypr/hyprland.lua"
want "live-only lines -> 1" "$(drift "$cfg" --pre-switch)" 1
grep -q 'REPLACED' "$TMP/out" \
    && ok "warns they will be replaced" \
    || bad "does not warn they will be replaced"

cfg=$(mkcfg unseeded)
rm -f "$cfg/hypr/hyprland.lua"
want "never seeded on this host -> 1" "$(drift "$cfg" --pre-switch)" 1

# --------------------------------------------------------------------------
sec "--pre-switch: a reconciler that cannot run IS fatal"

cfg=$(mkcfg broken)
awk '/\/\/ >>> wal palette/{print; skip=1; next} /\/\/ <<< wal palette/{skip=0} !skip{print}' \
    "$QML_SRC" >"$cfg/quickshell/Theme.qml"
want "switch would silently skip a file -> 2" "$(drift "$cfg" --pre-switch)" 2
grep -q 'CANNOT RUN' "$TMP/out" \
    && ok "names the file it would skip" \
    || bad "does not name the file it would skip"

# --------------------------------------------------------------------------
sec "the report mode is still the post-switch tripwire"

cfg=$(mkcfg report)
want "in sync -> 0" "$(drift "$cfg")" 0
cfg=$(mkcfg report2)
printf '\n-- drift\n' >>"$cfg/hypr/hyprland.lua"
want "drift -> 1" "$(drift "$cfg")" 1
want "--quiet still exits 1 on drift" "$(drift "$cfg" --quiet)" 1
[ -s "$TMP/out" ] && bad "--quiet printed output" || ok "--quiet prints nothing"

# --------------------------------------------------------------------------
if [ "$QUICK" -eq 1 ]; then
    sec "skipping the preflight runs (--quick)"
else
    sec "preflight itself: the deadlock case passes, the fault case fails"

    cfg=$(mkcfg pfbehind)
    grep -v 'repo-updates.service' "$LUA_SRC" >"$cfg/hypr/hyprland.lua"
    XDG_CONFIG_HOME="$cfg" "$REPO/tools/preflight.sh" >"$TMP/pf" 2>&1
    want "source ahead of live: preflight OK" "$?" 0

    cfg=$(mkcfg pfbroken)
    awk '/\/\/ >>> wal palette/{print; skip=1; next} /\/\/ <<< wal palette/{skip=0} !skip{print}' \
        "$QML_SRC" >"$cfg/quickshell/Theme.qml"
    XDG_CONFIG_HOME="$cfg" "$REPO/tools/preflight.sh" >"$TMP/pf" 2>&1
    want "reconciler cannot run: preflight FAILS" "$?" 1
fi

# --------------------------------------------------------------------------
if [ "$fails" -eq 0 ]; then
    printf '\nall cases pass\n'
    exit 0
fi
printf '\n%d case(s) FAILED\n' "$fails"
exit 1

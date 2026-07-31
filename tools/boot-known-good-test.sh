#!/usr/bin/env bash
# Exercise the known-good-boots recorder (sys/boot-known-good.nix) end to end
# against a THROWAWAY directory tree — never the real ESP, never the real
# /nix/var/nix/gcroots, never a reboot.
#
# The recorder honours KGB_ROOTS / KGB_BOOT / KGB_BOOTED / KGB_KEEP /
# KGB_MARGIN_MB / KGB_SKIP_TARGET_CHECK for exactly this purpose. Everything
# below runs unprivileged and touches nothing outside its own mktemp -d.
#
# Run after any change to sys/boot-known-good.nix.
#   ./tools/boot-known-good-test.sh
set -euo pipefail

cd "$(dirname "$0")/.."

fail=0
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; fail=1; }

echo "building the recorder..."
bin=$(nix build --no-link --print-out-paths \
        ".#nixosConfigurations.top.config.system.build.knownGoodBoots")/bin/known-good-boots
[ -x "$bin" ] || { echo "recorder not executable: $bin" >&2; exit 1; }
echo "recorder: $bin"

tmp=$(mktemp -d /tmp/kgb-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT

export KGB_ROOTS="$tmp/gcroots"
export KGB_BOOT="$tmp/boot"
export KGB_KEEP=3
export KGB_MARGIN_MB=0
export KGB_SKIP_TARGET_CHECK=1
mkdir -p "$KGB_ROOTS" "$KGB_BOOT/EFI" "$KGB_BOOT/loader/entries"

# Fake generations: a directory shaped like a nixos-system toplevel, with a
# bootspec naming a fake kernel and initrd. Nothing here is a real store path,
# which is fine — the recorder only reads and copies what boot.json names.
mkgen() {
  local n d
  n="$1"
  d="$tmp/store/${n}fakehash$(printf '%026d' "$n")-nixos-system-top-test"
  mkdir -p "$d"
  head -c 100000 /dev/urandom > "$d/bzImage"
  head -c 200000 /dev/urandom > "$d/initrd"
  : > "$d/init"; chmod +x "$d/init"
  cat > "$d/boot.json" <<EOF
{ "org.nixos.bootspec.v1": {
    "init": "$d/init",
    "initrd": "$d/initrd",
    "kernel": "$d/bzImage",
    "kernelParams": ["root=fstab", "loglevel=4"],
    "label": "NixOS test generation $n",
    "system": "x86_64-linux",
    "toplevel": "$d"
} }
EOF
  echo "$d"
}

record_as() {   # record_as <toplevel-dir>
  ln -sfn "$1" "$tmp/booted"
  # empty PATH: the recorder must carry every tool it uses in runtimeInputs
  PATH= KGB_BOOTED="$tmp/booted" "$bin" record
}

entries() { find "$KGB_BOOT/loader/entries" -name 'known-good-*.conf' | sort; }
roots()   { find "$KGB_ROOTS" -maxdepth 1 -type l | sort; }

echo
echo "1. a first boot is recorded"
g1=$(mkgen 1); record_as "$g1" 2>&1 | sed 's/^/     /'
[ "$(roots | wc -l)" = 1 ]   && ok "one gcroot"           || bad "gcroot count $(roots | wc -l)"
[ "$(entries | wc -l)" = 1 ] && ok "one loader entry"     || bad "entry count $(entries | wc -l)"
slot1=$(basename "$g1" | cut -d- -f1)
[ -s "$KGB_BOOT/EFI/known-good/$slot1/linux" ]  && ok "kernel copied to ESP" || bad "no kernel on ESP"
[ -s "$KGB_BOOT/EFI/known-good/$slot1/initrd" ] && ok "initrd copied to ESP" || bad "no initrd on ESP"
grep -q '^sort-key zz-known-good' "$(entries)" && ok "sorts below the nixos group" || bad "missing sort-key"
grep -q "^options  init=$g1/init root=fstab loglevel=4$" "$(entries)" \
  && ok "options carry init= plus the kernel params" || bad "bad options line: $(grep '^options' "$(entries)")"
grep -q '^title    NixOS known-good [0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' "$(entries)" \
  && ok "title is a date a human can read" || bad "bad title: $(grep '^title' "$(entries)")"
# the copies must be independent of the store path
cmp -s "$g1/bzImage" "$KGB_BOOT/EFI/known-good/$slot1/linux" \
  && ok "ESP kernel is a real copy, not a link" || bad "ESP kernel differs from source"

echo
echo "2. recording the same generation twice is a no-op"
record_as "$g1" 2>&1 | sed 's/^/     /'
[ "$(roots | wc -l)" = 1 ] && ok "still one gcroot" || bad "duplicate recorded"

echo
echo "3. the ring keeps only the newest three"
for n in 2 3 4 5; do
  sleep 1.1   # the gcroot name carries a 1s-resolution timestamp
  g=$(mkgen "$n"); record_as "$g" >/dev/null 2>&1
  eval "g$n=\$g"
done
[ "$(roots | wc -l)" = 3 ]   && ok "three gcroots"     || bad "gcroot count $(roots | wc -l)"
[ "$(entries | wc -l)" = 3 ] && ok "three entries"     || bad "entry count $(entries | wc -l)"
[ "$(find "$KGB_BOOT/EFI/known-good" -mindepth 1 -maxdepth 1 -type d | wc -l)" = 3 ] \
  && ok "three ESP slots" || bad "stale ESP slots left behind"
[ ! -e "$KGB_BOOT/EFI/known-good/$slot1" ] && ok "the oldest slot's files are gone" || bad "slot 1 leaked"
# shellcheck disable=SC2154
newest=$(basename "$g5" | cut -d- -f1)
[ -e "$KGB_BOOT/EFI/known-good/$newest" ] && ok "the newest slot is kept" || bad "newest slot missing"

echo
echo "4. a too-small ESP is declined, not half-written"
before=$(entries | wc -l)
g6=$(mkgen 6)
KGB_MARGIN_MB=999999 record_as "$g6" 2>&1 | sed 's/^/     /'
[ "$(entries | wc -l)" = "$before" ] && ok "no entry written when the ESP is too full" \
                                     || bad "wrote an entry with no room"
[ ! -e "$KGB_BOOT/EFI/known-good/$(basename "$g6" | cut -d- -f1)" ] \
  && ok "no half-copied slot left behind" || bad "partial slot left on the ESP"

echo
echo "5. a bootspec naming a missing kernel is declined"
before=$(entries | wc -l)
g7=$(mkgen 7); rm "$g7/bzImage"
record_as "$g7" 2>&1 | sed 's/^/     /'
[ "$(entries | wc -l)" = "$before" ] && ok "declined" || bad "recorded a generation with no kernel"

echo
echo "6. list reports what is pinned"
PATH= KGB_BOOTED="$tmp/booted" "$bin" list | sed 's/^/     /'

echo
echo "7. the recorder never names a nixos-* entry path"
grep -q 'nixos-.*\.conf' "$bin" && bad "the script references nixos-*.conf" \
                                || ok "leaves the generation entries alone"

echo
[ "$fail" = 0 ] && echo "PASS" || { echo "FAIL"; exit 1; }

#!/usr/bin/env bash
# Ask the question the whole containment strategy rests on: if we bumped
# Hyprland right now, what would break, and would it all be in vtbCompat.hpp?
#
# Builds hyprvtb against an arbitrary upstream Hyprland ref WITHOUT touching
# flake.nix, the pin, or the running system — nothing here is installed. Use it
# before deciding to bump, and to see the size of the port in advance.
#
#   ./bump-dry-run.sh              # against hyprwm/Hyprland main
#   ./bump-dry-run.sh v0.57.0      # against a tag
#   ./bump-dry-run.sh <sha>        # against a commit
#
# Reading the result:
#   - builds clean              -> that bump is free; edit the tag in flake.nix
#                                  and follow the ritual in ../PORTING.md.
#   - errors, all in vtbCompat.hpp -> the seam is doing its job. Port that one
#                                  file. Keep new spellings compatible with the
#                                  pinned version where you can, so both build.
#   - errors ANYWHERE else      -> a seam gap. Wrap that symbol in vtbCompat.hpp
#                                  and add it to the checkPhase grep in
#                                  ../default.nix, THEN do the port. Closing the
#                                  gap is the more valuable half of the work.
set -uo pipefail

REF="${1:-main}"
echo "building hyprvtb against github:hyprwm/Hyprland/$REF (nothing is installed)"
echo "first run for a given ref pulls or builds that Hyprland — this can take a while"

OUT=$(nix build --no-link --print-out-paths --impure --expr "
let
  upstream = builtins.getFlake \"github:hyprwm/Hyprland/$REF\";
  pkgs     = import (builtins.getFlake \"github:NixOS/nixpkgs/nixos-unstable\") {
               system = \"x86_64-linux\"; config.allowUnfree = true;
             };
  hl       = upstream.packages.x86_64-linux.hyprland;
in pkgs.callPackage $(cd "$(dirname "$0")/.." && pwd) {
     hyprland        = hl;
     hyprlandPlugins = pkgs.hyprlandPlugins.override { hyprland = hl; };
   }" 2>&1)
RC=$?

if [ $RC -eq 0 ]; then
  printf '\n\033[32mBUILDS CLEAN\033[0m against %s\n  %s\n' "$REF" "$(printf '%s\n' "$OUT" | tail -1)"
  exit 0
fi

DRV=$(printf '%s\n' "$OUT" | grep -o "/nix/store/[a-z0-9]*-hyprvtb-[^ ']*\.drv" | head -1)
if [ -z "$DRV" ]; then
  printf '\n\033[31mthe dry run failed before compiling\033[0m (bad ref? no network?):\n%s\n' "$OUT" | tail -20
  exit 1
fi

ERRS=$(nix log "$DRV" 2>&1 | sed 's/\x1b\[[0-9;]*[mK]//g' | grep -E "error:|SEAM VIOLATION" | sed 's/^ *> *//' | sort -u)
printf '\n\033[33mWOULD NOT BUILD\033[0m against %s:\n\n%s\n\n' "$REF" "$ERRS"

OUTSIDE=$(printf '%s\n' "$ERRS" | grep "^/build/hyprvtb/" | grep -v "^/build/hyprvtb/vtbCompat.hpp" || true)
if [ -z "$OUTSIDE" ]; then
  printf '\033[32mEvery error is in vtbCompat.hpp\033[0m — the seam held. Port that one file.\n'
else
  printf '\033[31mSEAM GAP\033[0m — these errors are outside vtbCompat.hpp:\n%s\n\nWrap those symbols in the seam and add them to the checkPhase grep first.\n' "$OUTSIDE"
fi
exit 1

#!/bin/sh
# preflight.sh — THE pre-rebuild gate. Run from anywhere before `sudo rebuild-top`.
#
# Mechanizes the ritual that previously lived only as prose in AGENTS.md:
#   1. Untracked *.nix/*.qml/*.lua/*.sh under sys// home/ — flake eval silently
#      ignores untracked files, so a brand-new module/panel file is missing from
#      the build unless git add-ed first. This is the #1 "my change did nothing".
#   2. Rootless eval of the top system — catches syntax/option errors before the
#      passwordless switch (~10s, no sudo needed).
#   3. seed-drift.sh — seed-once files (Theme.qml, hyprland.lua, hyprpaper.conf)
#      must have source and live copies in step.
# Exit nonzero on any failure; safe to run repeatedly.
set -u
REPO="${PREFLIGHT_REPO:-$HOME/nix}"
fail=0

untracked=$(git -C "$REPO" ls-files --others --exclude-standard -- sys home \
  | grep -E '\.(nix|qml|lua|sh)$')
if [ -n "$untracked" ]; then
  echo "FAIL: untracked files that flake eval will SILENTLY IGNORE (git add them):"
  printf '  %s\n' $untracked
  fail=1
fi

echo "eval: nixosConfigurations.top ..."
if ! nix eval --raw "$REPO#nixosConfigurations.top.config.system.build.toplevel.drvPath" >/dev/null; then
  echo "FAIL: system eval failed"
  fail=1
fi

if ! "$REPO/tools/seed-drift.sh" --quiet; then
  echo "FAIL: seed-once drift (run tools/seed-drift.sh for details)"
  fail=1
fi

[ "$fail" -eq 0 ] && echo "preflight OK"
exit "$fail"

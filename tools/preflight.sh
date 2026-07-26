#!/bin/sh
# preflight.sh — THE pre-rebuild gate. Run from anywhere before `sudo rebuild-top`.
#
# Mechanizes the ritual that previously lived only as prose in AGENTS.md:
#   1. Untracked *.nix/*.qml/*.lua/*.sh under sys// home/ — flake eval silently
#      ignores untracked files, so a brand-new module/panel file is missing from
#      the build unless git add-ed first. This is the #1 "my change did nothing".
#      Use `git add -N` (intent-to-add): verified enough for flake eval to read
#      the working-tree content, while staging NO content — see check 4.
#   4. Staged CONTENT in the shared index. Several agents and the user share one
#      checkout and therefore ONE .git/index, and a pathspec-less `git commit`
#      commits whatever is in it — so anyone's plain commit silently swallows
#      everyone else's staged work (this really happened: fcc7855). Warning
#      only, never fatal: staging is legitimate, leaving it staged is the risk.
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
  echo "FAIL: untracked files that flake eval will SILENTLY IGNORE."
  echo "      Mark them intent-to-add (stages no content, so a concurrent"
  echo "      pathspec-less commit cannot swallow them):"
  printf '  git add -N %s\n' $untracked
  fail=1
fi

# Staged content is at risk in a shared checkout: whoever runs a pathspec-less
# `git commit` next takes it, whether or not it is theirs. --diff-filter=d
# drops intent-to-add entries, which carry no content and are therefore safe.
staged=$(git -C "$REPO" diff --cached --name-only --diff-filter=d)
if [ -n "$staged" ]; then
  echo "WARN: content staged in the shared index — another agent's (or your own)"
  echo "      pathspec-less 'git commit' would sweep these into ITS commit:"
  printf '  %s\n' $staged
  echo "      Commit them now with an explicit pathspec:"
  echo "        git commit -m msg -- <paths>     # immune to a dirty index"
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

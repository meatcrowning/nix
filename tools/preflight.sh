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
#   3. seed-drift.sh — seed-once files (Theme.qml, hyprland.lua)
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

# 6. A deployed board-watch.py that is not the repo's. The watcher is a
#    home-manager unit, so a fix in the repo does NOTHING until the next
#    switch on that host — twice now a "correct" fix could not reach him, and
#    a stale watcher once ran an orchestrator with no timeout for 100 minutes.
#    Warning only: it is a deploy-lag fact, not a fault in the tree.
DEPLOYED="$HOME/.config/scripts/board-watch.py"
SRC="$REPO/home/srvs/board-watch-files/board-watch.py"
if [ -e "$DEPLOYED" ] && [ -e "$SRC" ] && ! cmp -s "$DEPLOYED" "$SRC"; then
  echo "WARN: deployed board-watch.py differs from the repo copy - the running"
  echo "      watcher is a rebuild behind (this host's switch deploys it)."
fi

# 5. The systemd user manager's compositor identity. Hyprland imports its own
#    HYPRLAND_INSTANCE_SIGNATURE/WAYLAND_DISPLAY into that manager-global store
#    at every startup, so a nested test compositor claims it — and, SIGKILLed by
#    the harnesses, never gives it back. A user unit then talks to a dead socket
#    and exits 0, which is invisible: wal-set.service would change the wallpaper
#    and silently not recolour anything. Warning only — it is a state-of-the-
#    machine fault, not a fault in the tree being built, and it is absent
#    entirely from a TTY or a non-Hyprland session (exit 3).
ENVCHK="$HOME/.config/scripts/hypr-session-env.sh"
if [ -x "$ENVCHK" ]; then
  out=$("$ENVCHK" --check 2>&1); rc=$?
  if [ "$rc" -eq 1 ]; then
    echo "WARN: $out"
  fi
fi

[ "$fail" -eq 0 ] && echo "preflight OK"
exit "$fail"

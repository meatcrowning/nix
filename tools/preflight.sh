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
#   3. seed-drift.sh --pre-switch — what this switch will do to the seed-once
#      files (Theme.qml, hyprland.lua). Reported, not blocked: the switch
#      reconciles them itself. Fatal only if the reconciler cannot run.
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

# 8. Tracked files carrying a LARGE uncommitted diff vs HEAD — the "mixed WIP"
#    smell. A file another spirit is mid-edit on, on top of your own change,
#    shows up here. The hazard: a pathspec commit takes the WHOLE working-tree
#    copy, so it silently sweeps their half-finished edits into your commit
#    (really happened: 9c1f477). This is a HEURISTIC — a big single change is
#    legitimate — so it warns and never fails (a false failure blocking a
#    rebuild would be worse than the bug); the HARD gate is tools/git-commit.sh,
#    which fronts every commit and refuses a plausibly-mixed path. Thresholds
#    gelded high here and tunable: GIT_PREFLIGHT_MAX_HUNKS / _MAX_LINES.
MH="${GIT_PREFLIGHT_MAX_HUNKS:-8}"
ML="${GIT_PREFLIGHT_MAX_LINES:-120}"
for f in $(git -C "$REPO" diff --name-only HEAD); do
  [ -f "$REPO/$f" ] || continue
  hunks=$(git -C "$REPO" diff --unified=0 HEAD -- "$f" | grep -c '^@@')
  churn=$(git -C "$REPO" diff --numstat HEAD -- "$f" | awk '{s=$1+$2} END{print s+0}')
  if [ "$hunks" -ge "$MH" ] || [ "$churn" -ge "$ML" ]; then
    echo "WARN: $f carries $hunks uncommitted hunks / $churn changed lines vs HEAD —"
    echo "      possibly another spirit's WIP in the same file. A pathspec commit"
    echo "      would sweep it all in. Commit through tools/git-commit.sh (or --hunks"
    echo "      to take only your part), not bare 'git commit -- $f'."
  fi
done

echo "eval: nixosConfigurations.top ..."
if ! nix eval --raw "$REPO#nixosConfigurations.top.config.system.build.toplevel.drvPath" >/dev/null; then
  echo "FAIL: system eval failed"
  fail=1
fi

# 3. The seed-once pair (hyprland.lua, Theme.qml) — but asked as "what will THIS
#    switch do?", not "is there drift?". Since 2026-08-05 the switch's own
#    activation reconciles both files, so source-ahead-of-live is the normal
#    state of any commit that touched one, and failing on it deadlocked the
#    repo: preflight gates `sudo rebuild-top`, and the switch was the only
#    thing that could clear the drift. Commit 4c1ed09 (four lines added to
#    hyprland.lua) was unlandable on top for that reason, and `nix-pull apply`
#    — which rebuilds unattended through this same wrapper — could never have
#    landed such a commit at all. So: exit 1 is informational, and only exit 2
#    (the reconciler CANNOT run, i.e. the switch would silently skip the file)
#    is fatal.
"$REPO/tools/seed-drift.sh" --pre-switch
case "$?" in
  0|1) ;;
  *)   echo "FAIL: the switch cannot reconcile a seed-once file (see above)"
       fail=1 ;;
esac

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

# 5. Residue from a test that leaked into his live session — a dead compositor
#    signature in the systemd user manager (the manager-global store every
#    Hyprland overwrites and a SIGKILLed nested one never gives back), a stale
#    hypr lock directory, a nested compositor still running, a sandbox left
#    standing. Warning only, by design: these are states of the machine, not
#    faults in the tree, and a false failure that blocks his rebuild is worse
#    than the bug. See AGENTS.md -> "Testing without interfering with the user".
"$REPO/tools/leak-check.sh" || true

# 7. Known-corrupt /nix/store paths, found by the weekly nix-store-integrity
#    timer (home/srvs/nix-store-integrity.nix). Bit rot in the store is silent
#    and surfaces as an eval error that reads like a config bug — a rebuild is
#    exactly the moment to know about it. Warning only: a rotted path off the
#    eval path breaks nothing, and repair is a deliberate act
#    (`sudo nix-store --repair-path <path>`), not something to block on.
NSI="${XDG_STATE_HOME:-$HOME/.local/state}/nix-store-integrity/corrupt.txt"
if [ -s "$NSI" ]; then
  still=$("$HOME/.config/scripts/nix-store-integrity.sh" --known 2>/dev/null | wc -l)
  if [ "$still" -gt 0 ]; then
    echo "WARN: $still /nix/store path(s) still fail their content hash - bit rot."
    echo "      Listed in $NSI; repair with:"
    echo "        sudo -A nix-store --repair-path <path>     # if substitutable"
    echo "      Background: docs/agents/nix-store-bitrot-extent.md"
  fi
fi

[ "$fail" -eq 0 ] && echo "preflight OK"
exit "$fail"

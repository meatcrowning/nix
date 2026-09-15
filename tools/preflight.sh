#!/bin/sh
# Pre-rebuild checks: source tracking, ownership, private configuration,
# flake evaluation, seed reconciliation, and deployment/session warnings.
# Run from any directory; PREFLIGHT_REPO and PREFLIGHT_FLAKE override ~/nix.
set -u
REPO="${PREFLIGHT_REPO:-$HOME/nix}"
FLAKE="${PREFLIGHT_FLAKE:-$REPO}"
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

# Ignore intent-to-add entries; warn about content in the shared index.
staged=$(git -C "$REPO" diff --cached --name-only --diff-filter=d)
if [ -n "$staged" ]; then
  echo "WARN: content staged in the shared index — another agent's (or your own)"
  echo "      pathspec-less 'git commit' would sweep these into ITS commit:"
  printf '  %s\n' $staged
  echo "      Commit them now with an explicit pathspec:"
  echo "        git commit -m msg -- <paths>     # immune to a dirty index"
fi

# Large diffs may contain mixed ownership. Warn here; git-commit.sh enforces
# explicit review. Thresholds remain configurable for legitimate large edits.
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

if ! python3 "$REPO/tools/privacy-check.py" --repo "$REPO"; then
  echo "FAIL: private identifiers or unsafe public Git identity detected"
  fail=1
fi

echo "eval: nixosConfigurations.top ..."
if ! "$REPO/tools/nix-private.sh" eval --raw "$FLAKE#nixosConfigurations.top.config.system.build.toplevel.drvPath" >/dev/null; then
  echo "FAIL: system eval failed"
  fail=1
fi

# Source-ahead drift is expected before activation reconciles mutable files.
# Exit 1 is informational; inability to reconcile is fatal.
"$REPO/tools/seed-drift.sh" --pre-switch
case "$?" in
  0|1) ;;
  *)   echo "FAIL: the switch cannot reconcile a seed-once file (see above)"
       fail=1 ;;
esac

# Deployed watcher drift is a rebuild warning, not a source failure.
DEPLOYED="$HOME/.config/scripts/board-watch.py"
SRC="$REPO/home/srvs/board-watch-files/board-watch.py"
if [ -e "$DEPLOYED" ] && [ -e "$SRC" ] && ! cmp -s "$DEPLOYED" "$SRC"; then
  echo "WARN: deployed board-watch.py differs from the repo copy - the running"
  echo "      watcher is a rebuild behind (this host's switch deploys it)."
fi

# Session leaks warn without blocking a rebuild; see root test-isolation rules.
"$REPO/tools/leak-check.sh" || true

# Warn about known store corruption; repair is a separate explicit action.
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

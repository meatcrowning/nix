#!/usr/bin/env bash
# Snapshot ~/nix/flake.lock into a rotating backup directory whenever it
# changes, keeping the newest $keep copies.
#
# Triggered two ways (see ../flake-lock-backup.nix):
#   - a .path unit on the file, so a change is captured within seconds
#   - a .timer, the backstop for changes that happened while logged out or
#     that the path unit missed
#
# Backups live in ~/.local/state/flake-lock-backup/ — machine-local state,
# nothing that syncs, nothing in any git tree. Names are timestamped and sort
# lexicographically, so pruning is just "keep the newest N".
#
# A run is a no-op when flake.lock is identical to the newest existing backup:
# the timer ticks against an unchanged file, and the path unit can fire on
# writes that did not change content (mtime churn from git operations).

set -uo pipefail

src="$HOME/nix/flake.lock"
dir="$HOME/.local/state/flake-lock-backup"
keep=20

[ -f "$src" ] || exit 0
mkdir -p "$dir" || exit 1

# Newest existing backup, if any.
newest=$(ls -1 "$dir"/flake.lock.* 2>/dev/null | sort | tail -n 1)

# Nothing changed since the last snapshot: cheap exit.
if [ -n "$newest" ] && cmp -s -- "$src" "$newest"; then
  exit 0
fi

stamp=$(date +%Y%m%d-%H%M%S-%N)
dest="$dir/flake.lock.$stamp"

if ! cp -- "$src" "$dest"; then
  echo "flake-lock-backup: failed to snapshot $src to $dest" >&2
  exit 1
fi
echo "flake-lock-backup: snapshot $dest"

# Prune: keep the newest $keep, drop the rest. Names sort chronologically, so
# "all but the last $keep lines" (GNU head -n -N, coreutils on both hosts) is
# exactly the oldest ones.
ls -1 "$dir"/flake.lock.* 2>/dev/null | sort | head -n -"$keep" | while read -r old; do
  rm -f -- "$old"
done

exit 0

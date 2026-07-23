#!/bin/sh
# wal-repo-sync.sh — auto-version dropped wallpapers.
#
# Fired by the wal-repo-sync.path unit whenever ~/Pictures/wall changes: copy any
# image files into the repo's versioned set (home/srvs/wal-files/wallpapers) and
# commit + push them, so a wallpaper dropped in on one machine shows up on the
# others after a pull. Deployed to ~/.config/scripts by home/srvs/wal.nix.
#
# SAFETY — this touches a shared repo the user hand-edits and leaves dirty, so it
# is deliberately paranoid:
#   * The commit is assembled in a THROWAWAY index (GIT_INDEX_FILE), seeded from
#     HEAD's tree and then `git add`-ing ONLY the wallpapers path. The real index
#     and working tree are never touched, so the user's other uncommitted ~/nix
#     edits can't be swept in — the commit contains wallpaper changes and nothing
#     else, by construction.
#   * The branch is advanced with a compare-and-swap on the old HEAD
#     (`git update-ref HEAD new old`); if HEAD moved underneath us (a concurrent
#     commit), we bail and let the next drop retry, never clobbering that commit.
#   * Additive only: files removed from ~/Pictures/wall are NOT removed from the
#     repo here (deletion stays a deliberate, manual act).
# Paths default to the live locations; the WAL_SYNC_* overrides exist only so the
# script can be exercised end-to-end against a throwaway repo in a test.
REPO="${WAL_SYNC_REPO:-$HOME/nix}"
WALL="${WAL_SYNC_WALL:-$HOME/Pictures/wall}"
REL="home/srvs/wal-files/wallpapers"
LOG="${WAL_SYNC_LOG:-$HOME/.cache/wal/repo-sync.log}"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date -Is) wal-repo-sync ==="

[ -d "$WALL" ] || { echo "no $WALL"; exit 0; }
[ -d "$REPO/.git" ] || { echo "no repo at $REPO"; exit 0; }
mkdir -p "$REPO/$REL"

# Coalesce a burst of drops (multi-file copy, an editor's temp-then-rename, etc.)
# into a single sync — the path unit may fire several times in quick succession.
sleep 3

# Mirror image files wall -> repo (add/update only). Re-copying an unchanged file
# is a no-op as far as git is concerned (it compares content, not mtime).
for f in "$WALL"/*; do
  [ -f "$f" ] || continue
  case "$(printf '%s' "${f##*/}" | tr '[:upper:]' '[:lower:]')" in
    *.png | *.jpg | *.jpeg | *.webp | *.bmp | *.gif) cp -p "$f" "$REPO/$REL/" ;;
  esac
done

cd "$REPO" || { echo "cd failed"; exit 0; }

base=$(git rev-parse HEAD 2>/dev/null) || { echo "no HEAD"; exit 0; }

idx=$(mktemp)
export GIT_INDEX_FILE="$idx"
git read-tree "$base"
git add -- "$REL"
if git diff-index --cached --quiet "$base" -- "$REL"; then
  echo "no new wallpapers"
  rm -f "$idx"
  exit 0
fi
# Human-readable list of the added/changed basenames for the commit message.
names=$(git diff-index --cached --name-only "$base" -- "$REL" \
  | while IFS= read -r p; do printf '%s ' "${p##*/}"; done)
tree=$(git write-tree)
unset GIT_INDEX_FILE
rm -f "$idx"

newc=$(printf 'wall: auto-add %s\n' "$names" | git commit-tree "$tree" -p "$base") \
  || { echo "commit-tree failed"; exit 0; }

if git update-ref HEAD "$newc" "$base"; then
  echo "committed: $names ($newc)"
else
  echo "HEAD moved during sync — skipped, will retry on next drop"
  exit 0
fi

if git push -q; then
  echo "pushed"
else
  echo "push FAILED — commit is local; will retry on next drop or resolve manually"
fi

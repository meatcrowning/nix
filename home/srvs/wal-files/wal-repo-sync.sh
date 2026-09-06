#!/bin/sh
# wal-repo-sync.sh — auto-version dropped wallpapers.
#
# Fired by the wal-repo-sync.path unit whenever ~/Pictures/wall changes: copy any
# image files into the repo's versioned set (home/srvs/wal-files/wallpapers) and
# commit + push them, together with the completed wallpaper selection, so a
# wallpaper dropped or picked on one machine shows up on the others after a
# pull. Deployed to ~/.config/scripts by home/srvs/wal.nix.
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
#   * The image set is reconciled both ways: a supported image removed from
#     ~/Pictures/wall is removed from the versioned source in the same focused
#     commit. Home Manager seeds that source on activation, so without this a
#     deleted image would return at the next rebuild.
# Paths default to the live locations; the WAL_SYNC_* overrides exist only so the
# script can be exercised end-to-end against a throwaway repo in a test.
REPO="${WAL_SYNC_REPO:-$HOME/nix}"
WALL="${WAL_SYNC_WALL:-$HOME/Pictures/wall}"
WALL_REL="home/srvs/wal-files/wallpapers"
SELECTOR_REL="home/srvs/wal-files/current-wallpaper"
LOG="${WAL_SYNC_LOG:-$HOME/.cache/wal/repo-sync.log}"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date -Is) wal-repo-sync ==="

[ -d "$WALL" ] || { echo "no $WALL"; exit 0; }
[ -d "$REPO/.git" ] || { echo "no repo at $REPO"; exit 0; }
mkdir -p "$REPO/$WALL_REL"

# Coalesce a burst of drops (multi-file copy, an editor's temp-then-rename, etc.)
# into a single sync — the path unit may fire several times in quick succession.
sleep 3

# Mirror supported image files wall -> repo. Re-copying an unchanged file is a
# no-op as far as git CONTENT is concerned, but git does track the exec bit —
# `cp -p` used to carry 755 modes over from ~/Pictures/wall, flipping every
# wallpaper to git-modified (mode-only) and keeping the tree permanently dirty.
# install -m 644 pins the mode so an unchanged file really is a no-op.
for f in "$WALL"/*; do
  [ -f "$f" ] || continue
  case "$(printf '%s' "${f##*/}" | tr '[:upper:]' '[:lower:]')" in
    *.png | *.jpg | *.jpeg | *.webp | *.bmp | *.gif) install -m 644 "$f" "$REPO/$WALL_REL/" ;;
  esac
done

# Deletion must reach the versioned source too. Restrict this to supported image
# files so sidecars or future metadata in the source directory are never removed
# just because they do not belong in the writable picker directory.
for f in "$REPO/$WALL_REL"/*; do
  [ -f "$f" ] || continue
  case "$(printf '%s' "${f##*/}" | tr '[:upper:]' '[:lower:]')" in
    *.png | *.jpg | *.jpeg | *.webp | *.bmp | *.gif)
      [ -e "$WALL/${f##*/}" ] || rm -f -- "$f"
      ;;
  esac
done

# wal-set.sh writes this only after a full apply, never for a picker preview.
# Accept a basename that names an image in both the writable set and the repo;
# anything else is ignored rather than allowing a local state file to escape
# the versioned wallpaper directory.
pick_file="$WALL/.current-wallpaper"
if [ -f "$pick_file" ]; then
  selected="$(tr -d '\r\n' < "$pick_file")"
  case "$selected" in
    ""|*/*|.|..)
      echo "invalid selected wallpaper ignored"
      ;;
    *)
      case "$(printf '%s' "$selected" | tr '[:upper:]' '[:lower:]')" in
        *.png | *.jpg | *.jpeg | *.webp | *.bmp | *.gif)
          if [ -f "$WALL/$selected" ] && [ -f "$REPO/$WALL_REL/$selected" ]; then
            printf '%s\n' "$selected" > "$REPO/$SELECTOR_REL"
          else
            echo "selected wallpaper is not in both sets; retaining selector"
          fi
          ;;
        *) echo "selected wallpaper has unsupported extension; retaining selector" ;;
      esac
      ;;
  esac
fi

cd "$REPO" || { echo "cd failed"; exit 0; }

base=$(git rev-parse HEAD 2>/dev/null) || { echo "no HEAD"; exit 0; }

# Bring the REAL index up to the current HEAD for exactly the paths HEAD advanced
# over since $base (the wallpapers we added, plus anything a rebase pulled in
# from the remote). The commit was assembled in a throwaway index, so the real
# index still sits at $base and would otherwise make `git status` report those
# paths as phantom staged deletions. Scoped by pathspec and index-only (never the
# working tree), so the user's unrelated staged/dirty edits survive as ordinary
# modifications. NUL-delimited so spaced filenames are safe.
sync_index() {
  git diff -z --name-only "$base" HEAD -- "$WALL_REL" "$SELECTOR_REL" | xargs -0 -r git reset -q --
}

idx=$(mktemp)
export GIT_INDEX_FILE="$idx"
git read-tree "$base"
git add -- "$WALL_REL" "$SELECTOR_REL"
if git diff-index --cached --quiet "$base" -- "$WALL_REL" "$SELECTOR_REL"; then
  echo "wallpaper set unchanged"
  rm -f "$idx"
  exit 0
fi
# Human-readable list of the added, changed, or removed basenames for the commit message.
names=$(git diff-index --cached --name-only "$base" -- "$WALL_REL" "$SELECTOR_REL" \
  | while IFS= read -r p; do printf '%s ' "${p##*/}"; done)
tree=$(git write-tree)
unset GIT_INDEX_FILE
rm -f "$idx"

newc=$(printf 'wall: sync %s\n' "$names" | git commit-tree "$tree" -p "$base") \
  || { echo "commit-tree failed"; exit 0; }

if git update-ref HEAD "$newc" "$base"; then
  echo "committed: $names ($newc)"
else
  echo "HEAD moved during sync — skipped, will retry on next drop"
  exit 0
fi

sync_index    # clear phantom staged deletions of the just-committed wallpapers

if git push -q; then
  echo "pushed"
else
  # Push rejected — most likely the remote advanced from another machine (the
  # exact multi-host case this feature exists for). Without integrating it the
  # stale local commit would wedge EVERY future drop. Rebase our auto-commit
  # onto the new remote head and retry once. --autostash tucks the user's
  # uncommitted edits away for the rebase and restores them after — it never
  # discards them (a rare truly-conflicting hunk is left as a recoverable stash,
  # not lost) — and the rebase advances HEAD, index and working tree together so
  # `git status` stays consistent (no phantom deletions of the pulled-in files).
  echo "push rejected — pull --rebase --autostash then retry"
  if git pull -q --rebase --autostash && git push -q; then
    echo "pushed after rebase"
  else
    git rebase --abort 2>/dev/null   # back out cleanly if a rebase is mid-flight
    echo "auto-rebase failed — commit is local; resolve manually (check: git stash list)"
  fi
fi

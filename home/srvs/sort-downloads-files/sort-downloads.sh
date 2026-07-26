#!/usr/bin/env bash
# Move finished image/video downloads out of ~/Downloads into ~/Pictures / ~/Videos.
#
# Triggered two ways (see ../sort-downloads.nix):
#   - a .path unit, so a file that lands while the desktop is up is filed within
#     the settle window
#   - a .timer, which is the backstop: the path unit only fires on change, so
#     anything that arrived while logged out, or that was still too fresh when
#     the watcher ran, gets picked up on the next tick
#
# Deliberate limits:
#   - top level of ~/Downloads only, regular files only. Downloads full of
#     extracted game/ROM directories stay untouched.
#   - a file must be SETTLE_SECS old before it moves, so a browser writing
#     straight to the final name isn't yanked mid-write. Partial-download
#     extensions are skipped outright on top of that.
#   - never overwrites: an existing target gets a " (n)" suffix.

set -uo pipefail

src="$HOME/Downloads"
pics="$HOME/Pictures"
vids="$HOME/Videos"

# How old (seconds) a file must be before it's considered done downloading.
SETTLE_SECS=90

image_exts="jpg jpeg png gif webp bmp tif tiff avif heic heif jxl ico svg"
video_exts="mp4 mkv webm mov avi wmv flv m4v mpg mpeg ogv 3gp ts m2ts"
# Extensions that mean "still downloading" no matter how old the file looks.
partial_exts="part crdownload download opdownload tmp !qb aria2 st filepart"

[ -d "$src" ] || exit 0

now=$(date +%s)
moved=0

contains() { # contains <needle> <space-separated haystack>
  case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# Pick a non-colliding destination path for a basename in a directory.
dest_for() {
  local dir=$1 base=$2 stem ext n candidate
  candidate="$dir/$base"
  [ -e "$candidate" ] || { printf '%s' "$candidate"; return; }

  case "$base" in
    *.*) stem="${base%.*}"; ext=".${base##*.}" ;;
    *)   stem="$base"; ext="" ;;
  esac
  n=1
  while [ -e "$dir/$stem ($n)$ext" ]; do
    n=$((n + 1))
  done
  printf '%s' "$dir/$stem ($n)$ext"
}

shopt -s nullglob
for f in "$src"/*; do
  [ -f "$f" ] || continue          # dirs, sockets, dangling symlinks
  base=${f##*/}
  case "$base" in .*) continue ;; esac

  ext=${base##*.}
  [ "$ext" = "$base" ] && continue # no extension at all
  ext=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')

  contains "$ext" "$partial_exts" && continue

  if contains "$ext" "$image_exts"; then
    target=$pics
  elif contains "$ext" "$video_exts"; then
    target=$vids
  else
    continue
  fi

  mtime=$(stat -c %Y "$f" 2>/dev/null) || continue
  [ $((now - mtime)) -lt "$SETTLE_SECS" ] && continue

  # Something still has it open for writing (a downloader that keeps the final
  # name from the start). Leave it for the next run.
  if command -v lsof >/dev/null 2>&1 && lsof -t -- "$f" >/dev/null 2>&1; then
    continue
  fi

  mkdir -p "$target" || continue
  dest=$(dest_for "$target" "$base")
  if mv -n -- "$f" "$dest"; then
    echo "sorted: $base -> ${dest#$HOME/}"
    moved=$((moved + 1))
  else
    echo "failed: $base" >&2
  fi
done

[ "$moved" -gt 0 ] && echo "sort-downloads: moved $moved file(s)"
exit 0

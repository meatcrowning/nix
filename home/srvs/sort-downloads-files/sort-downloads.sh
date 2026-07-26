#!/usr/bin/env bash
# Move finished image/video downloads out of ~/Downloads into ~/Pictures / ~/Videos.
#
# Triggered two ways (see ../sort-downloads.nix):
#   - a .path unit, so a file that lands while the desktop is up is filed within
#     seconds of the download finishing
#   - a .timer, the backstop for anything that arrived while logged out
#
# "Finished" is decided by STABILITY, not by age: a candidate must hold the same
# size+mtime across a poll interval and not be open in any process. A run that
# sees an in-flight download keeps polling until it settles (up to MAX_WAIT)
# rather than exiting — the path unit gets no second event once a download stops
# writing, so bailing out early would strand the file until the next timer tick.
#
# Deliberate limits:
#   - top level of ~/Downloads only, regular files only. Downloads full of
#     extracted game/ROM directories stay untouched.
#   - files with no extension are classified by MIME sniff (browser saves from
#     twitter/4chan land that way); files WITH an extension are classified by
#     extension only, so nothing surprising gets swept up.
#   - never overwrites: an existing target gets a " (n)" suffix.

set -uo pipefail

src="$HOME/Downloads"
pics="$HOME/Pictures"
vids="$HOME/Videos"

POLL_SECS=4     # gap between stability samples
MAX_WAIT=600    # give up waiting on a still-growing download after this long

image_exts="jpg jpeg png gif webp bmp tif tiff avif heic heif jxl ico svg"
video_exts="mp4 mkv webm mov avi wmv flv m4v mpg mpeg ogv 3gp ts m2ts"
# Extensions that mean "still downloading" no matter how stable the file looks.
partial_exts="part crdownload download opdownload tmp !qb aria2 st filepart"

[ -d "$src" ] || exit 0

moved=0

contains() { # contains <needle> <space-separated haystack>
  case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# Echo "pics", "vids", or nothing.
classify() {
  local f=$1 base=${1##*/} ext mime
  if [ "${base##*.}" != "$base" ]; then
    ext=$(printf '%s' "${base##*.}" | tr '[:upper:]' '[:lower:]')
    contains "$ext" "$partial_exts" && return
    contains "$ext" "$image_exts" && { echo pics; return; }
    contains "$ext" "$video_exts" && { echo vids; return; }
    return
  fi
  # No extension at all — sniff it.
  command -v file >/dev/null 2>&1 || return
  mime=$(file -b --mime-type -- "$f" 2>/dev/null)
  case "$mime" in
    image/*) echo pics ;;
    video/*) echo vids ;;
  esac
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

# "<size> <mtime>" for a file, empty if it vanished.
stamp() { stat -c '%s %Y' -- "$1" 2>/dev/null; }

busy() { # open for writing by some process?
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -t -- "$1" >/dev/null 2>&1
}

declare -A seen   # path -> stamp observed on the previous pass

shopt -s nullglob
waited=0
while :; do
  pending=0

  for f in "$src"/*; do
    [ -f "$f" ] || continue          # dirs, sockets, dangling symlinks
    base=${f##*/}
    case "$base" in .*) continue ;; esac

    kind=$(classify "$f")
    [ -n "$kind" ] || continue

    now=$(stamp "$f")
    [ -n "$now" ] || continue        # vanished under us

    if busy "$f" || [ "${seen[$f]-}" != "$now" ]; then
      seen[$f]=$now                  # first sighting, or it changed — recheck
      pending=1
      continue
    fi

    # Stable across a full poll interval and nobody has it open: it's done.
    case $kind in
      pics) target=$pics ;;
      vids) target=$vids ;;
    esac
    mkdir -p "$target" || continue
    dest=$(dest_for "$target" "$base")
    if mv -n -- "$f" "$dest"; then
      echo "sorted: $base -> ${dest#"$HOME"/}"
      moved=$((moved + 1))
      unset 'seen[$f]'
    else
      echo "failed: $base" >&2
    fi
  done

  [ "$pending" -eq 1 ] || break
  [ "$waited" -ge "$MAX_WAIT" ] && { echo "sort-downloads: gave up waiting on in-flight download(s)" >&2; break; }
  sleep "$POLL_SECS"
  waited=$((waited + POLL_SECS))
done

[ "$moved" -gt 0 ] && echo "sort-downloads: moved $moved file(s)"
exit 0

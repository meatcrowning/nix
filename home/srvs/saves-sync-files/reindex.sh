# Rebuild a Saves library's index when its posts changed since this host last
# indexed it. The index (saves.sqlite3) is not synced: each host builds its
# own from the synced files, so two hosts never fight over it.
data="$HOME/Projects/saves/data"
state="${XDG_STATE_HOME:-$HOME/.local/state}/saves-sync"
mkdir -p "$state"
status=0
for lib in bookmarked following kept; do
  dir="$data"
  arg=()
  if [ "$lib" != bookmarked ]; then dir="$data/$lib"; arg=("$lib"); fi
  [ -d "$dir" ] || continue
  # A library without one of these folders makes find exit 1; that is fine.
  sig=$(cd "$dir" && { find -L twitter instagram youtube soundcloud _order -type f \
          -printf '%p\t%s\t%T@\n' 2>/dev/null || true; } | LC_ALL=C sort | md5sum | cut -d' ' -f1)
  [ "$(cat "$state/$lib" 2>/dev/null)" = "$sig" ] && continue
  # A rebuild already running (the app's own after a fetch) makes this one
  # fail; the signature stays unrecorded and the next tick tries again.
  if saves index "${arg[@]}"; then
    echo "$sig" >"$state/$lib"
  else
    status=1
  fi
done
exit "$status"

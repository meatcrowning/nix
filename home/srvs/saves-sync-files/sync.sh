# Two-way sync of ~/Projects/saves/data between top and book (runs on top).
# unison carries files both ways; merge.py reconciles the stars/hidden marks,
# gallery-dl archives and account lists when both hosts changed them.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/saves-sync.lock"
flock -n 9 || { echo "another sync is running"; exit 0; }
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 book true 2>/dev/null; then
  echo "book is unreachable; nothing to sync"
  exit 0
fi
rc=0
unison saves || rc=$?
# 1 = skipped and 2 = failed items (a file busy or changed mid-transfer, or a
# missing youtube/media mount): the rest synced and the next tick retries.
# 3 = fatal: nothing synced.
[ "$rc" -ge 2 ] && echo "unison exited $rc" >&2
[ "$rc" -ge 3 ] && exit "$rc"
saves-sync-reindex || true
ssh -o BatchMode=yes book saves-sync-reindex || true

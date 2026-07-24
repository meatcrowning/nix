# claude-sessions — prune old Claude Code sessions and completed background tasks.
#
# Claude Code has no built-in way to remove old conversation transcripts
# (~/.claude/projects/<enc-cwd>/*.jsonl) or finished background agents
# (~/.claude/jobs/*/). This lists them and clears the ones you pick.
#
# NOTHING IS HARD-DELETED: selected items are MOVED to a trash dir
# (~/.claude/.trash-claude-sessions/) so a mistake is always recoverable with
# `claude-sessions restore`. Empty the trash for good with `claude-sessions
# empty-trash`.
#
# Usage:
#   claude-sessions [sessions]        interactive session picker (default)
#   claude-sessions tasks             pick completed background agents to remove
#   claude-sessions restore           restore a previous deletion from trash
#   claude-sessions empty-trash       permanently delete everything in trash
#
# Options (for sessions/tasks):
#   -p, --project        limit to the current working directory's project
#   --older-than N       only consider items older than N days
#   --dry-run            show what would be trashed, move nothing
#   -y, --yes            skip the confirmation prompt (for scripts)
#   -h, --help           this help
#
# `tasks` targets agents in a finished state (done/failed); a still-running
# (working) or input-blocked agent is never listed.

set -euo pipefail

CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ROOT="$CFG/projects"
JOBS="$CFG/jobs"
TRASH="$CFG/.trash-claude-sessions"

MODE="sessions"
PROJECT_ONLY=0
OLDER_THAN=""
ASSUME_YES=0
DRY_RUN=0

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "$0"; exit 0; }

# First non-flag arg selects the mode.
case "${1:-}" in
  sessions|tasks|restore|empty-trash) MODE="$1"; shift ;;
  -h|--help) usage ;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project) PROJECT_ONLY=1 ;;
    --older-than) shift; OLDER_THAN="${1:-}"; [ -n "$OLDER_THAN" ] || die "--older-than needs a number of days" ;;
    -y|--yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

command -v jq >/dev/null 2>&1 || die "jq is required but not found on PATH"

human_size() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "${1}B"; }
encode_cwd() { printf '%s' "$PWD" | sed 's:[/.]:-:g'; }

# ---- trash helpers -------------------------------------------------------
# Move a set of paths into a new timestamped trash batch, recording each
# item's original absolute path so `restore` can put it back exactly.
trash_batch() {
  local ts batch f base i=0
  ts=$(date +%Y%m%d-%H%M%S)
  batch="$TRASH/$ts-$$"
  mkdir -p "$batch"
  : > "$batch/manifest.tsv"
  for f in "$@"; do
    [ -e "$f" ] || continue
    i=$((i+1))
    base="item$i-$(basename "$f")"
    printf '%s\t%s\n' "$base" "$f" >> "$batch/manifest.tsv"
    mv "$f" "$batch/$base"
  done
  echo "$batch"
}

# ==========================================================================
# restore
# ==========================================================================
if [ "$MODE" = "restore" ]; then
  [ -d "$TRASH" ] || { echo "Trash is empty."; exit 0; }
  mapfile -t BATCHES < <(find "$TRASH" -mindepth 1 -maxdepth 1 -type d | sort -r)
  [ "${#BATCHES[@]}" -gt 0 ] || { echo "Trash is empty."; exit 0; }
  echo
  printf '  %-3s  %-17s  %6s  %s\n' "#" "DELETED" "ITEMS" "FIRST ITEM"
  printf '  '; printf '─%.0s' {1..70}; echo
  i=0; declare -a IDX=()
  for b in "${BATCHES[@]}"; do
    i=$((i+1)); IDX[$i]="$b"
    when=$(basename "$b" | sed -E 's/-[0-9]+$//; s/([0-9]{4})([0-9]{2})([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})/\1-\2-\3 \4:\5/')
    n=$(grep -c . "$b/manifest.tsv" 2>/dev/null || echo 0)
    first=$(head -1 "$b/manifest.tsv" 2>/dev/null | cut -f2)
    printf '  %-3s  %-17s  %6s  %s\n' "$i" "$when" "$n" "$(basename "${first:-?}")"
  done
  echo
  printf 'Batch # to restore (Enter to cancel): '
  read -r sel </dev/tty || sel=""
  [ -n "$sel" ] && [ -n "${IDX[$sel]:-}" ] || { echo "Cancelled."; exit 0; }
  b="${IDX[$sel]}"; restored=0
  while IFS=$'\t' read -r base orig; do
    [ -n "$orig" ] || continue
    mkdir -p "$(dirname "$orig")"
    if [ -e "$orig" ]; then echo "  skip (exists): $orig"; continue; fi
    mv "$b/$base" "$orig" && restored=$((restored+1))
  done < "$b/manifest.tsv"
  rm -f "$b/manifest.tsv"; rmdir "$b" 2>/dev/null || true
  echo "Restored $restored item(s)."
  exit 0
fi

# ==========================================================================
# empty-trash
# ==========================================================================
if [ "$MODE" = "empty-trash" ]; then
  [ -d "$TRASH" ] || { echo "Trash is already empty."; exit 0; }
  sz=$(du -sh "$TRASH" 2>/dev/null | cut -f1)
  n=$(find "$TRASH" -mindepth 1 -maxdepth 1 -type d | wc -l)
  echo "Trash holds $n deletion batch(es), $sz."
  if [ "$ASSUME_YES" -ne 1 ]; then
    printf 'Permanently delete all of it? [y/N] '
    read -r ans </dev/tty || ans=""
    case "$ans" in y|Y|yes) ;; *) echo "Cancelled."; exit 0 ;; esac
  fi
  rm -rf "$TRASH"
  echo "Trash emptied."
  exit 0
fi

# ==========================================================================
# tasks — completed background agents under ~/.claude/jobs
# ==========================================================================
if [ "$MODE" = "tasks" ]; then
  [ -d "$JOBS" ] || { echo "No background tasks found."; exit 0; }
  cutoff=0
  [ -n "$OLDER_THAN" ] && cutoff=$(( $(date +%s) - OLDER_THAN * 86400 ))
  here=""; [ "$PROJECT_ONLY" -eq 1 ] && here="$PWD"

  declare -a IDX_JOB=()
  echo
  printf '  %-3s  %-16s  %-8s  %-20s  %s\n' "#" "UPDATED" "STATE" "PROJECT" "TASK"
  printf '  '; printf '─%.0s' {1..84}; echo
  i=0
  while IFS= read -r sf; do
    d=$(dirname "$sf")
    state=$(jq -r '.state // "?"' "$sf" 2>/dev/null || echo "?")
    case "$state" in done|failed) ;; *) continue ;; esac
    cwd=$(jq -r '.cwd // ""' "$sf" 2>/dev/null || echo "")
    mt=$(stat -c %Y "$sf" 2>/dev/null || echo 0)
    [ -n "$OLDER_THAN" ] && [ "$mt" -ge "$cutoff" ] && continue
    [ -n "$here" ] && [ "$cwd" != "$here" ] && continue
    i=$((i+1)); IDX_JOB[$i]="$d"
    when=$(date -d "@$mt" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '?')
    proj=$(basename "${cwd:-?}"); proj="${proj:0:20}"
    label=$(jq -r '(.name // .intent // "(no label)")' "$sf" 2>/dev/null | tr '\n' ' '); label="${label:0:44}"
    printf '  %-3s  %-16s  %-8s  %-20s  %s\n' "$i" "$when" "$state" "$proj" "$label"
  done < <(find "$JOBS" -mindepth 2 -maxdepth 2 -name 'state.json' | sort)
  echo
  [ "$i" -gt 0 ] || { echo "No completed background tasks to clean."; exit 0; }

  declare -a PICK=()
  if [ "$ASSUME_YES" -eq 1 ]; then
    PICK=("${IDX_JOB[@]:1}")
  else
    printf 'Tasks to remove (e.g. "1 3 5-8", "all", Enter to cancel): '
    read -r sel </dev/tty || sel=""
    [ -n "$sel" ] || { echo "Cancelled."; exit 0; }
    if [ "$sel" = "all" ]; then PICK=("${IDX_JOB[@]:1}"); else
      for tok in $sel; do
        if [[ "$tok" =~ ^[0-9]+-[0-9]+$ ]]; then
          for ((n=${tok%-*}; n<=${tok#*-}; n++)); do [ -n "${IDX_JOB[$n]:-}" ] && PICK+=("${IDX_JOB[$n]}"); done
        elif [[ "$tok" =~ ^[0-9]+$ ]]; then
          [ -n "${IDX_JOB[$tok]:-}" ] && PICK+=("${IDX_JOB[$tok]}") || echo "  (skip #$tok)"
        fi
      done
    fi
  fi
  [ "${#PICK[@]}" -gt 0 ] || { echo "Nothing selected."; exit 0; }
  echo; echo "Will move ${#PICK[@]} task(s) to trash."
  if [ "$DRY_RUN" -eq 1 ]; then echo "(dry-run: nothing moved)"; exit 0; fi
  if [ "$ASSUME_YES" -ne 1 ]; then
    printf 'Confirm? [y/N] '; read -r ans </dev/tty || ans=""
    case "$ans" in y|Y|yes) ;; *) echo "Cancelled."; exit 0 ;; esac
  fi
  trash_batch "${PICK[@]}" >/dev/null
  echo "Moved ${#PICK[@]} task(s) to trash. Undo with: claude-sessions restore"
  exit 0
fi

# ==========================================================================
# sessions (default) — transcripts under ~/.claude/projects
# ==========================================================================
[ -d "$ROOT" ] || die "no sessions directory at $ROOT"

if [ "$PROJECT_ONLY" -eq 1 ]; then
  dir="$ROOT/$(encode_cwd)"
  [ -d "$dir" ] || die "no sessions recorded for this project yet ($dir)"
  search_roots=("$dir")
else
  search_roots=("$ROOT")
fi

declare -a FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(
  find "${search_roots[@]}" -maxdepth 2 -name '*.jsonl' -not -path '*/subagents/*' 2>/dev/null
)
[ "${#FILES[@]}" -gt 0 ] || { echo "No sessions found."; exit 0; }

if [ -n "$OLDER_THAN" ]; then
  cutoff=$(( $(date +%s) - OLDER_THAN * 86400 ))
  declare -a KEEP=()
  for f in "${FILES[@]}"; do
    mt=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    [ "$mt" -lt "$cutoff" ] && KEEP+=("$f")
  done
  FILES=("${KEEP[@]:-}")
  [ "${#FILES[@]}" -gt 0 ] && [ -n "${FILES[0]}" ] || { echo "No sessions older than $OLDER_THAN days."; exit 0; }
fi

declare -a SORTED=()
while IFS= read -r line; do SORTED+=("${line#* }"); done < <(
  for f in "${FILES[@]}"; do printf '%s %s\n' "$(stat -c %Y "$f" 2>/dev/null || echo 0)" "$f"; done | sort -n
)
FILES=("${SORTED[@]}")

preview() {
  head -n 60 "$1" 2>/dev/null | jq -rs '
    (map(select(.aiTitle)) | .[0].aiTitle) as $t
    | (map(select(.type=="user" and (.message.content|type=="string"))) | .[0].message.content) as $u
    | (($t // $u) // "(no title)") | gsub("[\n\t]";" ") | .[0:80]
  ' 2>/dev/null || echo "(unreadable)"
}

echo
printf '  %-3s  %-16s  %8s  %-22s  %s\n' "#" "LAST MODIFIED" "SIZE" "PROJECT" "TITLE"
printf '  '; printf '─%.0s' {1..88}; echo
i=0; declare -a IDX_FILE=()
for f in "${FILES[@]}"; do
  i=$((i+1)); IDX_FILE[$i]="$f"
  when=$(date -d "@$(stat -c %Y "$f")" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '?')
  size=$(human_size "$(stat -c %s "$f" 2>/dev/null || echo 0)")
  proj=$(basename "$(dirname "$f")"); proj="${proj#-home-lam-}"; proj="${proj:0:22}"
  printf '  %-3s  %-16s  %8s  %-22s  %s\n' "$i" "$when" "$size" "$proj" "$(preview "$f")"
done
echo

declare -a TO_DELETE=()
if [ "$ASSUME_YES" -eq 1 ]; then
  TO_DELETE=("${FILES[@]}")
else
  printf 'Sessions to delete (e.g. "1 3 5-8", "all", Enter to cancel): '
  read -r sel </dev/tty || sel=""
  [ -n "$sel" ] || { echo "Cancelled."; exit 0; }
  if [ "$sel" = "all" ]; then
    TO_DELETE=("${FILES[@]}")
  else
    for tok in $sel; do
      if [[ "$tok" =~ ^[0-9]+-[0-9]+$ ]]; then
        a="${tok%-*}"; b="${tok#*-}"
        for ((n=a; n<=b; n++)); do [ -n "${IDX_FILE[$n]:-}" ] && TO_DELETE+=("${IDX_FILE[$n]}"); done
      elif [[ "$tok" =~ ^[0-9]+$ ]]; then
        [ -n "${IDX_FILE[$tok]:-}" ] && TO_DELETE+=("${IDX_FILE[$tok]}") || echo "  (skipping invalid #$tok)"
      else
        echo "  (skipping unrecognized '$tok')"
      fi
    done
  fi
fi
[ "${#TO_DELETE[@]}" -gt 0 ] || { echo "Nothing selected."; exit 0; }

echo
echo "Will move ${#TO_DELETE[@]} session(s) to trash:"
total=0
for f in "${TO_DELETE[@]}"; do
  sz=$(stat -c %s "$f" 2>/dev/null || echo 0); total=$((total+sz))
  echo "  - $(basename "$f")  ($(date -d "@$(stat -c %Y "$f")" '+%Y-%m-%d' 2>/dev/null))"
done
echo "  freeing ~$(human_size "$total") (recoverable via 'claude-sessions restore')"
echo

if [ "$DRY_RUN" -eq 1 ]; then echo "(dry-run: nothing moved)"; exit 0; fi
if [ "$ASSUME_YES" -ne 1 ]; then
  printf 'Confirm? [y/N] '
  read -r ans </dev/tty || ans=""
  case "$ans" in y|Y|yes) ;; *) echo "Cancelled."; exit 0 ;; esac
fi

# Trash each .jsonl together with its subagent sidecar directory.
declare -a MOVE=()
for f in "${TO_DELETE[@]}"; do
  MOVE+=("$f")
  side="${f%.jsonl}"
  [ -d "$side" ] && MOVE+=("$side")
done
trash_batch "${MOVE[@]}" >/dev/null
echo "Moved ${#TO_DELETE[@]} session(s) to trash. Undo with: claude-sessions restore"

# claude-sessions — list and delete old Claude Code sessions.
#
# Claude Code stores each conversation as a .jsonl file under
# ~/.claude/projects/<encoded-cwd>/. There is no built-in way to prune them,
# so this tool lists sessions (with age, size and an AI-generated title) and
# lets you delete the ones you no longer want, along with their subagent
# sidecar transcripts.
#
# Usage:
#   claude-sessions                 interactive picker (all projects)
#   claude-sessions -p              only sessions for the current directory
#   claude-sessions --older-than 30 preselect sessions older than 30 days
#   claude-sessions --older-than 30 -y --dry-run   preview a prune, no delete
#
# Flags:
#   -p, --project        limit to the current working directory's project
#   --older-than N       only consider sessions older than N days
#   -y, --yes            delete without the confirmation prompt (for scripts)
#   --dry-run            show what would be deleted, delete nothing
#   -h, --help           this help

set -euo pipefail

ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
PROJECT_ONLY=0
OLDER_THAN=""
ASSUME_YES=0
DRY_RUN=0

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project) PROJECT_ONLY=1 ;;
    --older-than) shift; OLDER_THAN="${1:-}"; [ -n "$OLDER_THAN" ] || die "--older-than needs a number of days"; ;;
    -y|--yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

command -v jq >/dev/null 2>&1 || die "jq is required but not found on PATH"
[ -d "$ROOT" ] || die "no sessions directory at $ROOT"

# Claude encodes the project path by replacing '/' and '.' with '-'.
encode_cwd() { printf '%s' "$PWD" | sed 's:[/.]:-:g'; }

# Collect candidate .jsonl files.
declare -a FILES=()
if [ "$PROJECT_ONLY" -eq 1 ]; then
  dir="$ROOT/$(encode_cwd)"
  [ -d "$dir" ] || die "no sessions found for this project ($dir)"
  search_roots=("$dir")
else
  search_roots=("$ROOT")
fi

# Only top-level session files (exclude subagent sidecar dirs like */subagents/*).
while IFS= read -r f; do FILES+=("$f"); done < <(
  find "${search_roots[@]}" -maxdepth 2 -name '*.jsonl' -not -path '*/subagents/*' 2>/dev/null
)

[ "${#FILES[@]}" -gt 0 ] || { echo "No sessions found."; exit 0; }

# Optional age filter.
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

# Sort oldest-first so cleanup targets sit at the top.
declare -a SORTED=()
while IFS= read -r line; do SORTED+=("${line#* }"); done < <(
  for f in "${FILES[@]}"; do printf '%s %s\n' "$(stat -c %Y "$f" 2>/dev/null || echo 0)" "$f"; done | sort -n
)
FILES=("${SORTED[@]}")

# Extract a short preview: aiTitle, else first typed user message.
preview() {
  head -n 60 "$1" 2>/dev/null | jq -rs '
    (map(select(.aiTitle)) | .[0].aiTitle) as $t
    | (map(select(.type=="user" and (.message.content|type=="string"))) | .[0].message.content) as $u
    | (($t // $u) // "(no title)") | gsub("[\n\t]";" ") | .[0:80]
  ' 2>/dev/null || echo "(unreadable)"
}

human_size() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "${1}B"; }

# Render the list.
echo
printf '  %-3s  %-16s  %8s  %-22s  %s\n' "#" "LAST MODIFIED" "SIZE" "PROJECT" "TITLE"
printf '  '; printf '─%.0s' {1..88}; echo
i=0
declare -a IDX_FILE=()
for f in "${FILES[@]}"; do
  i=$((i+1))
  IDX_FILE[$i]="$f"
  when=$(date -d "@$(stat -c %Y "$f")" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '?')
  size=$(human_size "$(stat -c %s "$f" 2>/dev/null || echo 0)")
  proj=$(basename "$(dirname "$f")"); proj="${proj#-home-lam-}"; proj="${proj:0:22}"
  printf '  %-3s  %-16s  %8s  %-22s  %s\n' "$i" "$when" "$size" "$proj" "$(preview "$f")"
done
echo

# Determine selection.
declare -a TO_DELETE=()
if [ "$ASSUME_YES" -eq 1 ]; then
  # Non-interactive: everything shown (typically combined with --older-than).
  TO_DELETE=("${FILES[@]}")
else
  printf 'Sessions to delete (e.g. "1 3 5-8", "all", or Enter to cancel): '
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

# Confirm.
echo
echo "Will delete ${#TO_DELETE[@]} session(s):"
total=0
for f in "${TO_DELETE[@]}"; do
  sz=$(stat -c %s "$f" 2>/dev/null || echo 0); total=$((total+sz))
  echo "  - $(basename "$f")  ($(date -d "@$(stat -c %Y "$f")" '+%Y-%m-%d' 2>/dev/null))"
done
echo "  reclaiming ~$(human_size "$total")"
echo

if [ "$DRY_RUN" -eq 1 ]; then
  echo "(dry-run: nothing deleted)"; exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  printf 'Confirm? [y/N] '
  read -r ans </dev/tty || ans=""
  case "$ans" in y|Y|yes) ;; *) echo "Cancelled."; exit 0 ;; esac
fi

# Delete each .jsonl plus its subagent sidecar directory (same basename, no ext).
n=0
for f in "${TO_DELETE[@]}"; do
  rm -f -- "$f"
  side="${f%.jsonl}"
  [ -d "$side" ] && rm -rf -- "$side"
  n=$((n+1))
done
echo "Deleted $n session(s)."

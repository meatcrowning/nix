#!/usr/bin/env bash
# Ask before a heavy rebuild overlaps a loaded ComfyUI or ollama backend.
# ComfyUI's queue identifies in-flight renders; ollama's cgroup memory identifies
# resident/loading weights. Usage:
#   heavy-gate.sh status | loaded | ask [timeout] | wait [timeout]
#                  | suspend | resume | demo [timeout]
# Runs as root from rebuild-top or as lam by hand. `Stop & rebuild` waits for a
# render, frees/stops and runtime-masks loaded backends, then restores only what
# it suspended. `Rebuild anyway`, timeout, or no notification server leaves them
# running so the caller uses throttled limits. Every verb is idempotent.
set -uo pipefail

COMFY_URL=${HEAVY_GATE_COMFY_URL:-${COMFY_GATE_URL:-http://127.0.0.1:8188}}
OLLAMA_URL=${HEAVY_GATE_OLLAMA_URL:-http://127.0.0.1:11434}
COMFY_UNIT=comfy-painter.service
OLLAMA_UNIT=ollama.service
# ollama is a system unit; read memory.current because /api/ps is empty while a
# model loads. More than 1 GiB means resident/loading weights, not an idle daemon.
OLLAMA_CGROUP=${OLLAMA_CGROUP:-/sys/fs/cgroup/system.slice/ollama.service/memory.current}
# tmpfs: a reboot mid-rebuild leaves nothing to undo.
STATE_DIR=/run/heavy-gate
POLL=10
ASK_TIMEOUT_DEFAULT=300

U=${SUDO_USER:-$(id -un)}
UID_=$(id -u "$U")

# Every systemctl --user / notify-send here has to reach HIS session bus, which
# root does not have. runuser + the two variables is the same shape the
# rebuild-top wrapper already uses for preflight.
as_user() {
  if [ "$(id -u)" = 0 ]; then
    runuser -u "$U" -- env XDG_RUNTIME_DIR="/run/user/$UID_" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_/bus" "$@"
  else
    "$@"
  fi
}

# ollama is a SYSTEM unit: root drives it directly, a hand run escalates through
# the askpass dialog rather than failing silently (AGENTS.md, `sudo -A`).
as_root() {
  if [ "$(id -u)" = 0 ]; then
    "$@"
  else
    SUDO_ASKPASS_REASON="${SUDO_ASKPASS_REASON:-stopping ollama for a heavy rebuild}" sudo -A "$@"
  fi
}

# ---------------------------------------------------------------------------
# reading the two backends
# ---------------------------------------------------------------------------

comfy_active() { as_user systemctl --user is-active --quiet "$COMFY_UNIT"; }
ollama_active() { systemctl is-active --quiet "$OLLAMA_UNIT"; }

# queue_remaining counts the running job AND anything queued behind it, which is
# the right definition of "still busy": draining the queue is one wait, not one
# per prompt. An unreachable comfy is NOT reported as rendering — a backend that
# is still starting up has nothing in flight to protect.
queue_remaining() {
  local body
  body=$(curl -sf -m 3 "$COMFY_URL/prompt" 2>/dev/null) || { echo ""; return; }
  printf '%s' "$body" | grep -o '"queue_remaining"[[:space:]]*:[[:space:]]*[0-9]\+' \
    | grep -o '[0-9]\+$' | head -1
}

comfy_state() {
  if ! comfy_active; then echo down; return; fi
  local q; q=$(queue_remaining)
  if [ -z "$q" ]; then echo starting; return; fi
  if [ "$q" -gt 0 ]; then echo rendering; else echo idle; fi
}

# `warm` is cgroup memory above 1 GiB: keep-alive weights still count after a
# request, and `/api/ps` is blind during loading. Prints `<1|0> <bytes>` for the
# existing model-count wording.
OLLAMA_WARM_BYTES=$((1024 * 1024 * 1024))
ollama_resident() {
  local b=0
  if [ -r "$OLLAMA_CGROUP" ]; then
    b=$(cat "$OLLAMA_CGROUP" 2>/dev/null | tr -d '[:space:]')
  fi
  case "${b:-0}" in
    ''|*[!0-9]*) b=0 ;;
  esac
  if [ "$b" -gt "$OLLAMA_WARM_BYTES" ]; then echo "1 $b"; else echo "0 $b"; fi
}

ollama_state() {
  if ! ollama_active; then echo down; return; fi
  local n; n=$(ollama_resident | cut -d' ' -f1)
  [ "${n:-0}" -gt 0 ] && echo warm || echo idle
}

# Advisory only, and said as such in the toast: ollama has no "am I generating"
# endpoint, so sustained GPU utilization is the one hint that a stop would
# interrupt something. Absent nvidia-smi it is simply not mentioned.
gpu_util() {
  command -v nvidia-smi >/dev/null 2>&1 || { echo ""; return; }
  nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null \
    | head -1 | tr -d ' '
}

human_gb() { awk -v b="${1:-0}" 'BEGIN{ printf "%.1fG", b/1073741824 }'; }

# `${arr[*]}` joins on the FIRST character of IFS only, so "ComfyUI + ollama"
# cannot be had that way — spell the separator out.
join_by() { local sep=$1; shift; local out=""; for x in "$@"; do
  out="${out:+$out$sep}$x"; done; printf '%s' "$out"; }

status() {
  local c o n b
  c=$(comfy_state); o=$(ollama_state)
  read -r n b <<<"$(ollama_resident)"
  local line="comfy=$c ollama=$o"
  [ "${n:-0}" -gt 0 ] && line="$line($n model$([ "$n" = 1 ] || echo s), $(human_gb "$b"))"
  local g; g=$(gpu_util); [ -n "$g" ] && line="$line gpu=${g}%"
  echo "$line"
}

# "Is there anything here worth asking about" — the caller's cheap first check,
# before it pays ~12s of dry-build eval to find out whether the plan is heavy.
loaded() {
  [ "$(comfy_state)" != down ] && return 0
  [ "$(ollama_state)" = warm ] && return 0
  return 1
}

# ---------------------------------------------------------------------------
# telling him / asking him
# ---------------------------------------------------------------------------

notify() {
  # Echoed as well as sent, so the rebuild log says what he was told.
  echo "heavy-gate: notify: $1 — $2" >&2
  # HEAVY_GATE_NO_NOTIFY exists for the harness: a test may not put a toast on
  # his screen (AGENTS.md, "Testing without interfering with the user").
  [ "${HEAVY_GATE_NO_NOTIFY:-${COMFY_GATE_NO_NOTIFY:-0}}" = 1 ] && return 0
  # -- before the positionals: notify-send parses a leading dash in the summary
  # or body as an option and exits 1 with no notification.
  as_user notify-send -a "rebuild" -u normal -- "$1" "$2" >/dev/null 2>&1 || true
}

# `ask` prints one contract word: clear, stop, keep, timeout, or noask. The
# critical, non-expiring toast has buttons regardless of `notifActions`; timeout
# and noask mean keep/continue rather than holding an unattended rebuild lock.
ask() {
  local timeout=${1:-$ASK_TIMEOUT_DEFAULT}
  local c o n b g body sum

  # The demo raises the toast whatever the machine is doing; a real ask with
  # nothing loaded has no question to put on his screen.
  if ! loaded && [ "${HEAVY_GATE_DEMO:-0}" != 1 ]; then echo clear; return 0; fi

  c=$(comfy_state); o=$(ollama_state)
  read -r n b <<<"$(ollama_resident)"
  g=$(gpu_util)

  local what=() lines=()
  if [ "$c" = rendering ]; then
    what+=("ComfyUI"); lines+=("- ComfyUI is RENDERING (it will be waited out, never cut)")
  elif [ "$c" != down ]; then
    what+=("ComfyUI"); lines+=("- ComfyUI is up with its weights resident")
  fi
  if [ "$o" = warm ]; then
    what+=("ollama")
    lines+=("- ollama holds $n model$([ "$n" = 1 ] || echo s), $(human_gb "$b")$([ -n "$g" ] && echo ", GPU ${g}%")")
  fi
  if [ "${#lines[@]}" = 0 ]; then
    what+=("ComfyUI" "ollama")
    lines+=("- ComfyUI is up with its weights resident" \
            "- ollama holds 1 model, 22.4G (demo — nothing is actually loaded)")
  fi
  sum="Heavy rebuild wants the memory"
  body=$(printf '%s\n' "${lines[@]}")
  body="$body
Stop $(join_by " and " "${what[@]}") and build, or build alongside it?"

  # The harness answers without a toast; a real run never sets this.
  if [ -n "${HEAVY_GATE_ASK_ANSWER:-}" ]; then
    echo "heavy-gate: ask (stubbed): $sum | ${lines[*]} -> $HEAVY_GATE_ASK_ANSWER" >&2
    echo "$HEAVY_GATE_ASK_ANSWER"; return 0
  fi

  # NOBODY CAN ANSWER A TOAST NOBODY CAN SEE. If no process OWNS
  # org.freedesktop.Notifications there is no notification server — `top` sits
  # at the ly greeter for days at a time with no session at all — and raising
  # the question means holding the rebuild lock for the whole ask timeout to
  # arrive at the answer we would have given anyway. `--acquired`, not
  # `--activatable`: the activatable entry is what made this look answerable,
  # and D-Bus activating it just fails 20s later (`plasma_waitforname:
  # WaitForName: Service was not registered within timeout`).
  if ! as_user busctl --user list --acquired --no-pager 2>/dev/null \
       | grep -q "org.freedesktop.Notifications"; then
    echo "heavy-gate: nothing on this machine can show a toast — not asking" >&2
    echo noask; return 0
  fi

  # notify-send -w blocks until the toast is acted on and then prints the action
  # key; -p prints the id first. Both go to a file rather than a pipe, because
  # the read has to survive us killing notify-send at the timeout — a pipe's
  # block-buffered tail would be lost with it.
  #
  # `timeout` AND `9>&-`, both learned the hard way on 2026-08-24. `as_user` is
  # `runuser -- env … notify-send`, so `$!` is runuser's pid and the kill below
  # reaps THAT — the notify-send under it is orphaned, not killed. With no
  # notification daemon on the host (nobody sitting at it) `-w` then blocks for
  # ever, and because it inherited rebuild-top's flock on fd 9 it holds THE
  # REBUILD LOCK: found 17 minutes later still parked on a toast nothing could
  # display, with every rebuild on that machine queued behind it. So the toast
  # (a) dies on its own a little after the timeout we are counting out, and (b)
  # cannot hold the lock even if it somehow outlives that.
  local out; out=$(mktemp)
  as_user timeout -k 5 "$((timeout + 15))" \
    notify-send -a "rebuild" -u critical -t 0 -p -w \
    --action=stop="Stop & rebuild" --action=keep="Rebuild anyway" \
    -- "$sum" "$body" >"$out" 2>/dev/null 9>&- &
  local pid=$!

  local waited=0 key="" nid=""
  while [ "$waited" -lt "$timeout" ]; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1; waited=$((waited + 1))
  done
  nid=$(sed -n 1p "$out" 2>/dev/null | tr -d '[:space:]')

  # Checked BEFORE `wait`, which on a still-running notify-send would block past
  # the timeout we just spent counting out.
  if kill -0 "$pid" 2>/dev/null; then
    # Timed out: take the question off his screen rather than leaving a critical
    # toast that outlives the build it was asking about.
    kill "$pid" 2>/dev/null
    [ -n "$nid" ] && as_user busctl --user call org.freedesktop.Notifications \
      /org/freedesktop/Notifications org.freedesktop.Notifications \
      CloseNotification u "$nid" >/dev/null 2>&1
    rm -f "$out"; echo timeout; return 0
  fi
  wait "$pid" 2>/dev/null
  key=$(sed -n 2p "$out" 2>/dev/null | tr -d '[:space:]')
  rm -f "$out"

  case "$key" in
    stop) echo stop ;;
    keep) echo keep ;;
    # No id and no key: notify-send failed outright (no server, or the panel is
    # not up yet). That is not an answer and must not read as one.
    "") [ -n "$nid" ] && echo keep || echo noask ;;
    *)  echo keep ;;
  esac
}

# ---------------------------------------------------------------------------
# waiting / suspending / resuming
# ---------------------------------------------------------------------------

# Wait for an in-flight render. Timeout is a hung-queue backstop, not a deadline
# for the render; the caller chooses the throttled fallback.
do_wait() {
  local timeout=${1:-3600} waited=0 said=0
  while [ "$(comfy_state)" = rendering ]; do
    if [ "$said" = 0 ]; then
      echo "heavy-gate: a render is in flight — waiting for it to finish" >&2
      said=1
    fi
    if [ "$waited" -ge "$timeout" ]; then
      echo "heavy-gate: still rendering after ${timeout}s — giving up the wait" >&2
      return 1
    fi
    sleep "$POLL"; waited=$((waited + POLL))
  done
  [ "$said" = 1 ] && echo "heavy-gate: render finished after ${waited}s" >&2
  return 0
}

# A user-unit runtime mask under XDG_RUNTIME_DIR loses to home-manager's unit;
# place ComfyUI's mask in user.control. The system-unit runtime mask works for
# ollama.
CTL="/run/user/$UID_/systemd/user.control"
comfy_mask_on() {
  as_user mkdir -p "$CTL" \
    && as_user ln -sfn /dev/null "$CTL/$COMFY_UNIT" \
    && as_user systemctl --user daemon-reload
}
comfy_mask_off() {
  as_user rm -f "$CTL/$COMFY_UNIT"
  as_user systemctl --user daemon-reload
}

suspend_comfy() {
  comfy_active || { echo "heavy-gate: comfy is not running — nothing to suspend" >&2; return 0; }
  if [ "$(comfy_state)" = rendering ]; then
    echo "heavy-gate: REFUSING to suspend a running render" >&2
    return 1
  fi
  # Free first: stopping the unit would drop the weights anyway, but asking
  # comfy to unload them itself lets it tear down its CUDA context cleanly.
  curl -sf -m 10 -X POST -H 'Content-Type: application/json' \
    -d '{"unload_models": true, "free_memory": true}' "$COMFY_URL/free" >/dev/null 2>&1 || true
  as_user systemctl --user stop "$COMFY_UNIT" || return 1
  comfy_mask_on
  local masked; masked=$(as_user systemctl --user is-enabled "$COMFY_UNIT" 2>/dev/null)
  case "$masked" in
    masked*) ;;
    *) echo "heavy-gate: WARN: comfy is stopped but NOT masked ($masked) — opening painter could start it mid-build" >&2 ;;
  esac
  mkdir -p "$STATE_DIR" && : >"$STATE_DIR/comfy"
  echo "heavy-gate: comfy suspended (stopped and runtime-masked)" >&2
  return 0
}

suspend_ollama() {
  ollama_active || { echo "heavy-gate: ollama is not running — nothing to suspend" >&2; return 0; }
  as_root systemctl stop "$OLLAMA_UNIT" || return 1
  # Runtime mask so oracle (or anything else that pokes 11434) cannot bring it
  # back under the build. /run outranks /etc for system units, so this one works.
  as_root systemctl mask --runtime "$OLLAMA_UNIT" >/dev/null 2>&1
  mkdir -p "$STATE_DIR" && : >"$STATE_DIR/ollama"
  echo "heavy-gate: ollama suspended (stopped and runtime-masked)" >&2
  return 0
}

do_suspend() {
  local did=() rc=0
  if [ "$(comfy_state)" != down ]; then
    suspend_comfy && did+=("ComfyUI") || rc=1
  fi
  if [ "$(ollama_state)" != down ]; then
    suspend_ollama && did+=("ollama") || rc=1
  fi
  if [ "${#did[@]}" -gt 0 ]; then
    notify "$(join_by " + " "${did[@]}") suspended" \
           "Rebuilding the system — stopped at your say-so, and back on their own when it finishes."
  fi
  return $rc
}

do_resume() {
  local back=()
  if [ -e "$STATE_DIR/comfy" ]; then
    comfy_mask_off
    rm -f "$STATE_DIR/comfy"
    if as_user systemctl --user start "$COMFY_UNIT"; then
      back+=("ComfyUI"); echo "heavy-gate: comfy resumed" >&2
    else
      echo "heavy-gate: FAILED to restart comfy — start it from painter's settings drawer" >&2
      notify "ComfyUI did not restart" \
             "The rebuild is done but comfy-painter failed to start. Start it from painter's settings drawer."
    fi
  fi
  if [ -e "$STATE_DIR/ollama" ]; then
    as_root systemctl unmask --runtime "$OLLAMA_UNIT" >/dev/null 2>&1
    rm -f "$STATE_DIR/ollama"
    if as_root systemctl start "$OLLAMA_UNIT"; then
      back+=("ollama"); echo "heavy-gate: ollama resumed" >&2
    else
      echo "heavy-gate: FAILED to restart ollama — systemctl start ollama" >&2
      notify "ollama did not restart" \
             "The rebuild is done but ollama failed to start. Run: sudo systemctl start ollama"
    fi
  fi
  if [ "${#back[@]}" -gt 0 ]; then
    notify "$(join_by " + " "${back[@]}") back" \
           "The rebuild is done and the backend is starting — the first run reloads its weights."
  fi
}

# Raising the real toast, with real buttons, is a command HE runs — the harness
# never does it (same rule as `repo-updates.py --demo`). This is how the ask is
# verified end to end: the wording, the two buttons, and that the key comes back.
do_demo() {
  local t=${1:-120}
  echo "heavy-gate: raising the real toast — press a button (or wait ${t}s for the timeout path)" >&2
  HEAVY_GATE_DEMO=1 ask "$t"
}

case "${1:-status}" in
  status)  status ;;
  loaded)  loaded ;;
  ask)     ask "${2:-}" ;;
  demo)    do_demo "${2:-}" ;;
  wait)    do_wait "${2:-3600}" ;;
  suspend) do_suspend ;;
  resume)  do_resume ;;
  *) echo "usage: heavy-gate.sh status | loaded | ask [timeout] | wait [timeout] | suspend | resume | demo [timeout]" >&2; exit 2 ;;
esac

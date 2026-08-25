#!/usr/bin/env bash
# Keep a heavy rebuild from meeting a loaded GPU backend — by ASKING him first.
#
# The 2026-08-09 freeze was a rebuild compiling ollama's CUDA kernels while a
# ComfyUI video run held the other half of 30 GiB. Capping the build cgroup
# (sys/nix-build-limits.nix) makes that survivable; this makes the two never
# meet, which is better: a throttled build and a throttled render are both bad
# outcomes, and they are avoidable by simply not overlapping.
#
# TWO backends, because either can hold the machine's memory:
#
#   * ComfyUI (`comfy-painter.service`, a USER unit) — its queue says whether a
#     job is in flight, so a render can be waited out precisely.
#   * ollama (`ollama.service`, a SYSTEM unit) — `/api/ps` says which models are
#     RESIDENT. It has no queue endpoint, so a generation in flight is not
#     visible here; a warm 23 GB model is, and that is what matters for RAM.
#
# THE ANSWER IS HIS, NOT OURS (2026-08-09). This used to suspend comfy on its
# own judgement. Now a loaded backend in front of a heavy build raises a
# CRITICAL toast with two buttons and does what he picks:
#
#   Stop & rebuild  -> stop whichever backend is loaded, build, put them back
#   Rebuild anyway  -> leave them up; the caller builds throttled instead
#
# and no answer inside the timeout means "anyway" — an unattended machine must
# not sit on a held rebuild lock waiting for a click that is not coming.
#
# The rules that survived from the silent version, each for a reason:
#
#   1. A render in flight is NEVER interrupted. Even on "Stop & rebuild" we
#      wait for it — however long — and only then stop comfy.
#   2. Weights merely sitting in VRAM are not a reason to wait: they are freed
#      (`/free`), which costs him a reload later and nothing else.
#   3. Suspending stops AND runtime-masks, so nothing can restart the backend
#      halfway through the build. Masking is the half that matters: painter
#      fires `startBackend` on its own launch (main.py:790).
#   4. He is told, by name, at every step — a backend that vanished with no
#      explanation is exactly the "silent change" docs/DESIGN.md §10 forbids.
#   5. Resume restores only what we suspended, and only if we suspended it — a
#      backend that was already down before the rebuild stays down.
#
# Usage:  heavy-gate.sh status | loaded | ask [timeout] | wait [timeout]
#                       | suspend | resume | demo [timeout]
#
# Runs as root (from rebuild-top) or as lam by hand; the user-side half is
# re-entered with runuser when root. Idempotent: every verb is safe to repeat,
# and `resume` with nothing suspended does nothing at all.
set -uo pipefail

COMFY_URL=${HEAVY_GATE_COMFY_URL:-${COMFY_GATE_URL:-http://127.0.0.1:8188}}
OLLAMA_URL=${HEAVY_GATE_OLLAMA_URL:-http://127.0.0.1:11434}
COMFY_UNIT=comfy-painter.service
OLLAMA_UNIT=ollama.service
# ollama is a SYSTEM unit, so its cgroup is fixed under system.slice (unlike
# comfy's user unit, which heavy-gate reads via systemctl). This is the same
# path the ai-warden reads (ai-warden.py ollama_cgroup()) and the reason is
# identical: `/api/ps` reports {"models":[]} for the whole duration a model
# LOADS, which is precisely the window a rebuild collides with, while
# memory.current is correct throughout (measured 2026-08-22: it said "nothing
# resident" while llama-server held 14.4 GiB).
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

# `warm` is the whole point for ollama: a model that finished answering an hour
# ago still holds its weights until keep_alive expires, and THAT is the memory a
# build would have to fit around. Reads the unit's cgroup, NOT `/api/ps` — the
# endpoint is blind for the whole duration a model loads (measured 2026-08-22:
# `{"models":[]}` while llama-server held 14.4 GiB RSS), which is exactly the
# window a rebuild collides with; memory.current is correct throughout and is
# the same source the ai-warden trusts. A warm model holds gigabytes, an idle
# daemon sits near zero, so > 1 GiB is the "resident or loading" bar.
# Prints: "<1|0> <bytes>" — the count is a proxy for the cgroup bar, kept so the
# callers' "N model(s)" wording survives.
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

# The question. Prints ONE word on stdout, which is the caller's whole contract:
#
#   clear    nothing is loaded — there was nothing to ask
#   stop     he pressed "Stop & rebuild"
#   keep     he pressed "Rebuild anyway"
#   timeout  he was not there; treat as "anyway"
#   noask    no notification server answered; treat as "anyway"
#
# The toast is urgency 2 so it never auto-expires and ignores do-not-disturb,
# and NotificationCard draws a critical toast's buttons whatever the
# `notifActions` setting says — a critical question he cannot answer would be
# worse than not asking.
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

# Waits while a comfy render is in flight. The timeout is a backstop against a
# hung queue, not a deadline for his work: it defaults to an hour and the caller
# decides what a timeout means (rebuild-top declines to suspend and builds under
# the cgroup caps instead, which is the throttled path).
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

# `systemctl --user mask --runtime` DOES NOT WORK for a home-manager user unit,
# and fails silently: it writes its /dev/null symlink into
# $XDG_RUNTIME_DIR/systemd/user, which in the USER manager's search path ranks
# BELOW $XDG_CONFIG_HOME/systemd/user — where home-manager puts
# comfy-painter.service. Measured 2026-08-09: symlink present, exit 0,
# `is-enabled` still `enabled-runtime`, and the unit started perfectly happily.
# `user.control` is the directory that outranks everything, so the mask goes
# there by hand. (The SYSTEM manager has no such problem: /run/systemd/system
# outranks /etc, so `mask --runtime` is the right tool for ollama.)
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

#!/usr/bin/env bash
# A headless Hyprland output for GUI tests. It is a real compositor output but
# has no cable, so windows and `grim -o` pixels are invisible to the user.
# This deliberately uses the live compositor for fidelity; a not-yet-switched
# plugin needs the nested harness instead, since a plugin crash still affects
# the live session.
#
#   sandbox.sh start | exec CMD... | shot [FILE] | clients | hyprctl ARGS...
#   sandbox.sh status | stop
#
# Safety contracts:
# * `exec` must receive a command that `exec`s all the way down. The compositor
#   applies `[workspace N silent; tag +sandbox]` and `no_focus` by PID; a forked
#   wrapper can miss the rule and steal focus. Placement is checked afterwards;
#   a miss closes the client and aborts, without retrying. The sandbox cannot
#   accept keyboard input; use a nested compositor when the subject needs a seat.
# * Clients are tagged `sandbox`, audio is disabled with
#   `PIPEWIRE_REMOTE=/dev/null PULSE_SERVER=/dev/null` unless `SANDBOX_AUDIO=1`,
#   and `stop` closes them before removing the output. The tag also catches
#   windows moved away from the sandbox and geometry state is pruned.
# * `session-guard.sh` rejects a stale/non-live compositor target. Pointer
#   changes caused by output removal or focus dispatch go only through
#   `sg_pointer_pin`, which restores the position it just read.
# * Use `hl.dsp.*` Lua dispatchers, not bare `hyprctl dispatch` or `keyword`.

set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/session-guard.sh
. "$HERE/lib/session-guard.sh"

DIR="${VTB_SANDBOX_DIR:-/tmp/vtb-sandbox}"
STATE="$DIR/state"
CLASSES="$DIR/classes"

die() {
  echo "sandbox: $*" >&2
  exit 1
}

# This harness DELIBERATELY drives the live compositor (see the trade-off
# above), so the guard it wants is the one that refuses to drive anything
# ELSE: a stale signature left by a nested test would otherwise have us
# creating outputs in a compositor nobody is looking at, or in one that is
# half dead.
have_hypr() {
  sg_require_live_session
}

output_remove() {
  hyprctl output remove "$1" >/dev/null 2>&1
}

find_headless() {
  hyprctl monitors -j | python3 -c '
import json, sys
for m in json.load(sys.stdin):
    if m["name"].startswith("HEADLESS-"):
        print(m["name"]); break'
}

mon_ws() {
  hyprctl monitors -j | python3 -c '
import json, sys
for m in json.load(sys.stdin):
    if m["name"] == sys.argv[1]:
        print(m["activeWorkspace"]["id"]); break' "$1"
}

focused_mon() {
  hyprctl monitors -j | python3 -c '
import json, sys
for m in json.load(sys.stdin):
    if m["focused"]:
        print(m["name"]); break'
}

# strays WS — sandbox-tagged clients that are NOT on the sandbox workspace, i.e.
# on a monitor he can see. One line each: address, class, monitor name.
#
# The exec rule places the window; nothing until now CHECKED that it did. A rule
# that does not match (a client that maps a second, unrelated toplevel; a splash
# or dialog that the `[workspace ...]` rule does not reach; a compositor that
# refused the rule outright) puts an agent's test window in front of him, which
# is exactly what he reported on 2026-07-30. Checked after every launch, and a
# hit is fatal to the run rather than cosmetic.
strays() {
  python3 - "$1" <<'PY'
import json, subprocess, sys
ws = int(sys.argv[1])
j = lambda *a: json.loads(subprocess.check_output(["hyprctl", "-j", *a]))
mons = {m["id"]: m["name"] for m in j("monitors")}
for c in j("clients"):
    tags = [t.rstrip("*") for t in c.get("tags") or []]
    if "sandbox" in tags and c["workspace"]["id"] != ws:
        print(c["address"], c["class"], mons.get(c["monitor"], "?"), sep="\t")
PY
}

kill_addr() {
  hyprctl dispatch "hl.dsp.window.close({ window = \"address:$1\" })" >/dev/null 2>&1
  sleep 0.5
  hyprctl dispatch "hl.dsp.window.kill({ window = \"address:$1\" })" >/dev/null 2>&1
}

ws_windows() { # addresses of everything on the sandbox workspace, OR tagged ours
  # The tag is the half that still holds after a window has been moved: a
  # sandbox window that ended up somewhere else is exactly the one `stop` must
  # not leave behind on the user's desktop.
  hyprctl clients -j | python3 -c '
import json, sys
for c in json.load(sys.stdin):
    tags = [t.rstrip("*") for t in c.get("tags") or []]
    if c["workspace"]["id"] == int(sys.argv[1]) or "sandbox" in tags:
        print(c["address"])' "$1"
}

# load_state [lenient] — `lenient` warns instead of dying when the monitor has
# gone, so `stop` and `status` can still clean up after a vanished sandbox.
load_state() {
  [ -f "$STATE" ] || die "not started — tools/sandbox.sh start"
  # shellcheck disable=SC1090
  . "$STATE"
  [ -n "${MON:-}" ] && [ -n "${WS:-}" ] || die "state file is incomplete"
  # The monitor can go away underneath the state file — another agent's `stop`,
  # a stray `hyprctl output remove`, a compositor restart. Hyprland then moves
  # that workspace onto a REAL monitor, so a stale WS is no longer off-screen
  # and `exec` would put an agent's test window in front of the user. Checked
  # here rather than per-subcommand, because every one of them is wrong
  # afterwards.
  hyprctl monitors -j | python3 -c '
import json, sys
mons = {m["name"]: m for m in json.load(sys.stdin)}
m = mons.get(sys.argv[1])
sys.exit(0 if m and m["activeWorkspace"]["id"] == int(sys.argv[2]) else 1)' \
    "$MON" "$WS" && return 0
  [ "${1:-}" = "lenient" ] \
    || die "$MON no longer holds workspace $WS (monitor removed?) — re-run: tools/sandbox.sh start"
  echo "sandbox: warning — $MON no longer holds workspace $WS" >&2
}

case "${1:-}" in
  start)
    have_hypr
    mkdir -p "$DIR"
    mon="$(find_headless)"
    if [ -n "$mon" ]; then
      echo "sandbox: reusing existing $mon"
    else
      hyprctl output create headless >/dev/null || die "could not create the virtual output"
      sleep 0.5
      mon="$(find_headless)"
      [ -n "$mon" ] || die "virtual output did not appear"
    fi
    ws="$(mon_ws "$mon")"
    [ -n "$ws" ] || die "virtual monitor has no workspace"
    printf 'MON=%s\nWS=%s\n' "$mon" "$ws" > "$STATE"
    : > "$CLASSES"
    echo "sandbox: $mon up, workspace $ws (off-screen)"
    ;;

  exec)
    shift
    [ $# -gt 0 ] || die "exec needs a command"
    have_hypr
    load_state
    prev="$(focused_mon)"
    sg_seat_snapshot
    # DEAF BY CONSTRUCTION. A test program must not be able to make a sound on
    # the machine he is sitting at — he asked for mechanism, not a rule agents
    # remember. `hl.dsp.exec_cmd` is run BY THE COMPOSITOR, so it inherits the
    # compositor's environment and nothing this script exports reaches it; the
    # only way in is to prepend `env` to the command itself. Both names are
    # needed: PipeWire-native clients read PIPEWIRE_REMOTE, everything speaking
    # PulseAudio reads PULSE_SERVER, and a socket path that is not a socket
    # makes each of them fail to connect and carry on silently.
    # `SANDBOX_AUDIO=1` opts out, for a harness whose subject IS the audio.
    if [ "${SANDBOX_AUDIO:-0}" = 1 ]; then
      envwrap=""
    else
      envwrap="env PIPEWIRE_REMOTE=/dev/null PULSE_SERVER=/dev/null "
    fi
    # The bracket list is the exec dispatcher's own rule syntax: put the window
    # on the sandbox workspace without dragging the user's view along, and tag
    # it as ours.
    #
    # THE TAG IS ALSO WHAT KEEPS THIS OFF HIS KEYBOARD. `hyprland.lua` carries
    # `sandbox-never-takes-the-seat`, a `no_focus` window rule matched on
    # exactly this tag — read the comment there before changing either half,
    # because `silent` alone does NOT do it: measured on top 2026-07-30 on the
    # live event socket, every launch was `openwindow>>` followed immediately by
    # `activewindow>>` naming the test window, and his next two seconds of
    # typing went to a monitor with no cable in it. The restore below used to be
    # the whole defence and is now only a net under the rule.
    hyprctl dispatch "hl.dsp.exec_cmd(\"[workspace $WS silent; tag +sandbox] $envwrap$*\")" >/dev/null \
      || die "exec dispatch failed"
    basename "$1" >> "$CLASSES" # for the geometry-memory prune in stop
    sleep 2
    if [ -n "$prev" ] && [ "$(focused_mon)" != "$prev" ]; then
      echo "sandbox: warning — focus left $prev despite the no_focus rule; restoring it. Check that hyprland.lua's 'sandbox-never-takes-the-seat' rule is live (hyprctl configerrors)." >&2
      # PINNED: `hl.dsp.focus({monitor=...})` is `Actions::focusMonitor`, which
      # warps the pointer to the target workspace's focus candidate `middle()`
      # (or the monitor's, if empty) — `cursor:no_warps` does not gate it. So
      # giving his keyboard back used to take his mouse. See sg_pointer_pin.
      sg_pointer_pin hyprctl dispatch "hl.dsp.focus({ monitor = \"$prev\" })" >/dev/null
    fi
    # DID IT ACTUALLY LAND OFF-SCREEN? Nothing verified this before, and a
    # window the exec rule missed is a window on HIS monitor. Close it, and fail
    # the run — a harness that carries on here goes on to shoot pixels of a
    # window that is not where it thinks, and leaves the real one in front of
    # him for however long the run lasts.
    st="$(strays "$WS")"
    if [ -n "$st" ]; then
      echo "sandbox: ERROR - a window this launch created is NOT on $MON:" >&2
      printf '%s\n' "$st" | sed 's/^/  /' >&2
      printf '%s\n' "$st" | while IFS=$'\t' read -r addr _ _; do kill_addr "$addr"; done
      die "closed it. The [workspace $WS silent; tag +sandbox] rule did not reach that window — check 'hyprctl configerrors' and whether the client maps more than one toplevel. NOT retrying on his monitor."
    fi
    sg_seat_assert || true   # warn-only: says so in the log if we took the seat
    echo "sandbox: launched on $MON (ws $WS): $*"
    ;;

  shot)
    shift
    have_hypr
    load_state
    command -v grim >/dev/null || die "grim not installed"
    out="${1:-$DIR/shot.png}"
    mkdir -p "$(dirname "$out")"
    grim -o "$MON" "$out" && echo "$out"
    ;;

  clients)
    have_hypr
    load_state
    hyprctl clients -j | python3 -c '
import json, sys
rows = [c for c in json.load(sys.stdin) if c["workspace"]["id"] == int(sys.argv[1])]
if not rows:
    print("(no windows)")
for c in rows:
    print(c["address"], f"{c['"'"'class'"'"']:<16}", "at", c["at"], "size", c["size"], repr(c["title"][:40]))' "$WS"
    ;;

  hyprctl)
    shift
    have_hypr
    hyprctl "$@"
    ;;

  status)
    have_hypr
    if [ ! -f "$STATE" ]; then
      echo "sandbox: not started"
      exit 0
    fi
    load_state lenient
    echo "sandbox: $MON, workspace $WS, $(ws_windows "$WS" | wc -l) window(s)"
    ;;

  stop)
    have_hypr
    if [ ! -f "$STATE" ]; then
      echo "sandbox: not started"
      exit 0
    fi
    load_state lenient
    # Close the windows BEFORE the monitor goes away — see the notes.
    for addr in $(ws_windows "$WS"); do
      hyprctl dispatch "hl.dsp.window.close({ window = \"address:$addr\" })" >/dev/null 2>&1
    done
    sleep 1.5
    for addr in $(ws_windows "$WS"); do # anything that ignored the close
      hyprctl dispatch "hl.dsp.window.kill({ window = \"address:$addr\" })" >/dev/null 2>&1
    done
    # PINNED, and this is THE line he was feeling. `CMonitor::onDisconnect`
    # unconditionally snaps the cursor to the centre of the surviving monitor —
    # on a one-screen desktop, the middle of his screen — so every harness
    # teardown threw his mouse into the centre. Nothing in this script called a
    # cursor dispatcher, which is why an audit that grepped for one found
    # nothing. See sg_pointer_pin.
    # (Quiet inside the wrapper, not around it — sg_pointer_pin's own warning
    # about a failed restore must still reach the log.)
    sg_pointer_pin output_remove "$MON"

    G="$HOME/.local/state/hyprvtb/geometry.tsv"
    if [ -f "$G" ] && [ -s "$CLASSES" ]; then
      while read -r cls; do
        [ -n "$cls" ] || continue
        grep -v "^${cls}	" "$G" > "$G.tmp" 2>/dev/null && mv "$G.tmp" "$G"
      done < "$CLASSES"
    fi
    rm -f "$STATE" "$CLASSES"
    echo "sandbox: stopped"
    ;;

  *)
    sed -n '/^# USAGE/,/^# NOTES/p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac

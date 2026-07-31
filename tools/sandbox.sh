#!/usr/bin/env bash
# A monitor the user cannot see, for agents to test on.
#
# WHY THIS EXISTS
#
# Testing a desktop change used to mean opening a window on the live session:
# it steals focus, shoves the user's stack around, and drags whatever they were
# doing into the experiment. This gives that work somewhere else to happen.
#
# Hyprland can add a virtual output at runtime (`hyprctl output create
# headless`). It is a real monitor in every way the compositor cares about — it
# has workspaces, it renders every frame, and windows on it are decorated,
# animated and screenshottable — except that no cable leads anywhere. Windows
# launched onto it are invisible to the user, and `grim -o` reads its pixels
# back.
#
# The alternative (a nested Hyprland, as home/prog/hyprvtb/tools/nested-smoke.sh
# runs) is more isolated but appears as a WINDOW in the live session, so it is
# just as disruptive. Three headless-parent designs were tried and abandoned
# before this one: nixpkgs' cage is wlroots 0.17 and offers xdg_wm_base v5,
# which Hyprland's client side (v6) refuses; sway creates the headless output
# but has the same v5 ceiling; labwc has the right xdg-shell but on this NVIDIA
# box either advertises no usable DRM device (endless "Failed to allocate a GBM
# buffer: bo null") or hands the nested compositor no output at all. This
# approach needs no extra package and no nesting at all.
#
# THE TRADE-OFF, STATED PLAINLY: windows here are in the user's real session,
# decorated by the LIVE hyprvtb instance. Good for fidelity — you are testing
# the plugin that is actually running — but a plugin crash still takes the
# session down, and these are real clients of the real compositor. To test a
# plugin build that has NOT been switched to yet, use the nested harness.
#
# USAGE
#
#   tools/sandbox.sh start            create the virtual monitor
#   tools/sandbox.sh exec CMD...      launch a GUI program onto it (off-screen)
#   tools/sandbox.sh shot [FILE]      screenshot it (default /tmp/vtb-sandbox/shot.png)
#   tools/sandbox.sh clients          what is on it, with geometry
#   tools/sandbox.sh hyprctl ARGS...  plain hyprctl, for convenience
#   tools/sandbox.sh status           monitor + workspace + window count
#   tools/sandbox.sh stop             close its windows and remove the monitor
#
# NOTES
#
#  * A window launched here CANNOT TAKE THE KEYBOARD, and that is a compositor
#    rule rather than anything this script does after the fact:
#    `sandbox-never-takes-the-seat` in hyprland.lua is `no_focus` matched on the
#    `sandbox` tag below. `silent` only ever stopped the VIEW from switching —
#    the window still took focus at map time and held it for the two seconds
#    until the restore in `exec` noticed, once per launch, dozens of times in a
#    harness run (measured on the event socket, top 2026-07-30). The restore is
#    still there, as a net, and now warns if it ever fires.
#    The intended cost: nothing here can be typed into. A harness that must send
#    input to its subject wants a nested compositor with its own seat.
#  * A window launched here is also DEAF — `exec` prepends
#    `env PIPEWIRE_REMOTE=/dev/null PULSE_SERVER=/dev/null` so a test program
#    cannot play over whatever he is listening to. `SANDBOX_AUDIO=1` opts out.
#  * Every window launched here is TAGGED `sandbox` (an exec rule, so the
#    compositor applies it at map time — `hyprctl clients -j` shows
#    "tags": ["sandbox*"]). The monitor is what the panel filters on, since a
#    second REAL monitor's windows must keep appearing in the taskbar and
#    "which output" is the honest question there. The tag answers the other
#    one — "whose window is this" — which survives the window being moved, and
#    is what `stop` uses so a window dragged off the sandbox workspace is still
#    torn down instead of being left on the user's desktop.
#  * `exec` VERIFIES the placement afterwards and treats a miss as fatal. The
#    exec rule below places the window; until 2026-07-30 nothing checked that it
#    had, so a client the rule did not reach (a second toplevel, a splash, a
#    rule the compositor refused) simply opened in front of him and the harness
#    carried on. Now any sandbox-tagged window that is not on the sandbox
#    workspace is closed and the run aborts. It does not retry.
#  * Everything here goes through `lib/session-guard.sh`, which is also what
#    stops this script driving a compositor that is NOT his session — a stale
#    `HYPRLAND_INSTANCE_SIGNATURE` from somebody's nested test is an abort, not
#    a target.
#  * HIS POINTER IS PUT BACK, because the COMPOSITOR moves it and this script
#    cannot ask it not to. Removing an output makes Hyprland snap the cursor to
#    the centre of the surviving monitor, and `hl.dsp.focus({monitor=...})`
#    warps it to the focused window's middle; neither obeys `cursor:no_warps`.
#    Both call sites go through `sg_pointer_pin`, which restores the position it
#    read a moment earlier and nothing else. Nothing here may move his pointer
#    any other way.
#  * `stop` closes the sandbox's windows BEFORE removing the output — Hyprland
#    migrates the windows of a removed monitor onto a real one, which is
#    exactly what this exists to prevent. It then prunes the classes it
#    launched from the plugin's per-class geometry memory, so a test window's
#    size never becomes where the real app opens next time.
#  * Dispatchers go through `hl.dsp.*` Lua objects. NOT `hyprctl dispatch
#    <name>` (this config is Lua, so the argument is evaluated as Lua and a
#    bare dispatcher name is a nil global) and NOT `hyprctl keyword` (it
#    refuses outright: "keyword can't work with non-legacy parsers").

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

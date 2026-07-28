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
#  * `exec` restores keyboard focus to the monitor that had it. A new window
#    takes focus even with `silent` (silent only stops the VIEW switching), and
#    focus left sitting on an invisible monitor means the user's next keystroke
#    goes somewhere they cannot see. That is the one thing here that would
#    genuinely disturb them, so it is handled on every launch.
#  * Every window launched here is TAGGED `sandbox` (an exec rule, so the
#    compositor applies it at map time — `hyprctl clients -j` shows
#    "tags": ["sandbox*"]). The monitor is what the panel filters on, since a
#    second REAL monitor's windows must keep appearing in the taskbar and
#    "which output" is the honest question there. The tag answers the other
#    one — "whose window is this" — which survives the window being moved, and
#    is what `stop` uses so a window dragged off the sandbox workspace is still
#    torn down instead of being left on the user's desktop.
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

DIR="${VTB_SANDBOX_DIR:-/tmp/vtb-sandbox}"
STATE="$DIR/state"
CLASSES="$DIR/classes"

die() {
  echo "sandbox: $*" >&2
  exit 1
}

have_hypr() {
  hyprctl version >/dev/null 2>&1 || die "no live Hyprland session"
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
    # The bracket list is the exec dispatcher's own rule syntax: put the window
    # on the sandbox workspace without dragging the user's view along, and tag
    # it as ours so it stays identifiable wherever it ends up (see the notes).
    hyprctl dispatch "hl.dsp.exec_cmd(\"[workspace $WS silent; tag +sandbox] $*\")" >/dev/null \
      || die "exec dispatch failed"
    basename "$1" >> "$CLASSES" # for the geometry-memory prune in stop
    sleep 2
    if [ -n "$prev" ] && [ "$(focused_mon)" != "$prev" ]; then
      hyprctl dispatch "hl.dsp.focus({ monitor = \"$prev\" })" >/dev/null
    fi
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
    hyprctl output remove "$MON" >/dev/null 2>&1

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

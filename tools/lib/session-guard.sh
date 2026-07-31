#!/usr/bin/env bash
# session-guard.sh — the thing a harness sources so it cannot reach his session.
#
# WHY THIS EXISTS
#
# On 2026-07-30 he reported test windows appearing on his real monitor and his
# pointer being moved out from under him while agents ran tests. AGENTS.md ->
# "Testing without interfering with the user" already forbade both; what was
# missing was a MECHANISM, so every harness re-implemented the guard by hand and
# each one got a different subset of it right.
#
# The failure mode this is aimed at is the SILENT DEGRADE: a harness means to
# drive a nested compositor or an offscreen client, that target fails to come
# up, `WAYLAND_DISPLAY`/`HYPRLAND_INSTANCE_SIGNATURE` still name HIS session
# (they are inherited, and nothing clears them), and the test drives his desktop
# instead — successfully, quietly, with a green exit code. Every function here
# turns that into a loud abort.
#
# Sourced, not run:
#
#   . "$(dirname "$0")/lib/session-guard.sh"
#
# WHAT IT OFFERS
#
#   sg_live_sig                 HIS session's HYPRLAND_INSTANCE_SIGNATURE,
#                               RESOLVED (alive pid + live socket) rather than
#                               believed from the environment. Empty if there is
#                               no live Hyprland (a TTY, ssh) — not a fault.
#   sg_require_live_session     for a harness that deliberately uses the live
#                               compositor (tools/sandbox.sh): die unless
#                               `hyprctl` is reachable AND is talking to his
#                               session. A poisoned signature aiming us at some
#                               dead or nested instance is a bug, not a target.
#   sg_require_nested           the inverse, and the important one: die unless
#                               $HYPRLAND_INSTANCE_SIGNATURE / $WAYLAND_DISPLAY
#                               name something that is NOT his session. Call it
#                               after starting a nested compositor and before
#                               the first thing that would touch it. If the
#                               nested compositor did not come up, this is what
#                               stops the test from running against his desktop.
#   sg_require_offscreen        die unless QT_QPA_PLATFORM=offscreen is exported
#                               (or a nested target is in force). For harnesses
#                               that mean to render headless.
#   sg_seat_snapshot            record what he is focused on and where his
#                               pointer is.
#   sg_seat_assert              compare against that snapshot and warn on any
#                               change. Deliberately warn-only and deliberately
#                               NOT self-repairing: focusing something "back" is
#                               itself a focus grab, and warping the pointer
#                               "back" is itself a warp. The repair is to stop
#                               moving them.
#
# Every function here is read-only against his session.
#
# NOTE ON THE POINTER. `cursor:no_warps = true` in hyprland.lua, so focus
# changes do not drag the cursor along on this config — a pointer that moved
# means something warped it explicitly. That is worth catching by name.

# Guard against being sourced twice (a harness may source a sibling that
# sources this).
[ -n "${SG_SOURCED:-}" ] && return 0
SG_SOURCED=1

SG_ENVCHK="${SG_ENVCHK:-$HOME/.config/scripts/hypr-session-env.sh}"

sg_warn() { printf 'session-guard: %s\n' "$*" >&2; }
sg_die()  { printf 'session-guard: ABORT - %s\n' "$*" >&2; exit 90; }

# The live session's signature, resolved from $XDG_RUNTIME_DIR/hypr/*, never
# from our own environment — the environment is exactly what goes wrong.
sg_live_sig() {
  [ -x "$SG_ENVCHK" ] || return 0
  "$SG_ENVCHK" --print 2>/dev/null | sed -n 's/^HYPRLAND_INSTANCE_SIGNATURE=//p'
}

sg_live_wl() {
  [ -x "$SG_ENVCHK" ] || return 0
  "$SG_ENVCHK" --print 2>/dev/null | sed -n 's/^WAYLAND_DISPLAY=//p'
}

# For a harness that MEANS to use the live compositor.
sg_require_live_session() {
  hyprctl version >/dev/null 2>&1 || sg_die \
    "no reachable Hyprland. HYPRLAND_INSTANCE_SIGNATURE=${HYPRLAND_INSTANCE_SIGNATURE:-<unset>} names nothing alive.
    Repair the manager environment before retrying:  $SG_ENVCHK --restore"
  local live cur
  live=$(sg_live_sig)
  cur=${HYPRLAND_INSTANCE_SIGNATURE:-}
  # Empty `live` = the resolver found no session (TTY/ssh); we still have a
  # reachable compositor, so carry on rather than block a legitimate run.
  [ -n "$live" ] || return 0
  [ -z "$cur" ] || [ "$cur" = "$live" ] || sg_die \
    "this shell points at a DIFFERENT Hyprland than his session.
    ours: $cur
    his:  $live
    A test compositor left its signature behind. Repair:  $SG_ENVCHK --restore"
}

# For a harness that means to use a NESTED compositor. THE anti-fallthrough
# check: call it once the nested instance is supposed to be up.
sg_require_nested() {
  local live_sig live_wl
  live_sig=$(sg_live_sig)
  live_wl=$(sg_live_wl)
  [ -n "${WAYLAND_DISPLAY:-}" ] || sg_die \
    "WAYLAND_DISPLAY is unset where a nested compositor was expected.
    The nested target never came up; running on would drive his session."
  if [ -n "$live_wl" ] && [ "$WAYLAND_DISPLAY" = "$live_wl" ]; then
    sg_die "WAYLAND_DISPLAY=$WAYLAND_DISPLAY IS his session's.
    The nested compositor did not come up and this run would land on his screen."
  fi
  if [ -n "$live_sig" ] && [ "${HYPRLAND_INSTANCE_SIGNATURE:-}" = "$live_sig" ]; then
    sg_die "HYPRLAND_INSTANCE_SIGNATURE is his session's ($live_sig).
    The nested compositor did not come up and this run would drive his desktop."
  fi
  return 0
}

# For a harness that renders headless. A nested target counts as satisfying it.
sg_require_offscreen() {
  [ "${QT_QPA_PLATFORM:-}" = offscreen ] && return 0
  local live_wl
  live_wl=$(sg_live_wl)
  [ -n "${WAYLAND_DISPLAY:-}" ] && [ -n "$live_wl" ] && \
    [ "$WAYLAND_DISPLAY" != "$live_wl" ] && return 0
  sg_die "QT_QPA_PLATFORM is '${QT_QPA_PLATFORM:-<unset>}' and WAYLAND_DISPLAY
    (${WAYLAND_DISPLAY:-<unset>}) is his session's — this client would open a
    window on his monitor. Export QT_QPA_PLATFORM=offscreen, or use
    tools/sandbox.sh, or start a nested compositor."
}

# --- the seat: his focus and his pointer -------------------------------------

SG_SEAT_WIN=""
SG_SEAT_CUR=""

sg_seat_snapshot() {
  hyprctl version >/dev/null 2>&1 || return 0
  SG_SEAT_WIN=$(hyprctl -j activewindow 2>/dev/null \
    | sed -n 's/.*"address": "\([^"]*\)".*/\1/p' | head -1)
  SG_SEAT_CUR=$(hyprctl cursorpos 2>/dev/null)
}

# sg_seat_assert — did we borrow his focus or his pointer?
# Returns 1 if anything moved, so a caller can fail on it; warns either way.
sg_seat_assert() {
  hyprctl version >/dev/null 2>&1 || return 0
  local win cur moved=0
  win=$(hyprctl -j activewindow 2>/dev/null \
    | sed -n 's/.*"address": "\([^"]*\)".*/\1/p' | head -1)
  cur=$(hyprctl cursorpos 2>/dev/null)
  if [ -n "$SG_SEAT_WIN" ] && [ "$win" != "$SG_SEAT_WIN" ]; then
    sg_warn "this run MOVED HIS KEYBOARD FOCUS: $SG_SEAT_WIN -> ${win:-<none>}"
    moved=1
  fi
  if [ -n "$SG_SEAT_CUR" ] && [ "$cur" != "$SG_SEAT_CUR" ]; then
    # He moves his own mouse constantly, so this is only meaningful for a
    # harness that ran with him away from it — it is a warning, never a fault,
    # and never restored (warping it "back" is itself a warp he did not ask
    # for).
    sg_warn "the pointer is not where this run found it: $SG_SEAT_CUR -> $cur"
    moved=1
  fi
  return $((moved ? 1 : 0))
}

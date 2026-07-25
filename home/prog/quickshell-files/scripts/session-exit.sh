#!/bin/sh
# Graceful session exit for the power menu (logout / reboot / poweroff).
#
# Before the compositor is torn down, "click the [x]" on every open window so
# each app quits cleanly and persists its own state — and snapshot the session
# so the next fresh login relaunches every window at the position it was closed
# in. Both halves live in the hyprvtb plugin, behind one Lua entry point:
# hyprvtb.save_close() saves the snapshot (~/.local/state/hyprvtb/session.tsv,
# replayed by vtbRestoreSession at the next login) and then sends a graceful
# xdg close to every decorated window (see main.cpp).
#
# It must be invoked with `hyprctl eval`, NOT `hyprctl dispatch`: under the Lua
# config, `hyprctl dispatch X` evaluates X as a Lua expression and then demands
# a dispatcher object back, so the old `hyprctl dispatch hyprvtbsaveclose`
# (a plugin dispatcher name) resolved to an undefined global and silently did
# nothing — logout neither saved the session nor closed anything gracefully.
#
# sendClose only *requests* the close; clients go away asynchronously, so we
# then wait for the windows to actually vanish — giving apps time to flush —
# before returning. The caller chains the real power action after us
# (`session-exit.sh && systemctl poweroff`), so returning is the go signal.
# Bounded by a timeout: an app that puts up an unsaved-changes dialog (or
# otherwise refuses to close) must not wedge shutdown forever — after ~4s we
# proceed regardless and the power action reaps whatever is left.

hyprctl eval "hl.plugin.hyprvtb.save_close()" >/dev/null 2>&1

# Count still-open, real windows: mapped, on a normal (non-special/scratchpad)
# workspace, excluding the slide-in scratch terminal.
remaining() {
  hyprctl clients -j 2>/dev/null | jq '
    [ .[]
      | select(.mapped == true)
      | select(.workspace.id >= 0)
      | select(.class != "hyprvtb-scratch")
    ] | length' 2>/dev/null
}

i=0
while [ "$i" -lt 40 ]; do
  n=$(remaining)
  # jq/hyprctl hiccup -> empty: don't loop forever on a broken read, just go.
  [ -n "$n" ] || break
  [ "$n" -eq 0 ] && break
  sleep 0.1
  i=$((i + 1))
done

exit 0

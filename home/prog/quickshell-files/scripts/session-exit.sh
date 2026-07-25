#!/bin/sh
# Graceful session exit for the power menu (logout / reboot / poweroff).
#
# Before the compositor is torn down, "click the [x]" on every open window so
# each app quits cleanly and persists its own state — and so the plugin's own
# window.close handler records where the window was, which is what makes an app
# reopen at the size and position you left it (per-class geometry,
# ~/.local/state/hyprvtb/geometry.tsv). That is the whole point of this step.
# It does NOT snapshot a session for relaunch: logging back in should not spawn
# anything. hyprvtb.close_all() is the one Lua entry point (see main.cpp).
#
# It must be invoked with `hyprctl eval`, NOT `hyprctl dispatch`: under the Lua
# config, `hyprctl dispatch X` evaluates X as a Lua expression and then demands
# a dispatcher object back, so the old `hyprctl dispatch hyprvtbsaveclose`
# (a plugin dispatcher name) resolved to an undefined global and silently did
# nothing — logout closed nothing gracefully, so nothing remembered anything.
#
# sendClose only *requests* the close; clients go away asynchronously, so we
# then wait for the windows to actually vanish — giving apps time to flush —
# before returning. The caller chains the real power action after us
# (`session-exit.sh && systemctl poweroff`), so returning is the go signal.
# Bounded by a timeout: an app that puts up an unsaved-changes dialog (or
# otherwise refuses to close) must not wedge shutdown forever — after ~4s we
# proceed regardless and the power action reaps whatever is left.

hyprctl eval "hl.plugin.hyprvtb.close_all()" >/dev/null 2>&1

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

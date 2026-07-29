#!/usr/bin/env bash
# What happens when the laptop lid closes — a user setting, not a hardcode.
#
# Only `book` (the MacBook Air) has a lid; `top` is a desktop, so the unit and
# the binds that call this are gated on the host (home/srvs/lid.nix,
# hyprland.lua's `host.laptop`). See home/srvs/lid.nix for the whole mechanism.
#
# The setting is `lidClose` in ~/.config/quickshell/settings.json — the
# desktop's one cross-program settings file — and the Settings window's
# "Lock & Power" page draws it (SetPgSession.qml). Values:
#
#   suspend   systemctl suspend            (the default, and what logind would
#                                           have done on its own)
#   lock      qs ipc call lock activate    lock the session, screen stays on
#   blank     hyprctl dispatch dpms off    turn the display off, don't lock
#   nothing   do nothing at all
#
# ANY failure to read the setting falls back to `suspend`, deliberately: an
# unreadable or absent settings.json must leave the machine behaving the way it
# did before this file existed, never "the lid does nothing".
set -uo pipefail

SETTINGS="${XDG_CONFIG_HOME:-$HOME/.config}/quickshell/settings.json"

action=$(python3 - "$SETTINGS" <<'PY' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1]) as f:
        v = json.load(f).get("lidClose", "suspend")
except Exception:
    v = "suspend"
print(v if v in ("suspend", "lock", "blank", "nothing") else "suspend")
PY
)
[ -n "$action" ] || action=suspend

case "$1:$action" in
    # ---- lid closed ----
    # `lock activate` is the panel's lock, the same entry point Meta+L and
    # hypridle use, so the lid gets the identical lock screen.
    close:lock)    exec qs ipc call lock activate ;;
    close:blank)   exec hyprctl dispatch dpms off ;;
    # Not `qs ipc call lock suspend` — hypridle's before_sleep_cmd already runs
    # that on logind's sleep signal, and it is the half that honours the
    # `lockOnSuspend` setting. Asking for the suspend is all this has to do.
    close:suspend) exec systemctl suspend ;;
    close:nothing) exit 0 ;;

    # ---- lid opened ----
    # Unconditional, whatever the setting is: the only thing that can be wrong
    # after an open is a screen that is still off, and a lid you cannot wake is
    # the one failure mode here that looks like a dead machine. Harmless when
    # the display was never blanked.
    open:*)        exec hyprctl dispatch dpms on ;;
esac

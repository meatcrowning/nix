# Kitty loads this module once per process and calls `main()` for OSC 99/777
# notifications. Returning True drops the event before it reaches Quickshell.
# It suppresses repeats for the same window/app/title/body, and drops a toast
# when its source window already has keyboard focus. Focus acknowledges the
# record; otherwise it expires after REPEAT_WINDOW. This catches Claude Code's
# recurring idle prompt without suppressing a later prompt after a reply.
#
# The hook is limited to notifications emitted by programs inside kitty;
# notify-send and panel/app toasts do not pass through it. Reloading kitty's
# config does not rebuild NotificationManager, so existing processes need a new
# kitty window/process to load changes.

from time import monotonic

# Backstop for an unacknowledged record; focus is the normal acknowledgement.
REPEAT_WINDOW = 900.0

# Sweep only runs while records exist; the common case has no timer.
POLL_INTERVAL = 4.0

_last_shown: dict[tuple[int, str, str, str], float] = {}
_timer_armed = False


def _has_focus(channel_id: int) -> bool:
    """Whether the source kitty window currently holds keyboard focus."""
    try:
        from kitty.notifications import Channel
        return Channel().ui_state(channel_id).has_keyboard_focus
    except Exception:
        return False


def _arm_sweep() -> None:
    global _timer_armed
    if _timer_armed or not _last_shown:
        return
    try:
        from kitty.fast_data_types import add_timer
        add_timer(_sweep, POLL_INTERVAL, False)
        _timer_armed = True
    except Exception:
        pass


def _sweep(timer_id: int = 0) -> None:
    global _timer_armed
    _timer_armed = False
    try:
        now = monotonic()
        for key in list(_last_shown):
            if now - _last_shown[key] > REPEAT_WINDOW or _has_focus(key[0]):
                del _last_shown[key]
    except Exception:
        _last_shown.clear()
        return
    _arm_sweep()


def main(nc) -> bool:
    """Return True when this notification should be filtered."""
    try:
        key = (nc.channel_id, nc.application_name or '', nc.title or '', nc.body or '')
        if _has_focus(nc.channel_id):
            _last_shown.pop(key, None)
            return True
        now = monotonic()
        previous = _last_shown.get(key)
        _last_shown[key] = now
        _arm_sweep()
        return previous is not None and now - previous <= REPEAT_WINDOW
    except Exception:
        # Filtering must fail open.
        return False

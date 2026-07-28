# kitty desktop-notification filter.
#
# kitty loads ~/.config/kitty/notifications.py once, at process start
# (Boss.__init__ -> NotificationManager), and calls main() for every desktop
# notification a program running inside kitty raises over OSC 99 / OSC 777.
# Returning True drops the notification before it reaches the Quickshell
# notification server. See kitty/notifications.py: is_notification_filtered().
#
# WHY THIS EXISTS
#
# Claude Code raises an "idle prompt" notification — title "Claude Code", body
# "Claude is waiting for your input" — once its session has sat idle for
# `messageIdleNotifThresholdMs` (default 60000, a key in ~/.claude.json, NOT in
# settings.json). Its React effect re-arms that timeout whenever any of its
# dependencies change, and firing the notification is itself enough to change
# one, so the same notification is raised again every ~60 s for as long as the
# session stays idle — the only thing that stops it is the user typing. It also
# hands kitty a FRESH RANDOM notification id each time (`i=` in the escape
# code), so kitty cannot coalesce them either: every repeat is a brand new
# toast, with its own Vista sound. Claude Code exposes no repeat/debounce
# setting and its `Notification` hook is side-effect-only — it cannot suppress.
# So the de-duplication has to happen here, in the terminal that is forwarding
# the escape code.
#
# THE TWO RULES
#
# 1. The window that raised it currently has the keyboard. A toast about the
#    window you are looking at is pure noise, and the terminal is already
#    showing you the prompt.
# 2. The same (window, app, title, body) was already shown recently. The first
#    one goes through; the nagging repeats do not.
#
# A record is forgotten as soon as the window regains focus (i.e. you came back
# and looked), or after REPEAT_WINDOW. That is what keeps this from swallowing
# a *genuine* second notification: reply to Claude, and the act of focusing the
# terminal clears the record, so the next time it goes idle you are told again.
# Without that, a fixed time window would have to be shorter than one turn.
#
# It is deliberately app-agnostic. The only programs whose notifications reach
# this function are ones running inside kitty that speak OSC 99/777 — nothing
# that talks to the D-Bus server directly (notify-send, the panel's own toasts,
# surfer/filer progress) passes through here at all, so the blast radius is
# small and "don't show me the same thing twice while I'm away" is a fair rule
# for all of it.
#
# CAVEAT: loaded once per kitty PROCESS. An already-running kitty will not pick
# this up — `kitty @ load-config` re-reads options only, it does not rebuild the
# NotificationManager. New kitty windows get it.

from time import monotonic

# How long an unacknowledged notification suppresses identical repeats. Long on
# purpose: focus is the real acknowledgement (see _sweep), this is just the
# backstop for a window you never return to.
REPEAT_WINDOW = 900.0

# How often to check whether the window has been looked at. Only armed while
# something is actually being suppressed, and re-armed from its own callback,
# so kitty carries no timer at all in the common case.
POLL_INTERVAL = 4.0

_last_shown: dict[tuple[int, str, str, str], float] = {}
_timer_armed = False


def _has_focus(channel_id: int) -> bool:
    """True if the kitty window that raised the notification holds the keyboard.

    channel_id is the kitty window id; Channel.ui_state() is what kitty itself
    uses to honour a notification's `o=unfocused`.
    """
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
    """Return True to drop the notification."""
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
        # Never let a bug here cost the user a notification.
        return False

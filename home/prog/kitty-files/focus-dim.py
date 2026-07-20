# kitty focus-dim watcher — referenced from kitty.conf via `watcher focus-dim.py`.
#
# Greys kitty's default text colour when its OS window loses focus, so an
# unfocused terminal reads as "inactive" in the same tone that filer and the
# hyprvtb titlebar fade to (#595959). On focus it restores the live (wal)
# foreground from the current config, so it survives wallpaper/theme reloads.
#
# Only default_fg is touched — the ANSI colour table (coloured program output)
# is left alone, so this greys the bulk of the text (prompt, typed commands,
# default output) without turning coloured output into an unreadable grey blob.
# on_focus_change fires on OS-window focus changes too, not just kitty splits.

from kitty.rgb import color_from_int

INACTIVE = color_from_int(0x595959)  # == filer Theme.inactive / hyprvtb col.inactive


def on_focus_change(boss, window, data):
    try:
        cp = window.screen.color_profile
        cp.default_fg = boss.opts.foreground if data.get('focused') else INACTIVE
        window.refresh()
    except Exception:
        pass

{ ... }:

# Oxygen's own settings — `~/.config/oxygenrc` — declared, because they are an
# INPUT TO OUR CODE and not just a look he picked once.
#
# In a Plasma session our apps are real KDE windows (`apps/pylib/kdeshell.py`)
# and the widget style paints them. `kdeglobals` carries the colour scheme, the
# font and one animation factor, and `apps/pylib/kdetheme.py` already moves all
# three across. The style has a SECOND store that kdeglobals knows nothing
# about, and it is the one that says how wide a scrollbar is, how long a hover
# fade lasts, how big a tree expander's triangle is and whether a tooltip is
# translucent. Every real QWidget in one of our windows obeys it already; the
# QML inside the `QQuickWidget` is the half that did not, until
# `apps/pylib/oxygenstyle.py` started reading it and publishing it through
# `DeskStyle.style*`.
#
# So this file is half configuration and half contract: what is declared here is
# what those apps draw with. `oxygen-settings6` (in `kdePackages.oxygen`, on
# PATH) is the GUI that writes the same file — a value it sets that is declared
# below is reverted at the next switch, which is deliberate and the same rule as
# `kwinrc ButtonsOnRight` in home/plasma.nix. Everything NOT named here stays
# his to change from that dialog, and the reader falls back to upstream's own
# compiled-in default (`kstyle/oxygen.kcfg` in github.com/KDE/oxygen) for any key
# neither of us has set — so an unset key is a known number, not an unknown one.
#
# Both hosts, and on both it is LIVE: `programs.plasma` is enabled
# unconditionally in home/plasma.nix and `home/` is evaluated by `top` and
# `book` alike. This comment used to claim book had no Plasma and that the file
# was therefore inert there — it was wrong, corrected 2026-08-25: book runs a
# Plasma session wearing Oxygen, which is what chatter's `+oxygen` face is
# developed against.
#
# NOT set here, on purpose — the durations (`GenericAnimationsDuration` 150,
# `MenuAnimationsDuration` 150, `ProgressBarBusyStepDuration` 50) and the
# metrics (`ScrollBarWidth` 15, `ViewTriangularExpanderSize` TE_SMALL). Those
# are the numbers our QML now READS; pinning them here would make this file the
# source and the style the follower, which is backwards. He moves them in
# `oxygen-settings6` and the apps follow.
{
  programs.plasma.configFile.oxygenrc = {
    # ---- the window drag ----------------------------------------------------
    # Oxygen's WindowManager drags the window from every unclaimed pixel
    # (`WD_FULL`, upstream's default) — including from inside a QQuickWidget,
    # which only ever sees a press nothing in the QML scene accepted. That is
    # the behaviour `apps/painter/qml/Root.qml` already defends against with a
    # full-window MouseArea at `z: -1000`, and that guard STAYS: it is
    # session-independent and it is the only thing protecting an app on a
    # machine where this file has not been applied.
    #
    # `WD_MINIMAL` is upstream's own supported narrowing — drag from the
    # titlebar, the menubar, the toolbar and empty dialog space, and nowhere
    # else — so every Oxygen window on the box behaves the way ours already had
    # to be made to. (`WindowDragWhiteList`/`BlackList` take window-class
    # patterns if a single app ever needs an exception.)
    Style.WindowDragEnabled = true;
    Style.WindowDragMode = "WD_MINIMAL";

    # ---- the two debug modes, named so they are known to exist --------------
    # WidgetExplorer prints the widget under the pointer with its full class
    # hierarchy; DrawWidgetRects outlines every primitive the style paints.
    # Both are Oxygen's own and both are the fastest way to see where a
    # QQuickWidget's boundary actually falls. Declared OFF rather than left
    # unset so a debugging session cannot leave one of them on for good.
    Style.WidgetExplorerEnabled = false;
    Style.DrawWidgetRects = false;

    # ---- his, captured ------------------------------------------------------
    # These four were already in the live file, set by hand or by the KCM
    # before this module existed. Declared so they survive a fresh machine and
    # so `book` gets the same window.
    Style.StackedWidgetTransitionsEnabled = true;
    ActiveShadow.Enabled = false;
    Windeco.ButtonSize = "ButtonSmall";

    # TitleAlignment is NOT declared: he sets it himself (AlignLeft as of
    # 2026-09-05) and a declared value is re-asserted on EVERY switch, so
    # pinning it silently reverted his choice every time anything here was
    # rebuilt. Same reasoning as kwinrc ButtonsOnRight in home/plasma.nix.
  };
}

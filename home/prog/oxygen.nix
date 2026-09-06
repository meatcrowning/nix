{ host, ... }:

# `oxygenrc` is live input to both hosts' Plasma apps and their QML DeskStyle
# bridge. Values declared here are reset at each switch; undeclared values stay
# user-owned through oxygen-settings6 and fall back to Oxygen defaults. Keep
# animation durations and metrics undeclared so the apps follow the style.
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
    # Air alone uses normal titlebar controls.  Keeping this host-scoped makes
    # each profile durable across refreshes: top retains its small controls.
    Windeco.ButtonSize = if host == "air" then "ButtonNormal" else "ButtonSmall";

    # Titlebar geometry is shared across hosts. Leaving this mutable made
    # top's title text AlignLeft and book's AlignRight even though both selected
    # the same Oxygen decoration.
    Windeco.TitleAlignment = "AlignLeft";
  };
}

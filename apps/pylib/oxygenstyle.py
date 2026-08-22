"""Oxygen's own settings — `~/.config/oxygenrc` — as numbers the apps can draw with.

`kdetheme.py` moves the *palette*, the *font* and the *motion factor* to
`kdeglobals` in a Plasma session. That is everything KDE publishes about a
colour scheme, and it is still not everything the window is made of: the widget
style has a second store of its own, and under Oxygen that store says how wide
a scrollbar is, how long a hover fade lasts, how big a tree expander's triangle
is, whether a tooltip is translucent, and whether a toolbar draws separators.
Every real Qt *widget* in one of our Plasma windows already obeys it — Oxygen
reads it itself. The half that does not is our QML: `apps/*/qml/+plasma/*.qml`
hand-draws the controls that live inside the `QQuickWidget`, and until this
module those numbers were literals picked by eye. Two scrollbars of different
widths in one window is the same "one odd window" failure `kdeshell.py` exists
to prevent, one level down.

So: **in a Plasma session running Oxygen, Oxygen's own rc is the source for the
metrics and the motion our QML draws.** Nothing here is read in the Hyprland
session — there the desktop's own numbers (`docs/DESIGN.md`, the panel's
`settings.json`, hyprvtb's slide duration) are authoritative and Oxygen is not
installed in the window at all.

    from oxygenstyle import read_oxygen, is_oxygen
    if is_oxygen():
        ox = read_oxygen()
        width = ox["ScrollBarWidth"]        # 15, or whatever he set

`DeskStyle` (deskstyle.py) is what actually publishes these to QML, on the same
watch as everything else; this module is the reader and the defaults table, and
holds no Qt.

**The defaults table is upstream's, verbatim.** `kstyle/oxygen.kcfg` in
`github.com/KDE/oxygen` (6.7.4) — an entry absent from the rc is not "unset",
it is the compiled-in default, and reading `oxygenrc` alone would have most of
these missing on a machine that never opened the KCM. `oxygen-settings6` (in
`kdePackages.oxygen`, already on PATH) is the GUI that writes the file, and
`home/prog/oxygen.nix` is where the values this desktop pins are declared.
Adding a key here is one row in `_KEYS` plus, if QML needs it, one property in
`deskstyle.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

from kdetheme import is_plasma, kde_widget_style, read_ini

# name -> (kind, default). Kinds: "b" bool, "i" int, "e" enum (default names the
# member), "s" string. Straight from kstyle/oxygen.kcfg, [Common] and [Style];
# `oxygenrc` writes both groups flat under their own headers, and nothing here
# needs to know which group a key came from — the names do not collide.
_KEYS: dict[str, tuple[str, object]] = {
    # [Common]
    "UseBackgroundGradient":            ("b", True),
    # [Style] — painting
    "MnemonicsMode":                    ("e", "MN_ALWAYS"),
    "SliderDrawTickMarks":              ("b", True),
    "ToolTipTransparent":               ("b", True),
    "ToolBarDrawItemSeparator":         ("b", True),
    "ViewDrawFocusIndicator":           ("b", False),
    "ViewTriangularExpanderSize":       ("e", "TE_SMALL"),
    "ViewDrawTreeBranchLines":          ("b", True),
    "ViewInvertSortIndicator":          ("b", False),
    "ScrollBarWidth":                   ("i", 15),
    "ScrollBarAddLineButtons":          ("i", 2),
    "ScrollBarSubLineButtons":          ("i", 1),
    "ProgressBarAnimated":              ("b", True),
    "MenuHighlightMode":                ("e", "MM_DARK"),
    "SplitterProxyEnabled":             ("b", True),
    "SplitterProxyWidth":               ("i", 12),
    # [Style] — window dragging. WindowDragMode is the supported answer to
    # "Oxygen drags my window from everywhere": WD_FULL (upstream's default)
    # drags from any unclaimed pixel INCLUDING inside a QQuickWidget, which is
    # why painter's Root.qml carries a full-window MouseArea at z:-1000. That
    # guard stays — it is session-independent and defends against WD_FULL on
    # any machine — but WD_MINIMAL narrows the style itself to the chrome.
    "WindowDragEnabled":                ("b", True),
    "WindowDragMode":                   ("e", "WD_FULL"),
    "UseWMMoveResize":                  ("b", True),
    # [Style] — the two debug modes. WidgetExplorer prints the widget under the
    # pointer with its full class hierarchy; DrawWidgetRects outlines every
    # primitive Oxygen paints. Both are Oxygen's own, both are off by default,
    # and both are worth knowing about when a QQuickWidget's boundary is the
    # thing under investigation.
    "WidgetExplorerEnabled":            ("b", False),
    "DrawWidgetRects":                  ("b", False),
    # [Style] — animation. AnimationsEnabled is the master switch; the per-kind
    # flags gate a class of them and the durations are milliseconds. KDE's own
    # [KDE] AnimationDurationFactor (kdetheme.kde_motion) still scales all of
    # them on top — the two are independent controls and both apply.
    "AnimationsEnabled":                ("b", True),
    "GenericAnimationsEnabled":         ("b", True),
    "ProgressBarAnimationsEnabled":     ("b", True),
    "StackedWidgetTransitionsEnabled":  ("b", False),
    "LabelTransitionsEnabled":          ("b", True),
    "ComboBoxTransitionsEnabled":       ("b", True),
    "LineEditTransitionsEnabled":       ("b", True),
    "ToolBarAnimationType":             ("e", "TB_FADE"),
    "MenuBarAnimationType":             ("e", "MB_FADE"),
    "MenuAnimationType":                ("e", "ME_FADE"),
    "GenericAnimationsDuration":        ("i", 150),
    "ToolBarAnimationsDuration":        ("i", 50),
    "MenuBarAnimationsDuration":        ("i", 150),
    "MenuBarFollowMouseAnimationsDuration": ("i", 80),
    "MenuAnimationsDuration":           ("i", 150),
    "MenuFollowMouseAnimationsDuration": ("i", 40),
    "ProgressBarAnimationsDuration":    ("i", 250),
    "ProgressBarBusyStepDuration":      ("i", 50),
    "StackedWidgetTransitionsDuration": ("i", 150),
    "LabelTransitionsDuration":         ("i", 75),
    "ComboBoxTransitionsDuration":      ("i", 75),
    "LineEditTransitionsDuration":      ("i", 150),
    # [Windeco] — the decoration's, not the style's (kdecoration/oxygensettingsdata.kcfg).
    # Read for completeness: a client-side chrome that wants to agree with the
    # server-side titlebar needs its alignment and button size.
    "TitleAlignment":                   ("e", "AlignCenterFullWidth"),
    "ButtonSize":                       ("e", "ButtonDefault"),
    "BorderSize":                       ("e", "BorderNoSides"),
    "UseWindowColors":                  ("b", True),
    "HideTitleBar":                     ("b", False),
}

# Every enum's legal members, so a hand-edited rc cannot put a string nothing
# understands into a QML binding. An unknown value falls back to the default.
_ENUMS: dict[str, tuple[str, ...]] = {
    "MnemonicsMode":              ("MN_NEVER", "MN_AUTO", "MN_ALWAYS"),
    "ViewTriangularExpanderSize": ("TE_TINY", "TE_SMALL", "TE_NORMAL"),
    "MenuHighlightMode":          ("MM_DARK", "MM_SUBTLE", "MM_STRONG"),
    "WindowDragMode":             ("WD_NONE", "WD_MINIMAL", "WD_FULL"),
    "ToolBarAnimationType":       ("TB_NONE", "TB_FADE", "TB_FOLLOW_MOUSE"),
    "MenuBarAnimationType":       ("MB_NONE", "MB_FADE", "MB_FOLLOW_MOUSE"),
    "MenuAnimationType":          ("ME_NONE", "ME_FADE", "ME_FOLLOW_MOUSE"),
    "TitleAlignment":             ("AlignLeft", "AlignCenter",
                                   "AlignCenterFullWidth", "AlignRight"),
    "ButtonSize":                 ("ButtonSmall", "ButtonDefault", "ButtonLarge",
                                   "ButtonVeryLarge", "ButtonHuge"),
    "BorderSize":                 ("BorderNone", "BorderNoSides", "BorderTiny",
                                   "BorderNormal", "BorderLarge", "BorderVeryLarge",
                                   "BorderHuge", "BorderVeryHuge", "BorderOversized"),
}

# The triangular expander, as Oxygen actually draws it: `genericArrow()` in
# kstyle/oxygenstyle.cpp emits a polyline whose half-extent along the wide axis
# is this, at this pen width. Doubling gives the arrow's drawn width in px —
# which is what a QML expander needs to match a QTreeView's in the same window.
_EXPANDER = {"TE_TINY":   (2.25, 1.2),
             "TE_SMALL":  (2.5,  1.2),
             "TE_NORMAL": (3.5,  1.6)}


def oxygenrc_path() -> Path:
    """Oxygen's store. `DESK_OXYGENRC` retargets it — the twin of
    `DESK_KDEGLOBALS` in kdetheme, and how the test renders a configuration
    that is not his. Read on every call so a test can move it after import."""
    return Path(os.environ.get("DESK_OXYGENRC")
                or (Path.home() / ".config" / "oxygenrc"))


def is_oxygen(ini=None) -> bool:
    """True when this session is Plasma AND the widget style is Oxygen.

    Both halves matter. Outside Plasma nothing here applies at all; inside it
    with Breeze picked, Oxygen's rc still exists on disk (it is never deleted)
    and reading it would dress our QML in the numbers of a style the window is
    not wearing. `kde_widget_style` already falls back to the look-and-feel
    package's own default, which is where a stock Oxygen session records it.
    """
    return is_plasma() and kde_widget_style(ini) == "oxygen"


def read_oxygen(path=None) -> dict:
    """Every key in `_KEYS`, typed, with upstream's default where the rc is
    silent or holds something unreadable.

    Always returns a complete dict — a missing file is a fully-default Oxygen,
    which is exactly what a machine that never opened the KCM is running.
    """
    ini = read_ini(path or oxygenrc_path())
    flat: dict[str, str] = {}
    for group in ini.values():
        flat.update(group)
    out: dict = {}
    for name, (kind, default) in _KEYS.items():
        raw = flat.get(name)
        out[name] = default if raw is None else _coerce(kind, raw, default, name)
    return out


def _coerce(kind, raw, default, name):
    raw = raw.strip()
    if kind == "b":
        low = raw.lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        return default
    if kind == "i":
        try:
            return int(float(raw))
        except ValueError:
            return default
    if kind == "e":
        return raw if raw in _ENUMS.get(name, ()) else default
    return raw or default


def motion(ox=None) -> dict:
    """The durations our QML should animate at, in ms, with Oxygen's own
    enable flags already folded in — a disabled class of animation comes back
    as 0, which is what every `Behavior` here treats as "no animation".

    `generic` is the one most QML wants: it is what Oxygen fades a button's
    hover and a widget's enabled state at, so a hand-drawn control that uses it
    changes state in step with the real widgets beside it.
    """
    ox = read_oxygen() if ox is None else ox
    on = ox["AnimationsEnabled"]

    def d(flag, key):
        return ox[key] if (on and ox[flag]) else 0

    return {
        "generic":  d("GenericAnimationsEnabled", "GenericAnimationsDuration"),
        "toolbar":  ox["ToolBarAnimationsDuration"] if on else 0,
        "menubar":  ox["MenuBarAnimationsDuration"] if on else 0,
        "menu":     ox["MenuAnimationsDuration"] if on else 0,
        "progress": d("ProgressBarAnimationsEnabled", "ProgressBarAnimationsDuration"),
        "busyStep": d("ProgressBarAnimationsEnabled", "ProgressBarBusyStepDuration"),
        "stack":    d("StackedWidgetTransitionsEnabled", "StackedWidgetTransitionsDuration"),
        "label":    d("LabelTransitionsEnabled", "LabelTransitionsDuration"),
        "combo":    d("ComboBoxTransitionsEnabled", "ComboBoxTransitionsDuration"),
        "lineEdit": d("LineEditTransitionsEnabled", "LineEditTransitionsDuration"),
    }


def metrics(ox=None) -> dict:
    """The sizes and the on/off draws, including the two Oxygen states its own
    source derives rather than stores.

    `scrollButtonHeight` is `qMax(width * 7 / 10, 14)` per scrollbar button
    (kstyle/oxygenstyle.cpp `_singleButtonHeight`), so a QML scrollbar with
    buttons reserves the same room a QScrollBar does. `expanderWidth` /
    `expanderPen` come from the arrow polygon, see `_EXPANDER`.
    """
    ox = read_oxygen() if ox is None else ox
    half, pen = _EXPANDER[ox["ViewTriangularExpanderSize"]]
    width = max(1, ox["ScrollBarWidth"])
    return {
        "scrollWidth":        width,
        "scrollAddButtons":   max(0, min(2, ox["ScrollBarAddLineButtons"])),
        "scrollSubButtons":   max(0, min(2, ox["ScrollBarSubLineButtons"])),
        "scrollButtonHeight": max(width * 7 // 10, 14),
        "expanderWidth":      half * 2,
        "expanderPen":        pen,
        "splitterWidth":      ox["SplitterProxyWidth"] if ox["SplitterProxyEnabled"] else 0,
        "focusIndicator":     ox["ViewDrawFocusIndicator"],
        "treeBranchLines":    ox["ViewDrawTreeBranchLines"],
        "toolbarSeparators":  ox["ToolBarDrawItemSeparator"],
        "tooltipTransparent": ox["ToolTipTransparent"],
        "sliderTicks":        ox["SliderDrawTickMarks"],
        "backgroundGradient": ox["UseBackgroundGradient"],
        "menuHighlight":      ox["MenuHighlightMode"],
        "mnemonics":          ox["MnemonicsMode"],
    }


if __name__ == "__main__":   # `python3 oxygenstyle.py` — what this box resolves to
    import json
    resolved = read_oxygen()
    print(json.dumps({"path": str(oxygenrc_path()),
                      "isOxygen": is_oxygen(),
                      "motion": motion(resolved),
                      "metrics": metrics(resolved),
                      "raw": resolved}, indent=2, default=str))

import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets

// ONE running-program cell: app icon, focus treatment, click-to-focus /
// click-to-unroll / click-to-minimize, right-click menu, hover tooltip.
//
// Extracted from Taskbar.qml so the same cell can be laid out two ways without
// the behaviour existing twice: Taskbar.qml stacks these in a Column down the
// classic bar, and DockHeader.qml flows them across the dock panel's top,
// wrapping to a second row as they overflow.
Rectangle {
    id: cell
    required property var modelData

    readonly property bool focusedWin: modelData.activated

    // ---- what the cell says about its window ------------------------------
    // Four states, one ramp from the accent down to the same dim the cells have
    // always used when idle:
    //
    //   focused, on screen   full accent
    //   unfocused, on screen accent, a third of the way to dim
    //   rolled up            accent, three quarters of the way to dim
    //   minimized            dim
    //
    // Roll-up and minimize outrank focus: a rolled-up window can still hold the
    // keyboard, and drawing it as if it were on screen is the one thing this is
    // meant to fix. The state itself comes from WinState (the compositor knows;
    // the Wayland toplevel list does not).
    readonly property string winState: WinState.stateOf(modelData.appId, modelData.title)
    readonly property bool offScreen: winState !== ""
    function _mix(a, b, t) {
        return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t,
                       a.b + (b.b - a.b) * t, 1);
    }
    readonly property color stateColor:
          winState === "minimized" ? Theme.dim
        : winState === "rolled"    ? _mix(Theme.accent, Theme.dim, 0.75)
        : focusedWin               ? Theme.accent
                                   : _mix(Theme.accent, Theme.dim, 0.35)
    // DesktopEntries scans lazily/asynchronously on first access, so at panel
    // startup (windows already open) heuristicLookup can return null before the
    // scan populates. A plain function-call binding would latch that null
    // forever (heuristicLookup registers no dependency on the model), leaving
    // apps whose window-class != icon-name stuck on the generic fallback. Touch
    // .applications.values so this binding re-runs once the scan finishes and
    // the real entry appears.
    readonly property var appEntry: {
        DesktopEntries.applications.values;
        if (!modelData.appId)
            return null;
        const byClass = DesktopEntries.heuristicLookup(modelData.appId);
        // `org.quickshell` is Quickshell's OWN entry, not one of his programs,
        // and every Quickshell toplevel reports it: the Settings window and each
        // file-browser window are the same class, because Quickshell has no
        // per-window app id (and `qs` has no flag for one — checked). So for
        // that one class the title is the only handle that distinguishes them.
        // "settings" resolves to settings.desktop; a browser's title is a path
        // and resolves to nothing, which correctly leaves it on the Quickshell
        // icon rather than borrowing another program's seal.
        if (byClass && byClass.id === "org.quickshell" && modelData.title) {
            const byTitle = DesktopEntries.heuristicLookup(modelData.title);
            if (byTitle)
                return byTitle;
        }
        return byClass;
    }
    readonly property string iconName: appEntry && appEntry.icon
        ? appEntry.icon : (modelData.appId || "")
    // Knocked back off-screen: the icon is most of the cell's ink and a border
    // alone is easy to miss on a busy row.
    readonly property real iconDim: cell.winState === "minimized" ? 0.45
                                  : cell.winState === "rolled" ? 0.7 : 1

    // A window on an output the user cannot see is not one of HIS windows, and
    // the taskbar is the one place the sandbox's promise leaked: `tools/
    // sandbox.sh` keeps an agent's test windows off his screen, but the Wayland
    // toplevel list this cell is built from carries no monitor, so they turned
    // up in his bar anyway. WinState joins the monitor back on (see its OUTPUTS
    // block). Both hosts of this cell are Positioners — Taskbar's Column and
    // DockHeader's Flow — so an invisible cell takes no slot and leaves no gap.
    visible: !WinState.offOutput(modelData.appId, modelData.title)

    width: Theme.wsCell
    height: Theme.wsCell
    radius: 0
    // The filled background stays the FOCUS marker alone — it is the one thing
    // you look for to answer "where am I typing", and folding roll/minimize into
    // it would cost that reading. Those speak through the border colour instead.
    color: focusedWin && !cell.offScreen ? Theme.bgAlt : "transparent"
    border.width: focusedWin ? 2 : 1
    border.color: cell.stateColor

    // The icon is never drawn straight (AppIcon tints it to the state colour,
    // exactly for a seal, luminance-scaled for a foreign icon whose light/dark
    // detail is the drawing): breeze-dark ships no
    // dark VARIANT for its colourful app/mimetype icons (breeze-dark's
    // system-file-manager, text-x-generic … are
    // byte-identical to breeze's), so a raw icon renders in its light-theme
    // colours and reads as "stuck on light mode" on this dark bar. Tinting every
    // one to the cell's state colour is docs/DESIGN.md §3.3's own rule — "the
    // program icons should actually show the states of every window … full accent
    // colour for unrolled and focused" — the same accent ladder the border and
    // the fallback letter already ride, and the same move the tray makes with its
    // own tint. It also subsumes goetia's currentColor sigil, which used to be the
    // only icon tinted here.
    AppIcon {
        anchors.centerIn: parent
        width: Theme.wsCell - 12
        height: Theme.wsCell - 12
        visible: cell.iconName !== ""
        iconName: cell.iconName
        color: cell.stateColor
        dim: cell.iconDim
    }
    // fallback: first letter of the app id in the pixel font
    PixelText {
        anchors.centerIn: parent
        visible: cell.iconName === ""
        text: Glyphs.px((cell.modelData.appId || cell.modelData.title || "?").charAt(0))
        color: cell.stateColor
    }

    MouseArea {
        id: cellMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        // Left click, in the order the cases are tested:
        //
        //   ROLLED UP    un-shade it. NOT activate(): a rolled-up window is
        //                setHidden(true), so focusing it gives the keyboard to
        //                something with nothing on screen — and because a rolled
        //                window can still be `activated`, the old code read it as
        //                "the active one" and MINIMIZED it instead. This case has
        //                to be tested before the activated one for that reason.
        //   MINIMIZED    activate() — that is what slides it back in.
        //   focused      minimize (hyprvtb parks it off-screen), gated on
        //                taskbarClickMinimizes; a no-op when that is off.
        //   anything else focus it.
        //
        // Un-shading also FOCUSES, because the plugin's roll-out does
        // (Hl::focusWindow at the end of the animation) — the same thing the
        // titlebar's own >> button does. The taskbar must not disagree with the
        // titlebar about what un-rolling means.
        //
        // The plugin has no dispatcher (see ../AGENTS.md): actions are Lua
        // functions reached through `hyprctl eval`, and `rollup` is the only one
        // that takes a target — everything else acts on the ACTIVE window, which
        // is never the window whose cell was clicked. The address comes from the
        // same `hyprctl clients` poll that decided the window was rolled, so it
        // is present whenever this branch is taken; the guard is for the poll
        // landing between the two reads.
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton) {
                cellMenu.open();
                return;
            }
            if (cell.winState === "rolled") {
                const addr = WinState.addrOf(cell.modelData.appId, cell.modelData.title);
                if (addr)
                    Quickshell.execDetached(["hyprctl", "eval",
                        "hl.plugin.hyprvtb.rollup(\"" + addr + "\")"]);
                return;
            }
            if (cell.modelData.activated && cell.winState === "") {
                if (SettingsStore.d.taskbarClickMinimizes)
                    Quickshell.execDetached(["hyprctl", "eval", "hl.plugin.hyprvtb.minimize_active()"]);
            } else {
                cell.modelData.activate();
            }
        }
    }

    Tooltip {
        target: cell
        show: cellMouse.containsMouse && !cellMenu.visible
        // The state is spelled out here as well as coloured: the ramp says which
        // of the four a cell is in only if you can see two of them at once.
        // Glyphs.px on the DISPLAYED title only. The raw title is the join key
        // into WinState (stateOf/addrOf above), and the address it returns is
        // what the click dispatches on — map that and the cell would look up a
        // window that does not exist and silently stop rolling up.
        text: Glyphs.px(cell.modelData.title || cell.modelData.appId || "?")
              + (cell.winState === "" ? "" : "\n(" + cell.winState + ")")
    }

    TaskMenu {
        id: cellMenu
        target: cell
        toplevel: cell.modelData
    }
}

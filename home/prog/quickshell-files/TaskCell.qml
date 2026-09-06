import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets

// Shared task cell for the classic taskbar and dock header: icon, state,
// focus/unroll/minimize actions, context menu, and tooltip.
Rectangle {
    id: cell
    required property var modelData

    readonly property bool focusedWin: modelData.activated

    // State colors distinguish focused, ordinary, rolled, and minimized
    // windows. Roll/minimize outrank focus because WinState gets those states
    // from the compositor rather than the foreign-toplevel list.
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
    // Touch the values model so this binding re-evaluates after the lazy desktop
    // entry scan completes.
    readonly property var appEntry: {
        DesktopEntries.applications.values;
        if (!modelData.appId)
            return null;
        const byClass = DesktopEntries.heuristicLookup(modelData.appId);
        // Quickshell's shared app id covers settings and file-browser windows;
        // use the title when it resolves to a more specific desktop entry.
        if (byClass && byClass.id === "org.quickshell" && modelData.title) {
            const byTitle = DesktopEntries.heuristicLookup(modelData.title);
            if (byTitle)
                return byTitle;
        }
        return byClass;
    }
    readonly property string iconName: appEntry && appEntry.icon
        ? appEntry.icon : (modelData.appId || "")
    // Reduce icon ink for compositor-managed rolled/minimized states.
    readonly property real iconDim: cell.winState === "minimized" ? 0.45
                                  : cell.winState === "rolled" ? 0.7 : 1

    // Exclude windows on virtual outputs; Positioners then leave no slot.
    visible: !WinState.offOutput(modelData.appId, modelData.title)

    width: Theme.wsCell
    height: Theme.wsCell
    radius: Theme.windowRounding
    // The fill remains the focus marker; roll/minimize are communicated by the
    // border color.
    color: focusedWin && !cell.offScreen ? Theme.bgAlt : "transparent"
    border.width: focusedWin ? Theme.ctrlBorder + 1 : Theme.ctrlBorder
    border.color: cell.stateColor

    // AppIcon applies the state tint to both bespoke seals and foreign icons;
    // this keeps icon and border state consistent (docs/DESIGN.md §3.3).
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

import QtQuick
import Quickshell
import Quickshell.Widgets

// ONE running-program cell: app icon, focus treatment, click-to-focus /
// click-to-minimize, right-click menu, hover tooltip.
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
        return modelData.appId
            ? DesktopEntries.heuristicLookup(modelData.appId) : null;
    }
    readonly property string iconName: appEntry && appEntry.icon
        ? appEntry.icon : (modelData.appId || "")

    width: Theme.wsCell
    height: Theme.wsCell
    radius: 0
    // The filled background stays the FOCUS marker alone — it is the one thing
    // you look for to answer "where am I typing", and folding roll/minimize into
    // it would cost that reading. Those speak through the border colour instead.
    color: focusedWin && !cell.offScreen ? Theme.bgAlt : "transparent"
    border.width: focusedWin ? 2 : 1
    border.color: cell.stateColor

    IconImage {
        anchors.centerIn: parent
        visible: cell.iconName !== ""
        implicitSize: Theme.wsCell - 12
        source: Quickshell.iconPath(cell.iconName, "application-x-executable")
        // A window that isn't on screen has its icon knocked back to match,
        // since the icon is most of the cell's ink and a border alone is easy to
        // miss on a busy row.
        opacity: cell.winState === "minimized" ? 0.45
               : cell.winState === "rolled" ? 0.7 : 1
    }
    // fallback: first letter of the app id in the pixel font
    PixelText {
        anchors.centerIn: parent
        visible: cell.iconName === ""
        text: (cell.modelData.appId || cell.modelData.title || "?").charAt(0)
        color: cell.stateColor
    }

    MouseArea {
        id: cellMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        // Left-click the ACTIVE program's icon to minimize it (hyprvtb slides it
        // off-screen); left-click any other icon to focus it, which also slides
        // a minimized window back in. The minimize-on-click is gated on
        // taskbarClickMinimizes — when off, clicking the focused icon is a
        // no-op. Right-click opens the Close / Force Quit menu.
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton) {
                cellMenu.open();
                return;
            }
            if (cell.modelData.activated) {
                if (SettingsStore.d.taskbarClickMinimizes)
                    Quickshell.execDetached(["hyprctl", "eval", "hl.plugin.hyprvtb.minimize_active()"]);
            } else {
                cell.modelData.activate();
            }
        }
    }

    Tooltip {
        target: cell
        visible: cellMouse.containsMouse && !cellMenu.visible
        // The state is spelled out here as well as coloured: the ramp says which
        // of the four a cell is in only if you can see two of them at once.
        text: (cell.modelData.title || cell.modelData.appId || "?")
              + (cell.winState === "" ? "" : "\n(" + cell.winState + ")")
    }

    TaskMenu {
        id: cellMenu
        target: cell
        toplevel: cell.modelData
    }
}

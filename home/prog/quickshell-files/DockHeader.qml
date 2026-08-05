import QtQuick
import Quickshell
import Quickshell.Wayland

// The dock panel's top strip: the running-program icons, filling it from the
// left and wrapping onto further rows as they overflow.
//
// This is the horizontal counterpart of the classic bar's Taskbar column. The
// icons are TaskCell.qml, the same delegate Taskbar.qml uses, so focus
// treatment / click-to-minimize / the right-click menu behave identically in
// both modes.
//
// There is no runner button here (nor in the classic bar): the runner is the
// shortcut notch slid out — Launcher.qml — and it opens on mainMod+Super.
//
// The Flow is given an explicit width because that is what it wraps against —
// an unconstrained Flow lays everything out on one infinitely-wide row and
// never wraps at all.
//
// Uptime lives in the top-right corner, and the Flow's right edge stops short
// of it — NOT overlapped and left to luck. The icons wrap as they fill, so with
// enough windows open they would otherwise reach the corner and draw straight
// over the text.
Item {
    id: root

    function fmtUptime(s) {
        if (!s || s <= 0) return "--";
        const d = Math.floor(s / 86400);
        const h = Math.floor((s % 86400) / 3600);
        const m = Math.floor((s % 3600) / 60);
        if (d > 0) return d + "d" + h + "h";
        if (h > 0) return h + "h" + m + "m";
        return m + "m";
    }

    implicitHeight: Math.max(Theme.wsCell, icons.implicitHeight)

    PixelText {
        id: uptime
        anchors.right: parent.right
        // Centred on the FIRST ROW of icons, not on the header as a whole: the
        // Flow wraps onto further rows as windows accumulate, so centring on the
        // box would walk this text down the panel every time one opened. One
        // cell tall is the row height, whether there is one row or four.
        y: Math.round((Theme.wsCell - height) / 2)
        text: "up " + root.fmtUptime(SysInfo.uptimeSec)
        color: Theme.textDim
    }

    Flow {
        id: icons
        anchors {
            left: parent.left
            right: uptime.left
            rightMargin: Theme.gap
            top: parent.top
        }
        spacing: Theme.gap

        Repeater {
            model: ToplevelManager.toplevels
            delegate: TaskCell {}
        }
    }
}

import QtQuick
import Quickshell
import Quickshell.Wayland

// The dock panel's top strip: the runner button pinned at the LEFT, with the
// running-program icons filling the space to its right and wrapping onto
// further rows as they overflow.
//
// This is the horizontal counterpart of the classic bar's vertical
// launcher-over-Taskbar column. The icons are TaskCell.qml, the same delegate
// Taskbar.qml uses, so focus treatment / click-to-minimize / the right-click
// menu behave identically in both modes.
//
// Laid out as runner + Flow rather than a single Flow containing the runner:
// the runner must stay at the top-left corner no matter how many windows are
// open, whereas a Flow would let it be pushed around as cells re-wrap. The Flow
// is given an explicit width (whatever is left beside the runner) because that
// is what it wraps against — an unconstrained Flow lays everything out on one
// infinitely-wide row and never wraps at all.
//
// Uptime lives in the top-right corner, and the Flow's right edge stops short
// of it — NOT overlapped and left to luck. The icons wrap as they fill, so with
// enough windows open they would otherwise reach the corner and draw straight
// over the text.
Item {
    id: root

    property bool runnerActive: false
    signal runnerToggled()

    function fmtUptime(s) {
        if (!s || s <= 0) return "--";
        const d = Math.floor(s / 86400);
        const h = Math.floor((s % 86400) / 3600);
        const m = Math.floor((s % 3600) / 60);
        if (d > 0) return d + "d" + h + "h";
        if (h > 0) return h + "h" + m + "m";
        return m + "m";
    }

    implicitHeight: Math.max(runner.height, icons.implicitHeight)

    RunnerButton {
        id: runner
        anchors { left: parent.left; top: parent.top }
        active: root.runnerActive
        onToggled: root.runnerToggled()
    }

    PixelText {
        id: uptime
        anchors { right: parent.right; top: parent.top }
        text: "up " + root.fmtUptime(SysInfo.uptimeSec)
        color: Theme.textDim
    }

    Flow {
        id: icons
        anchors {
            left: runner.right
            leftMargin: Theme.gap
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

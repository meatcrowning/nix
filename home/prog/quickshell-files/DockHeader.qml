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
Item {
    id: root

    property bool runnerActive: false
    signal runnerToggled()

    implicitHeight: Math.max(runner.height, icons.implicitHeight)

    RunnerButton {
        id: runner
        anchors { left: parent.left; top: parent.top }
        active: root.runnerActive
        onToggled: root.runnerToggled()
    }

    Flow {
        id: icons
        anchors {
            left: runner.right
            leftMargin: Theme.gap
            right: parent.right
            top: parent.top
        }
        spacing: Theme.gap

        Repeater {
            model: ToplevelManager.toplevels
            delegate: TaskCell {}
        }
    }
}

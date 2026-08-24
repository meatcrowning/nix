import QtQuick
import "../../qmlcommon"

// ONE BACKGROUND JOB, in the Hyprland session's own idiom: a `bgAlt` row with a
// 1px border and the desktop's radius (docs/DESIGN.md §4, §9.1), a state dot on
// the left, the label, a fixed-width clock slot on the right, and the verbs
// after it.
//
// The row says WHAT IS HAPPENING before it says anything else — a job runs for
// an hour and the thing he needs at a glance is whether it is still alive
// (§10). The clock slot is reserved whatever the state, so nothing shifts when
// a job finishes (§5.4), and the log stays folded until asked for (§9.1 — a
// subordinated disclosure, not a wall of output).
//
// A component rather than markup in Root.qml because it has a Plasma twin
// (`+plasma/JobRow.qml`, drawn by the KStyle). API: `job` (one row of
// `Jobs.rows`), `expanded`, and the three signals.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property var job: ({})
    property bool expanded: false

    signal toggled()
    signal stopped()
    signal cleared()

    // The pulse stops with the job, and the dot goes back to solid — the
    // animation leaves opacity wherever it was when it stopped.
    onRunningChanged: if (!running) dot.opacity = 1.0

    readonly property string state_: job && job.state ? job.state : "unknown"
    readonly property bool running: state_ === "running" || state_ === "starting"
    readonly property color stateColor:
        state_ === "failed" || state_ === "timeout" ? Theme.crit
        : state_ === "stopped" ? Theme.warn
        : running ? Theme.accent : Theme.textDim

    // The elapsed clock: seconds under a minute, m:ss under an hour, h:mm over.
    function clock(s) {
        var n = Math.max(0, Math.round(s || 0));
        if (n < 60) return n + "s";
        if (n < 3600) return Math.floor(n / 60) + "m "
                             + ("0" + (n % 60)).slice(-2) + "s";
        return Math.floor(n / 3600) + "h "
               + ("0" + Math.floor((n % 3600) / 60)).slice(-2) + "m";
    }

    // What the state says in words — the exit code belongs to the failure, not
    // to a separate column nobody reads (§3.5, say it twice: colour and text).
    function stateText() {
        if (running) return "running";
        if (state_ === "done") return "done";
        if (state_ === "failed")
            return "failed" + (job && job.exit !== undefined && job.exit !== null
                               ? " " + job.exit : "");
        return state_;
    }

    implicitHeight: head.height + (expanded ? logBox.height + 6 : 0) + 12
    height: implicitHeight
    radius: Theme.rounding
    color: Theme.bgAlt
    border.width: Theme.ctrlBorder
    border.color: Theme.border

    Motion { id: motion }

    Behavior on implicitHeight {
        NumberAnimation { duration: motion.ms(motion.slideMs)
                          easing.type: motion.slideEasing }
    }

    Item {
        id: head
        anchors { top: parent.top; left: parent.left; right: parent.right
                  margins: 6; topMargin: 6 }
        height: Math.max(labelText.implicitHeight, 14)

        // The state dot. It PULSES while the job runs and is still while it is
        // not — the one moving thing in the row, and it moves for the one
        // reason that matters (§6.9, an indicator driven by what it indicates).
        Rectangle {
            id: dot
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            width: 6; height: 6; radius: 3
            color: root.stateColor
            SequentialAnimation on opacity {
                running: root.running
                loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 700
                                  easing.type: Easing.InOutQuad }
                NumberAnimation { to: 1.0; duration: 700
                                  easing.type: Easing.InOutQuad }
            }
        }

        PixelText {
            id: labelText
            anchors { left: dot.right; leftMargin: 8
                      right: stateText.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            text: root.job && root.job.label ? root.job.label : "job"
            elide: Text.ElideRight
            color: Theme.text
        }

        PixelText {
            id: stateText
            anchors { right: clockText.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            text: root.stateText()
            color: root.stateColor
        }

        PixelText {
            id: clockText
            anchors { right: verbs.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            // A RESERVED slot: the widest clock this can hold, so a job
            // finishing does not shuffle the row (§5.4).
            width: Math.max(implicitWidth, 46)
            horizontalAlignment: Text.AlignRight
            text: root.clock(root.job ? root.job.seconds : 0)
            color: Theme.textDim
        }

        Row {
            id: verbs
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            spacing: 6

            JobVerb {
                label: root.expanded ? "hide" : "log"
                onClicked: root.toggled()
            }
            JobVerb {
                label: "stop"
                visible: root.running
                onClicked: root.stopped()
            }
            JobVerb {
                label: "clear"
                visible: !root.running
                onClicked: root.cleared()
            }
        }
    }

    // The log tail, folded away until he asks for it. `bg` under the row's
    // `bgAlt` so the output reads as a well inside the row rather than a second
    // row (§3.2, fills dim).
    Rectangle {
        id: logBox
        visible: root.expanded
        anchors { top: head.bottom; topMargin: 6
                  left: parent.left; right: parent.right
                  leftMargin: 6; rightMargin: 6 }
        height: visible ? Math.min(logText.implicitHeight + 10, 150) : 0
        radius: Theme.rounding
        color: Theme.bg
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        clip: true

        Flickable {
            anchors { fill: parent; margins: 5 }
            contentWidth: width
            contentHeight: logText.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            // A running job writes to the bottom, so that is where it opens.
            onContentHeightChanged: contentY = Math.max(0, contentHeight - height)

            SelectableText {
                id: logText
                width: parent.width
                text: root.job && root.job.tail && root.job.tail.length
                      ? root.job.tail.join("\n") : "no output yet"
                color: Theme.textDim
                wrapMode: Text.NoWrap
            }
        }
    }
}

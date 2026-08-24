import QtQuick
import QtQuick.Controls as QQC
import "../../../qmlcommon"

// ONE BACKGROUND JOB in a Plasma session — an Oxygen row, not a pixel-era one:
// the KStyle's own `Frame` around it, `QQC.Label`s for every word, real buttons
// for the verbs, and the log in the style's `ScrollView` + read-only `TextArea`
// (the same recessed well Oxygen draws for the compose box, which is what
// `+plasma/PromptBox.qml` exists to get right).
//
// The layout is the Hyprland row's, deliberately: state dot, label, state,
// a reserved clock slot, then the verbs (docs/DESIGN.md §5.4, §9.1). What
// changes between the two faces is the HAND that draws it, never where a thing
// is or what it says.
//
// Same API as ../JobRow.qml — `job`, `expanded`, `toggled/stopped/cleared` — so
// JobsTray is untouched.
Item {
    id: root
    property string face: "plasma"
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

    function clock(s) {
        var n = Math.max(0, Math.round(s || 0));
        if (n < 60) return n + "s";
        if (n < 3600) return Math.floor(n / 60) + "m "
                             + ("0" + (n % 60)).slice(-2) + "s";
        return Math.floor(n / 3600) + "h "
               + ("0" + Math.floor((n % 3600) / 60)).slice(-2) + "m";
    }

    function stateText() {
        if (running) return "running";
        if (state_ === "done") return "done";
        if (state_ === "failed")
            return "failed" + (job && job.exit !== undefined && job.exit !== null
                               ? " " + job.exit : "");
        return state_;
    }

    implicitHeight: frame.implicitHeight
    height: implicitHeight

    Motion { id: motion }

    Behavior on implicitHeight {
        NumberAnimation { duration: motion.ms(motion.slideMs)
                          easing.type: motion.slideEasing }
    }

    QQC.Frame {
        id: frame
        anchors.fill: parent
        implicitHeight: head.height + (root.expanded ? logWell.height + 8 : 0)
                        + topPadding + bottomPadding

        Item {
            id: head
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: Math.max(labelText.implicitHeight, verbs.implicitHeight)

            Rectangle {
                id: dot
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                width: 8; height: 8; radius: 4
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

            QQC.Label {
                id: labelText
                anchors { left: dot.right; leftMargin: 8
                          right: stateLabel.left; rightMargin: 8
                          verticalCenter: parent.verticalCenter }
                text: root.job && root.job.label ? root.job.label : "job"
                elide: Text.ElideRight
            }

            QQC.Label {
                id: stateLabel
                anchors { right: clockLabel.left; rightMargin: 8
                          verticalCenter: parent.verticalCenter }
                text: root.stateText()
                color: root.stateColor
            }

            QQC.Label {
                id: clockLabel
                anchors { right: verbs.left; rightMargin: 8
                          verticalCenter: parent.verticalCenter }
                width: Math.max(implicitWidth, 52)
                horizontalAlignment: Text.AlignRight
                text: root.clock(root.job ? root.job.seconds : 0)
                opacity: 0.75
            }

            Row {
                id: verbs
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: 4

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

        // The output, in the style's own recessed well — a ScrollView holding a
        // read-only TextArea, which is how Oxygen draws a text view and what
        // keeps this from being our rectangle in a KDE window.
        QQC.ScrollView {
            id: logWell
            visible: root.expanded
            anchors { top: head.bottom; topMargin: 8
                      left: parent.left; right: parent.right }
            height: visible ? 150 : 0
            clip: true

            QQC.TextArea {
                id: logText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.NoWrap
                font.family: "monospace"
                text: root.job && root.job.tail && root.job.tail.length
                      ? root.job.tail.join("\n") : "no output yet"
                // A running job writes to the bottom, so that is where it opens.
                onTextChanged: cursorPosition = length
            }
        }
    }
}

import QtQuick
import "../../qmlcommon"

// The systheme-creation toast: the album-cover -> desktop-theme run reports
// itself HERE, as a card with a progress bar, not as in-window status text.
// Driven by Library.systhemeProgress ({active, fraction, label, outcome}) —
// systheme.py's own phase output, streamed live and mapped to a fraction in
// main.py. docs/DESIGN.md §8.1 is the card + progress-bar vocabulary; §7.2 is
// why the final result (applied / not applied / failed) always shows before
// the card leaves — a long op that can fail must never end in silence.
Item {
    id: root
    anchors.fill: parent
    z: 80
    // Ignore the pointer everywhere except the card itself (below).
    visible: shown

    property color fgText: Theme.text
    property color fgDim: Theme.textDim

    property bool active: false
    property real fraction: 0
    property string label: ""
    property string outcome: ""   // "" running, else ok | partial | fail
    property bool shown: false

    Motion { id: motion }

    // Card tint follows the urgency ladder (§8.1): a failure is critical, a
    // "created but not applied" is the info tone, everything else the accent.
    readonly property color tint: outcome === "fail" ? Theme.crit
                                : outcome === "partial" ? Theme.info
                                : Theme.accent

    Connections {
        target: Library
        function onSysthemeProgress(p) {
            root.active = !!p.active;
            root.fraction = p.fraction !== undefined ? p.fraction : root.fraction;
            root.label = p.label || "";
            root.outcome = p.outcome || "";
            root.shown = true;
            if (!root.active)
                linger.restart();   // let the result read, then roll away
            else
                linger.stop();
        }
    }

    // The result is READABLE for this long after the run ends, then the card
    // rolls away (painter's toast pause, §8.1 — a fixed dwell, not motion.ms(),
    // so reduceMotion doesn't blink it out of existence).
    Timer {
        id: linger
        interval: 3200
        onTriggered: root.shown = false
    }

    // ---- the card ----
    Rectangle {
        id: card
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Theme.gap
        width: Math.min(300, parent.width - 2 * Theme.gap)
        implicitHeight: col.implicitHeight + 20
        height: implicitHeight
        color: Theme.bgAlt
        border.width: 2
        border.color: root.tint
        radius: 0

        // Entrance/exit: roll in from below and fade, reversed on the way out
        // (§8.1 — "toasts roll up like how they roll out"), on the desktop clock.
        transform: Translate {
            y: root.shown ? 0 : 24
            Behavior on y { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }
        }
        opacity: root.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }
        Behavior on implicitHeight { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }

        // The 3px left urgency strip (§8.1).
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 3
            color: root.tint
        }

        Column {
            id: col
            anchors.fill: parent
            anchors.leftMargin: 10 + 3
            anchors.rightMargin: 10
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            spacing: 6

            // Header row: who it is from + the percent, in the tint (§8.1).
            Row {
                width: parent.width
                PixelText {
                    text: "systheme"
                    color: root.tint
                    width: parent.width - pct.width
                    elide: Text.ElideRight
                }
                PixelText {
                    id: pct
                    text: root.outcome === "" ? Math.round(root.fraction * 100) + "%" : ""
                    color: root.tint
                    horizontalAlignment: Text.AlignRight
                }
            }

            // The phase / result line.
            PixelText {
                width: parent.width
                text: root.label
                color: root.fgText
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }

            // The progress bar (§8.1: Theme.bgAlt box + 1px Theme.border, fill
            // inset margins:1, width = round((parent-2)*frac)). Only while the
            // run is live — a finished result is the label + the tint, no bar.
            Rectangle {
                width: parent.width
                height: 8
                color: Theme.bgAlt
                border.width: 1
                border.color: Theme.border
                visible: root.outcome === ""
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.margins: 1
                    width: Math.max(0, Math.round((parent.width - 2) * root.fraction))
                    color: root.tint
                    // The desktop's motion, not a literal of its own
                    // (qmlcommon/Motion.qml): this was a hardcoded 120ms, so
                    // reduceMotion and the animSpeed slider did not reach it —
                    // and in a Plasma session with Oxygen's animations switched
                    // off it was the one thing in the window still travelling.
                    Behavior on width { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }
                }
            }
        }

        // Click to dismiss (only meaningful once the result is up; a running
        // toast dismissed does not stop the process, so ignore clicks then —
        // §7.2, never advertise an action that does nothing).
        MouseArea {
            anchors.fill: parent
            enabled: root.outcome !== ""
            onClicked: root.shown = false
        }
    }
}

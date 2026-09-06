import QtQuick
import QtQuick.Controls as QQC

// The compose box in a Plasma session: the KStyle's own sunken Frame around a
// real TextArea, with a real Button beside it — Oxygen's focus frame, its
// scrollbar and its button relief, not an imitation of them (apps/AGENTS.md →
// kdeshell; the window's chrome is real widgets, so the one control the content
// still owns had better be drawn by the same style).
//
// Same API as ../PromptBox.qml — `text`, `busy`, `armed`, `clear()`, the three
// signals — so Root.qml is untouched; the file selector picks between the two.
Item {
    id: root
    property string face: "plasma"   // how a harness proves the swap happened
    property alias text: area.text
    property bool busy: false
    property bool armed: false
    property bool canContinue: false   // see ../PromptBox.qml
    signal submitted()
    signal stopped()
    signal continued()
    signal escaped()

    function clear() { area.clear(); }

    // HUG THE TEXT. A floor of 56 left 16px of nothing under a one-line
    // prompt [his, 2026-08-22]; the Frame's own padding is the only spare room
    // there should be, and `implicitHeight` on a TextArea is already one line
    // when it is empty. It grows with what he types, to a cap.
    //
    // The floor is the SEND BUTTON, measured, not a round number: 34 was two
    // pixels more than the button needs and four more than the input does, and
    // all six of them landed under the text, because the input is anchored to
    // the top and slack falls out of the bottom [his, 2026-08-23: "extra empty
    // space under the text line and the bottom edge"]. Whatever slack the
    // button's height still imposes is now SPLIT — the input is centred on it —
    // so the box reads as padding rather than as a gap.
    height: Math.min(180, Math.max(area.implicitHeight + 8,
                                   sendBtn.implicitHeight))

    // Draw the compose surface with the SAME native Button primitive as Send.
    // It is only a background (disabled, empty, and below the editor), so it
    // cannot claim a click; full opacity keeps its raised Oxygen gradient.
    QQC.Button {
        id: frame
        anchors { left: parent.left; right: sendBtn.left; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        height: Math.min(root.height, area.implicitHeight + 8)
        enabled: false
        text: ""
        background.opacity: 1.0
        contentItem: Item { }
    }

    // The editor is transparent so the Button beneath is the only surface. Its
    // own ScrollView/TextArea backgrounds are Oxygen's recessed View colour.
    QQC.ScrollView {
        anchors { fill: frame; margins: 4 }
        clip: true
        background: null

        QQC.TextArea {
            id: area
            wrapMode: QQC.TextArea.Wrap
            background: null
            placeholderText: "ask the model…  (Enter to send, Shift+Enter for a newline)"
            persistentSelection: true
            focus: true

            Keys.onPressed: function (e) {
                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                    && !(e.modifiers & Qt.ShiftModifier)) {
                    root.submitted();
                    e.accepted = true;
                } else if (e.key === Qt.Key_Escape) {
                    root.escaped();
                    e.accepted = true;
                }
            }
        }
    }

    QQC.Button {
        id: sendBtn
        objectName: "sendLabel"        // same handle as ../PromptBox.qml's
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        readonly property bool sends: root.armed || !root.canContinue
        text: root.busy ? "Stop" : (sends ? "Send" : "Continue")
        icon.name: root.busy ? "process-stop"
                   : (sends ? "document-send" : "media-playback-start")
        // §10.2: a button with nothing to act on is disabled, never silently
        // inert. Stopping is always available while a reply is streaming.
        enabled: root.busy || root.armed || root.canContinue
        onClicked: root.busy ? root.stopped()
                   : (sends ? root.submitted() : root.continued())
    }
}

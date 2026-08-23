import QtQuick
import QtQuick.Controls

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
    signal submitted()
    signal stopped()
    signal escaped()

    function clear() { area.clear(); }

    // HUG THE TEXT. A floor of 56 left 16px of nothing under a one-line
    // prompt [his, 2026-08-22]; the Frame's own padding is the only spare room
    // there should be, and `implicitHeight` on a TextArea is already one line
    // when it is empty. It grows with what he types, to a cap.
    height: Math.min(180, area.implicitHeight + frame.topPadding + frame.bottomPadding)

    Frame {
        id: frame
        anchors { top: parent.top; bottom: parent.bottom
                  left: parent.left; right: sendBtn.left; rightMargin: 6 }

        ScrollView {
            anchors.fill: parent
            clip: true

            TextArea {
                id: area
                wrapMode: TextArea.Wrap
                // The frame is the Frame's; a second one inside it is the
                // "one odd window" seam this face exists to close.
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
    }

    Button {
        id: sendBtn
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        text: root.busy ? "Stop" : "Send"
        icon.name: root.busy ? "process-stop" : "document-send"
        // §10.2: a button with nothing to act on is disabled, never silently
        // inert. Stopping is always available while a reply is streaming.
        enabled: root.busy || root.armed
        onClicked: root.busy ? root.stopped() : root.submitted()
    }
}

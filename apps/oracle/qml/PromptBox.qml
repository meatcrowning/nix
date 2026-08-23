import QtQuick
import "../../qmlcommon"

// The compose box: a framed multi-line input with the send/stop button at its
// right-hand end. Enter sends, Shift+Enter keeps typing a paragraph, Escape
// hands focus back to the reply view (the desktop-wide Escape-to-dismiss).
//
// Same API as `+plasma/PromptBox.qml`, which is what the file selector puts
// here in a Plasma session: `text`, `busy`, `armed`, `clear()`, and the three
// signals. The parent never reaches inside either one.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property alias text: input.text
    property bool busy: false        // a reply is streaming: the button stops it
    property bool armed: false       // there is something to send
    signal submitted()
    signal stopped()
    signal escaped()

    function clear() { input.clear(); }

    height: Math.max(48, Math.min(160, input.implicitHeight + 16))
    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: input.activeFocus ? Theme.accent : Theme.border

    KineticFlickable {
        id: inputFlick
        anchors { top: parent.top; bottom: parent.bottom
                  left: parent.left; right: sendBtn.left
                  margins: 8 }
        contentWidth: width
        contentHeight: input.implicitHeight
        clip: true

        TextEdit {
            id: input
            width: inputFlick.width
            // The pair, not one half of it: the whole QFont carries NoAntialias
            // (the only lever that reaches the rasteriser on an editable item —
            // docs/DESIGN.md §2.2), and NativeRendering is what stops Qt drawing
            // it through the distance-field renderer. Shipped with the font
            // alone, which is why the box he types into came out aliased and
            // blurry while every label around it was crisp. Same pairing as
            // editor's CodeView and board's InputBox.
            font: Theme.editorFont
            renderType: Text.NativeRendering
            color: Theme.text
            selectionColor: Theme.accent
            selectedTextColor: Theme.bg
            wrapMode: TextEdit.Wrap
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

            PixelText {
                anchors { left: parent.left; verticalCenter: parent.top
                          verticalCenterOffset: parent.implicitHeight / 2 }
                visible: input.text === "" && !input.activeFocus
                text: "ask the model…  (Enter to send, Shift+Enter for a newline)"
                color: Theme.textDim
            }
        }
    }

    Rectangle {
        id: sendBtn
        anchors { right: parent.right; rightMargin: 8
                  verticalCenter: parent.verticalCenter }
        width: 56
        height: 24
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        color: sendMouse.containsMouse && (root.armed || root.busy)
               ? Theme.highlight : Theme.bg
        PixelText {
            anchors.centerIn: parent
            text: root.busy ? "stop" : "send"
            color: root.busy ? Theme.warn
                   : (root.armed ? Theme.accent : Theme.dim)
        }
        MouseArea {
            id: sendMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: (root.armed || root.busy)
                         ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: root.busy ? root.stopped() : root.submitted()
        }
    }
}

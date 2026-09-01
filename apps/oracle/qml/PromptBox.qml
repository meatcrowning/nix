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
    // Nothing typed, and the last reply can be carried on: the SAME button
    // says `continue` [his, 2026-08-23 — it belongs on the button beside the
    // box, not under the bubble]. One button, one place, three states: stop
    // while a reply streams, send the moment there is something to send, and
    // continue when there is not (docs/DESIGN.md §10.2).
    property bool canContinue: false
    signal submitted()
    signal stopped()
    signal continued()
    signal escaped()

    function clear() { input.clear(); }

    // Which of the three the button is right now.
    readonly property bool acts: root.busy || root.armed || root.canContinue

    // Hug the text: the floor is the send button plus the box's own padding,
    // not a round 48 that left a dead band under a one-line prompt.
    //
    // The button is taller than one line of text, so a floor alone still leaves
    // slack — and anchoring the input to the top dropped ALL of it under the
    // line [his, 2026-08-23: "extra empty space under the text line and the
    // bottom edge"]. The input is centred on the box now, so what is left reads
    // as padding above and below rather than as a gap under the text.
    readonly property int pad: 8
    height: Math.max(sendBtn.height + 2 * pad,
                     Math.min(160, input.implicitHeight + 2 * pad))
    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: input.activeFocus ? Theme.accent : Theme.border

    KineticFlickable {
        id: inputFlick
        anchors { left: parent.left; right: sendBtn.left
                  leftMargin: root.pad; rightMargin: root.pad
                  verticalCenter: parent.verticalCenter }
        height: Math.min(root.height - 2 * root.pad, input.implicitHeight)
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
            font: Theme.editorFontAt(Screen.devicePixelRatio)
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
        // 56 fits `send` and `stop`; `continue` is wider, so the button grows
        // to its own label rather than clipping it.
        width: Math.max(56, sendLabel.implicitWidth + 16)
        height: 24
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        color: sendMouse.containsMouse && root.acts ? Theme.highlight : Theme.bg
        PixelText {
            id: sendLabel
            objectName: "sendLabel"     // what the harness reads the state off
            anchors.centerIn: parent
            text: root.busy ? "stop" : (root.armed || !root.canContinue
                                        ? "send" : "continue")
            color: root.busy ? Theme.warn
                   : (root.acts ? Theme.accent : Theme.dim)
        }
        MouseArea {
            id: sendMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: root.acts ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: root.busy ? root.stopped()
                       : (root.armed || !root.canContinue ? root.submitted()
                                                          : root.continued())
        }
    }
}

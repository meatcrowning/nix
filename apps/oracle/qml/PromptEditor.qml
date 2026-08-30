import QtQuick
import "../../qmlcommon"

// The custom-prompt editor — a floating panel over the conversation with a
// TextEdit for his own base text and Save / Cancel (docs/DESIGN.md §10: Save
// applies it; Cancel discards, nothing changes silently). Selecting "custom…"
// in the base-prompt dropdown, the "edit" button, or Settings ▸ Edit Custom
// Prompt… opens it.
//
// A component rather than a Rectangle in Root.qml because it has a Plasma twin
// (`+plasma/PromptEditor.qml`, real Frame/TextArea/Buttons). API, identical
// either way: `load(text)` fills and shows it, `saved(text)` and `cancelled()`
// report what he chose. The panel does not touch `Ollama` itself — the call
// site owns what saving MEANS, which is what lets the two faces stay pure QML.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    signal saved(string text)
    signal cancelled()

    function load(t) {
        editorArea.text = t;
        root.visible = true;
        editorArea.forceActiveFocus();
    }

    visible: false
    implicitHeight: 220
    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: Theme.accent

    PixelText {
        id: editorHeading
        anchors { top: parent.top; left: parent.left; right: parent.right
                  margins: 10 }
        text: "your custom system prompt"
        color: Theme.textDim
        wrapMode: Text.NoWrap
        elide: Text.ElideRight
    }

    Rectangle {
        anchors { top: editorHeading.bottom; topMargin: 8
                  left: parent.left; right: parent.right
                  bottom: editorButtons.top; bottomMargin: 8
                  leftMargin: 10; rightMargin: 10 }
        color: Theme.bg
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: editorArea.activeFocus ? Theme.accent : Theme.border

        KineticFlickable {
            id: editorFlick
            anchors { fill: parent; margins: 8 }
            contentWidth: width
            contentHeight: editorArea.implicitHeight
            clip: true
            TextEdit {
                id: editorArea
                width: editorFlick.width
                font: Theme.editorFont
            font.letterSpacing: Theme.fontLetterSpacing(Screen.devicePixelRatio)
                renderType: Text.NativeRendering
                color: Theme.text
                selectionColor: Theme.accent
                selectedTextColor: Theme.bg
                wrapMode: TextEdit.Wrap
                persistentSelection: true
                Keys.onPressed: function (e) {
                    if (e.key === Qt.Key_Escape) {
                        root.visible = false;
                        root.cancelled();
                        e.accepted = true;
                    }
                }

                PixelText {
                    anchors { left: parent.left; verticalCenter: parent.top
                              verticalCenterOffset: parent.implicitHeight / 2 }
                    visible: editorArea.text === "" && !editorArea.activeFocus
                    text: "write the base instructions the model gets every turn…"
                    color: Theme.textDim
                }
            }
        }
    }

    Row {
        id: editorButtons
        anchors { bottom: parent.bottom; right: parent.right; margins: 10 }
        spacing: 8

        Rectangle {
            width: 64; height: 24
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            color: cancelMouse.containsMouse ? Theme.highlight : Theme.bg
            PixelText { anchors.centerIn: parent; text: "cancel"; color: Theme.textDim }
            MouseArea {
                id: cancelMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { root.visible = false; root.cancelled(); }
            }
        }
        Rectangle {
            width: 64; height: 24
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            color: saveMouse.containsMouse ? Theme.highlight : Theme.bg
            PixelText { anchors.centerIn: parent; text: "save"; color: Theme.accent }
            MouseArea {
                id: saveMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { root.visible = false; root.saved(editorArea.text); }
            }
        }
    }
}

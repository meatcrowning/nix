import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

Rectangle {
    id: box
    property string placeholder: ""
    property alias text: input.text
    property bool negative: false
    signal edited(string text)

    color: Theme.bg
    border.color: input.activeFocus ? Theme.accent : Theme.border
    border.width: 1
    radius: 1

    KineticFlickable {
        id: flick
        anchors.fill: parent
        anchors.margins: 5
        contentWidth: width
        contentHeight: input.implicitHeight
        clip: true
        ScrollBar.vertical: VScroll {}

        TextEdit {
            id: input
            width: flick.width
            wrapMode: TextEdit.Wrap
            color: box.negative ? Theme.textDim : Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.fontSize
            font.hintingPreference: Font.PreferNoHinting
            renderType: Text.NativeRendering
            // the one multi-line editor in any of these apps, so it needs the
            // pin PixelText carries: FixedHeight at the font cell == kitty's row
            lineHeight: Theme.fontSize
            lineHeightMode: TextEdit.FixedHeight
            selectByMouse: true
            selectionColor: Theme.accent
            selectedTextColor: Theme.bg
            onTextChanged: box.edited(text)
            // Ctrl+Enter belongs to the window, not the editor.
            Keys.onPressed: function (e) {
                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                        && (e.modifiers & Qt.ControlModifier)) {
                    e.accepted = false
                }
            }
        }

        PixelText {
            visible: input.text === ""
            text: box.placeholder
            color: Theme.dim
        }
    }

}

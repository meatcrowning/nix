import QtQuick
import QtQuick.Controls.Basic

// Hover explanation, used wherever a control's reasoning is not obvious from
// its label (why an encoder was chosen, why a LoRA is greyed out).
MouseArea {
    property string text: ""
    hoverEnabled: enabled && text !== ""
    acceptedButtons: Qt.NoButton
    ToolTip.visible: containsMouse && text !== ""
    ToolTip.text: text
    ToolTip.delay: 400
}

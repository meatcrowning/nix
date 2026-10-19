import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Button {
    id: button
    required property string name
    property bool editable: true
    signal inserted(string name)
    objectName: "wildcard_" + name
    text: name
    focusPolicy: Qt.NoFocus
    hoverEnabled: true
    onClicked: inserted(name)
    onHoveredChanged: {
        if (hovered) { closeDelay.stop(); openDelay.restart() }
        else { openDelay.stop(); closeDelay.restart() }
    }
    onVisibleChanged: if (!visible) card.close()
    Timer { id: openDelay; interval: 400; onTriggered: card.open() }
    Timer {
        id: closeDelay
        interval: 300
        onTriggered: if (!button.hovered && !cardHover.hovered) card.close()
    }
    Popup {
        id: card
        objectName: "wildcardCard_" + button.name
        parent: Overlay.overlay
        modal: false
        focus: false
        padding: 6
        width: Math.min(380, parent ? parent.width : 380)
        height: Math.min(330, lines.implicitHeight + padding * 2)
        x: Math.max(0, Math.min(button.mapToItem(parent, 0, button.height).x, parent.width - width))
        y: Math.max(0, Math.min(button.mapToItem(parent, 0, button.height).y, parent.height - height))
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        contentItem: ScrollView {
            clip: true
            contentWidth: availableWidth
            HoverHandler {
                id: cardHover
                onHoveredChanged: {
                    if (hovered) closeDelay.stop()
                    else closeDelay.restart()
                }
            }
            Column {
                id: lines
                width: card.availableWidth
                Repeater {
                    model: App.wildcardOptions[button.name] || []
                    CheckBox {
                        id: check
                        required property var modelData
                        required property int index
                        width: lines.width
                        checked: modelData.enabled
                        enabled: button.editable
                        focusPolicy: Qt.NoFocus
                        text: modelData.text
                        contentItem: Label {
                            text: check.text
                            leftPadding: check.indicator.width + check.spacing
                            wrapMode: Text.Wrap
                            verticalAlignment: Text.AlignVCenter
                        }
                        onToggled: App.setWildcardLine(button.name, index, checked)
                    }
                }
                Label {
                    visible: !(App.wildcardOptions[button.name] || []).length
                    text: "No usable lines in this wildcard."
                    width: lines.width
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}

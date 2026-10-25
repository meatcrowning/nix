import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: explorer
    property var service: App.inspection
    required property Item imageItem
    property bool active: false
    property real nextX: 0
    property real nextY: 0
    function track(area, x, y) {
        if (!active || !service || !service.available || service.imageHeld) return
        var pt = area.mapToItem(imageItem, x, y)
        if (pt.x < 0 || pt.y < 0 || pt.x >= imageItem.width || pt.y >= imageItem.height) {
            leave(); return
        }
        leaveTimer.stop()
        nextX = pt.x / imageItem.width
        nextY = pt.y / imageItem.height
        if (!sample.running) sample.start()
    }
    function hold(area, x, y) {
        if (!active || !service || !service.available) return
        sample.stop(); leaveTimer.stop()
        var pt = area.mapToItem(imageItem, x, y)
        service.holdImage(pt.x / imageItem.width, pt.y / imageItem.height)
    }
    function leave() {
        sample.stop()
        if (!panelHover.hovered) leaveTimer.restart()
    }
    onActiveChanged: if (!active) { sample.stop(); leaveTimer.stop(); service.leaveImage() }
    // Coalesce pointer motion; this is input sampling, not visual animation.
    Timer { id: sample; interval: 40; onTriggered: explorer.service.hoverImage(explorer.nextX, explorer.nextY) }
    // Allow crossing the gap from the picture into the interactive tooltip.
    Timer { id: leaveTimer; interval: 200; onTriggered: if (!panelHover.hovered) explorer.service.leaveImage() }
    Pane {
        id: panel
        objectName: "nearbyTokens"
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 8
        visible: explorer.active && explorer.service && explorer.service.nearby.length > 0
        padding: 6
        width: Math.min(280, explorer.width)
        HoverHandler {
            id: panelHover
            onHoveredChanged: {
                if (hovered) { sample.stop(); leaveTimer.stop() }
                else explorer.leave()
            }
        }
        ColumnLayout {
            anchors.fill: parent
            spacing: 2
            Label {
                color: "white"
                text: explorer.service.imageHeld ? "Held area · choose a token"
                      : explorer.service.picking ? "Click image to hold tokens" : "Nearby tokens"
                Layout.fillWidth: true
            }
            ToolButton {
                id: resumeButton
                text: "Resume hover"
                contentItem: Text {
                    text: resumeButton.text
                    font: resumeButton.font
                    color: "white"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                visible: explorer.service.imageHeld
                onClicked: explorer.service.releaseImage()
            }
            Repeater {
                model: explorer.service ? explorer.service.nearby : []
                Button {
                    id: tokenButton
                    required property var modelData
                    objectName: "nearbyTokenChoice"
                    Layout.fillWidth: true
                    enabled: !explorer.service.picking || explorer.service.imageHeld
                    hoverEnabled: true
                    onHoveredChanged: {
                        if (hovered) explorer.service.hoverNearby(modelData.choice)
                        else explorer.service.leaveNearby(modelData.choice)
                    }
                    text: modelData.label + "  ·  " + Math.round(modelData.score * 100) + "%"
                    contentItem: Text {
                        text: tokenButton.text
                        font: tokenButton.font
                        color: "white"
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: explorer.service.chooseNearby(modelData.choice)
                }
            }
        }
    }
}

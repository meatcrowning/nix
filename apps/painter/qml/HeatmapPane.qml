import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../qmlcommon"

Rectangle {
    id: pane
    property var service
    signal closed()
    color: Theme.bg
    border.color: Theme.textDim
    MouseArea { anchors.fill: parent }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        RowLayout {
            Layout.fillWidth: true
            ComboBox {
                id: chooser
                Layout.fillWidth: true
                model: pane.service ? pane.service.tokens : []
                textRole: "label"
                onActivated: pane.service.select(currentIndex)
                Accessible.name: "Prompt token heatmap"
            }
            Button { text: "Close"; onClicked: pane.closed() }
        }
        PixelText {
            Layout.fillWidth: true
            text: "Token associations · positive prompt · experimental"
            wrapMode: Text.Wrap
        }
        Image {
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: pane.visible && pane.service ? pane.service.overlay : ""
            fillMode: Image.PreserveAspectFit
            cache: false
            asynchronous: true
        }
    }
    onVisibleChanged: if (visible && service && service.available) {
        chooser.currentIndex = 0
        service.select(0)
    }
}

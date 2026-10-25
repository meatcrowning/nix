import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: pane
    property var service
    property bool nativeToolbar: false
    signal toggled()
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        // Hyprland's titlebar cannot host a combo; keep a compact local row.
        RowLayout {
            visible: !pane.nativeToolbar
            Layout.fillWidth: true
            Button { text: "Heatmap"; checkable: true; checked: true; onClicked: pane.toggled() }
            ComboBox {
                Layout.fillWidth: true
                model: pane.service ? pane.service.tokens : []
                textRole: "label"
                currentIndex: pane.service ? pane.service.selected : -1
                onActivated: pane.service.select(currentIndex)
                Accessible.name: "Prompt token heatmap"
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.bg
            Image {
                anchors.fill: parent
                source: pane.visible && pane.service ? pane.service.overlay : ""
                fillMode: Image.PreserveAspectFit
                cache: false
                asynchronous: true
            }
        }
    }
}

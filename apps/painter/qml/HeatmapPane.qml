import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: pane
    property var service
    property bool nativeToolbar: false
    signal toggled()
    implicitHeight: nativeToolbar ? 0 : controls.implicitHeight
    RowLayout {
        id: controls
        anchors.fill: parent
        visible: !pane.nativeToolbar
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
}

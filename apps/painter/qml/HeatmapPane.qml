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
            model: pane.service ? pane.service.choices : []
            textRole: "label"
            currentIndex: pane.service ? pane.service.selected + 1 : -1
            onActivated: pane.service.select(currentIndex - 1)
            ToolTip.visible: hovered
            ToolTip.text: "All tokens: mean saved association scores, with relative thermal contrast. Blue is low; red is high."
            Accessible.name: "Prompt token heatmap"
        }
    }
}

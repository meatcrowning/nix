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
            model: ["Positive", "Negative"]
            currentIndex: pane.service && pane.service.branch === "negative" ? 1 : 0
            onActivated: pane.service.selectBranch(currentIndex === 1 ? "negative" : "positive")
            ToolTip.visible: hovered
            ToolTip.text: pane.service ? pane.service.status + "\nRelative association; blue is low and red is high. Agreement is consistency, not confidence." : ""
            Accessible.name: "Heatmap prompt"
        }
        Button {
            text: pane.service ? pane.service.gridLabel : "Grid comparison"
            enabled: pane.service && pane.service.branchAvailable && !pane.service.exporting
            checkable: true
            checked: pane.service && pane.service.picking
            onClicked: pane.service.toggleGrid()
            ToolTip.visible: hovered
            ToolTip.text: pane.service ? pane.service.gridStatus : ""
        }
    }
}

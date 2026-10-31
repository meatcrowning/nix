import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

Item {
    id: pane
    objectName: "jobQueuePane"
    property bool winActive: true
    property string expanded: ""
    PixelText {
        id: heading
        text: "Job queue · " + App.jobQueue.rows.length
        color: Theme.text
    }
    PixelText {
        anchors.top: heading.bottom
        anchors.topMargin: 8
        text: "No queued jobs"
        color: Theme.textDim
        visible: App.jobQueue.rows.length === 0
    }
    KineticListView {
        id: jobs
        anchors.top: heading.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true
        spacing: 6
        model: App.jobQueue.rows
        ScrollBar.vertical: VScroll { id: bar }
        delegate: Item {
            id: row
            required property var modelData
            width: jobs.width - bar.barW
            height: content.implicitHeight + 8
            Column {
                id: content
                width: parent.width
                spacing: 3
                PixelText {
                    width: parent.width
                    text: row.modelData.state + " · " + row.modelData.promptLabel
                    color: row.modelData.state === "Running" ? Theme.accent : Theme.textDim
                    elide: Text.ElideRight
                }
                PixelText {
                    width: parent.width
                    text: row.modelData.prompt || "(empty prompt)"
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    MouseArea {
                        anchors.fill: parent
                        onClicked: pane.expanded = pane.expanded === row.modelData.id ? "" : row.modelData.id
                    }
                    ToolTipArea { anchors.fill: parent; text: row.modelData.details }
                }
                PixelText {
                    width: parent.width
                    text: "Seed " + row.modelData.seed + " · " + row.modelData.label
                    elide: Text.ElideRight
                    color: Theme.textDim
                }
                Flow {
                    width: parent.width
                    spacing: 4
                    TextButton {
                        label: "[ Up ]"
                        winActive: pane.winActive
                        enabled: row.modelData.canUp
                        onClicked: App.jobQueue.move(row.modelData.id, -1)
                    }
                    TextButton {
                        label: "[ Down ]"
                        winActive: pane.winActive
                        enabled: row.modelData.canDown
                        onClicked: App.jobQueue.move(row.modelData.id, 1)
                    }
                    TextButton {
                        label: "[ Stop ]"
                        winActive: pane.winActive
                        enabled: row.modelData.canStop
                        onClicked: App.jobQueue.stop(row.modelData.id)
                        ToolTipArea { anchors.fill: parent; text: "Cancel this job without saving" }
                    }
                    TextButton {
                        label: "[ Details ]"
                        winActive: pane.winActive
                        lit: pane.expanded === row.modelData.id
                        onClicked: pane.expanded = pane.expanded === row.modelData.id ? "" : row.modelData.id
                    }
                }
                PixelText {
                    width: parent.width
                    visible: pane.expanded === row.modelData.id
                    text: row.modelData.details
                    wrapMode: Text.Wrap
                    color: Theme.textDim
                }
            }
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.border
            }
        }
    }
}

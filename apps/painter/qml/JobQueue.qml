import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

Item {
    id: pane
    objectName: "jobQueuePane"
    property bool winActive: true
    property string expanded: ""
    property string draggedId: ""
    property string draggedText: ""
    property string targetId: ""
    property bool targetAfter: false
    property real targetY: -1
    property point pointer: Qt.point(0, 0)

    function locateDrop() {
        targetId = ""
        targetY = -1
        var p = jobs.mapFromItem(pane, pointer.x, pointer.y)
        if (p.x < 0 || p.x > jobs.width || p.y < 0 || p.y > jobs.height) return
        var index = jobs.indexAt(4, p.y + jobs.contentY)
        if (index < 0) index = jobs.indexAt(4, p.y + jobs.contentY + jobs.spacing)
        if (index < 0 && p.y + jobs.contentY >= jobs.contentHeight) index = jobs.count - 1
        var item = jobs.itemAtIndex(index)
        if (!item || !item.modelData.canDrag || item.modelData.id === draggedId) return
        targetId = item.modelData.id
        targetAfter = p.y + jobs.contentY > item.y + item.height / 2
        targetY = item.mapToItem(pane, 0, targetAfter ? item.height : 0).y
    }
    function finishDrag(cancelled) {
        var source = draggedId, target = targetId, after = targetAfter
        draggedId = ""
        targetId = ""
        targetY = -1
        // Replacing a QVariantList can destroy the MouseArea delivering release.
        Qt.callLater(function() {
            jobs.currentIndex = -1
            App.jobQueue.setDragging(false)
            if (!cancelled && source && target) App.jobQueue.moveTo(source, target, after)
        })
    }
    Timer {
        interval: 40
        repeat: true
        running: pane.draggedId !== ""
        onTriggered: {
            var p = jobs.mapFromItem(pane, pane.pointer.x, pane.pointer.y)
            var step = p.y < 24 ? -12 : p.y > jobs.height - 24 ? 12 : 0
            jobs.contentY = Math.max(0, Math.min(Math.max(0, jobs.contentHeight - jobs.height), jobs.contentY + step))
            pane.locateDrop()
        }
    }
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
        objectName: "queueList"
        anchors.top: heading.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true
        spacing: 6
        model: App.jobQueue.rows
        currentIndex: -1
        ScrollBar.vertical: VScroll { id: bar }
        delegate: Item {
            id: row
            required property var modelData
            required property int index
            width: jobs.width - bar.barW
            height: content.implicitHeight + 8
            opacity: pane.draggedId === modelData.id ? 0.5 : 1
            Column {
                id: content
                width: parent.width
                spacing: 3
                Item {
                    width: parent.width
                    height: summary.implicitHeight
                    Column {
                        id: summary
                        width: parent.width
                        spacing: 3
                        PixelText {
                            objectName: "queueJobTitle"
                            width: parent.width
                            text: "#" + row.modelData.number + " · " + (row.modelData.prompt.replace(/\s+/g, " ") || "(empty prompt)")
                            color: row.modelData.state === "Running" ? Theme.accent : Theme.text
                            elide: Text.ElideRight
                        }
                    }
                    MouseArea {
                        id: dragArea
                        objectName: "queueJobDrag"
                        anchors.fill: parent
                        enabled: row.modelData.canDrag
                        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                        preventStealing: true
                        property point start: Qt.point(0, 0)
                        onPressed: function(m) {
                            start = mapToItem(pane, m.x, m.y)
                            // Retain the pressed delegate even after edge scrolling
                            // carries it beyond the list's delegate cache.
                            jobs.currentIndex = row.index
                            App.jobQueue.setDragging(true)
                        }
                        onPositionChanged: function(m) {
                            if (!pressed) return
                            pane.pointer = mapToItem(pane, m.x, m.y)
                            if (!pane.draggedId && Math.abs(pane.pointer.y - start.y) + Math.abs(pane.pointer.x - start.x) >= Qt.styleHints.startDragDistance) {
                                pane.draggedId = row.modelData.id
                                pane.draggedText = "#" + row.modelData.number + " · " + row.modelData.prompt.replace(/\s+/g, " ")
                            }
                            if (pane.draggedId) pane.locateDrop()
                        }
                        onReleased: pane.finishDrag(false)
                        onCanceled: pane.finishDrag(true)
                    }
                    ToolTipArea {
                        anchors.fill: parent
                        enabled: pane.draggedId === ""
                        text: row.modelData.state + "\n" + row.modelData.details
                    }
                }
                Item {
                    width: parent.width
                    height: Math.max(seedText.implicitHeight, actions.implicitHeight)
                    PixelText {
                        id: seedText
                        objectName: "queueJobSeed"
                        anchors.left: parent.left
                        anchors.right: actions.left
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.seed + " · " + row.modelData.label
                        elide: Text.ElideRight
                        color: Theme.textDim
                        ToolTipArea { anchors.fill: parent; text: seedText.text }
                    }
                    Row {
                        id: actions
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 4
                        TextButton {
                            label: "[ Stop ]"
                            winActive: pane.winActive
                            enabled: row.modelData.canStop
                            onClicked: App.jobQueue.stop(row.modelData.id)
                            ToolTipArea { anchors.fill: parent; text: "Stop sampling and decode/save the current latent" }
                        }
                        TextButton {
                            label: "[ Details ]"
                            winActive: pane.winActive
                            lit: pane.expanded === row.modelData.id
                            onClicked: pane.expanded = pane.expanded === row.modelData.id ? "" : row.modelData.id
                        }
                        TextButton {
                            label: "[ Cancel ]"
                            winActive: pane.winActive
                            enabled: row.modelData.canCancel
                            onClicked: App.jobQueue.cancel(row.modelData.id)
                            ToolTipArea { anchors.fill: parent; text: "Discard this job without decoding or saving" }
                        }
                    }
                }
                PixelText {
                    width: parent.width
                    visible: pane.expanded === row.modelData.id
                    text: row.modelData.state + "\n" + row.modelData.details
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
    Rectangle {
        visible: pane.targetY >= jobs.y && pane.targetY <= pane.height
        y: pane.targetY
        width: jobs.width - bar.barW
        height: 2
        color: Theme.accent
    }
    Rectangle {
        visible: pane.draggedId !== ""
        x: 4
        y: Math.max(jobs.y, Math.min(pane.height - height, pane.pointer.y + 12))
        width: Math.max(0, pane.width - bar.barW - 8)
        height: dragLabel.implicitHeight + 8
        color: Theme.bgAlt
        border.color: Theme.accent
        PixelText {
            id: dragLabel
            anchors.fill: parent
            anchors.margins: 4
            text: pane.draggedText
            elide: Text.ElideRight
        }
    }
}

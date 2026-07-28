import QtQuick

Rectangle {
    color: Theme.bgAlt
    border.color: Theme.border
    border.width: 1

    // Progress fills the bar behind the text.
    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 1
        width: (parent.width - 2) * App.progress
        color: Theme.highlight
        visible: App.busy
    }

    Row {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: 8
        spacing: 12

        PixelText {
            text: App.ready ? App.status : (App.status + " ...")
            color: App.ready ? Theme.textDim : Theme.warn
        }
        PixelText {
            visible: App.busy && App.currentNode !== ""
            text: App.currentNode
            color: Theme.accent
        }
        PixelText {
            visible: App.busy
            text: Math.round(App.progress * 100) + "%"
            color: Theme.text
        }
        PixelText {
            visible: App.queue > 0
            text: "queued " + App.queue
            color: Theme.info
        }
    }

    Row {
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: parent.right
        anchors.rightMargin: 8
        spacing: 10

        PixelText {
            text: "[ generate ]"
            color: App.ready ? Theme.accent : Theme.dim
            MouseArea {
                anchors.fill: parent
                enabled: App.ready
                onClicked: root.submit()
            }
        }
        PixelText {
            visible: App.busy
            text: "[ cancel ]"
            color: Theme.crit
            MouseArea { anchors.fill: parent; onClicked: App.cancel() }
        }
    }
}

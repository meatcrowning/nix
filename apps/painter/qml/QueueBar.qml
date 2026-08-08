import QtQuick

Rectangle {
    color: Theme.bgAlt
    border.color: Theme.border
    border.width: Theme.ctrlBorder

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
        // How far, then how long. A per-cent alone cannot say whether a job is
        // slow or stuck; the clock ticks once a second while one is running,
        // and then STAYS on the finished time. It used to vanish with the run,
        // which threw away the one number the run had just measured — the only
        // other copy was a toast that fades.
        //
        // The bare clock is the live one; `took` marks it as settled, borrowing
        // the `queued N` idiom beside it rather than inventing a second one.
        PixelText {
            visible: App.busy || App.lastElapsed > 0
            text: {
                var s = Math.floor(App.busy ? App.elapsed : App.lastElapsed)
                var m = Math.floor(s / 60)
                var r = s % 60
                var clock = m + ":" + (r < 10 ? "0" : "") + r
                return App.busy ? clock : "took " + clock
            }
            color: Theme.textDim
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

        TextButton {
            anchors.verticalCenter: parent.verticalCenter
            label: "[ generate ]"
            enabled: App.ready
            winActive: root.winActive
            onClicked: root.submit()
        }
        TextButton {
            anchors.verticalCenter: parent.verticalCenter
            visible: App.busy
            label: "[ cancel ]"
            tone: Theme.crit
            winActive: root.winActive
            onClicked: App.cancel()
        }
    }
}

import QtQuick

// A single notification toast. Text-only, coloured by urgency, click anywhere to
// dismiss, hover to pause its auto-expiry. Styled to match OsdWindow's card:
// bgAlt fill, hard edges (radius 0), a 2px tinted border and a left urgency
// strip echoing the bar's accent stripe.
Rectangle {
    id: card

    // The Quickshell Notification object this toast renders.
    required property var notif

    readonly property int urgency: notif ? notif.urgency : 1
    readonly property bool critical: urgency === 2
    readonly property color tint: critical ? Theme.crit
                                : urgency === 0 ? Theme.info
                                : Theme.accent

    width: 300
    implicitHeight: Math.max(Theme.cell, content.implicitHeight + 20)
    radius: 0
    color: Theme.bgAlt
    border.width: 2
    border.color: tint

    // fade in on arrival (removal is instant when the model drops the item)
    opacity: 0
    Component.onCompleted: opacity = 1
    Behavior on opacity { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

    // left urgency strip
    Rectangle {
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        width: 3
        color: card.tint
    }

    Column {
        id: content
        anchors {
            left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
            leftMargin: 14; rightMargin: 12
        }
        spacing: 4

        // app name — the tinted header line
        PixelText {
            width: parent.width
            text: (card.notif && card.notif.appName) ? card.notif.appName : "notification"
            color: card.tint
            font.pixelSize: Theme.fontSize
            elide: Text.ElideRight
        }

        // summary — the headline
        PixelText {
            width: parent.width
            text: card.notif ? card.notif.summary : ""
            color: Theme.text
            font.pixelSize: Theme.fontSize
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            visible: text.length > 0
        }

        // body — dimmed detail, capped so a wall of text can't fill the screen
        PixelText {
            width: parent.width
            text: Notifications.plain(card.notif ? card.notif.body : "")
            color: Theme.textDim
            font.pixelSize: Theme.fontSize
            wrapMode: Text.WordWrap
            maximumLineCount: 4
            elide: Text.ElideRight
            visible: text.length > 0
        }
    }

    // auto-expiry: runs for non-critical toasts while not hovered. Leaving the
    // toast restarts the countdown (running false->true resets the Timer).
    Timer {
        interval: Notifications.timeoutMs
        running: !card.critical && !hover.containsMouse
        onTriggered: if (card.notif) card.notif.expire()
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: if (card.notif) card.notif.dismiss()
    }
}

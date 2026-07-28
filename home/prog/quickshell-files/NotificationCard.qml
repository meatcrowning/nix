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

    // Per-notification expiry, straight off the spec's expire_timeout: 0 means
    // NEVER expire, >0 is an explicit ms lifetime, -1 (the default) means "use
    // the server's". Ignoring it was a real bug, not a stylistic choice: a
    // progress toast that morphs in place (surfer's downloads, filer's video
    // compress — notify-send -r) got retired by our 5s timer between updates,
    // so the next --replace-id named an id the server no longer had and it
    // opened a BRAND NEW toast, with its own sound, on every whole percent.
    // "Longer downloads just trigger the toast over and over" was that.
    readonly property bool persistent: critical || (notif && notif.expireTimeout === 0)
    readonly property int expiryMs: (notif && notif.expireTimeout > 0)
                                    ? notif.expireTimeout : Notifications.timeoutMs
    readonly property color tint: critical ? Theme.crit
                                : urgency === 0 ? Theme.info
                                : Theme.accent

    width: SettingsStore.d.notifWidth
    implicitHeight: Math.max(Theme.cell, content.implicitHeight + 20)
    radius: 0
    color: Theme.bgAlt
    border.width: 2
    border.color: tint

    // fade in on arrival (removal is instant when the model drops the item)
    opacity: 0
    Component.onCompleted: opacity = 1
    // A fade, not a slide, so it keeps its own (shorter) duration — but it goes
    // through ViewMode.ms() like everything else, so reduceMotion and animSpeed
    // reach it. docs/DESIGN.md §6.2: the CURVE is the desktop's, the duration is a
    // fade's to choose.
    Behavior on opacity { NumberAnimation { duration: ViewMode.ms(160); easing.type: ViewMode.slideEasing } }

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
            text: (card.notif && card.notif.appName)
                  ? Glyphs.px(card.notif.appName) : "notification"
            color: card.tint
            font.pixelSize: Theme.fontSize
            elide: Text.ElideRight
        }

        // summary — the headline
        PixelText {
            width: parent.width
            // Summary skips Notifications.plain() on purpose — a headline is not
            // supposed to carry markup — but it is prose from a stranger just
            // like the body, so it still needs the font map.
            text: card.notif ? Glyphs.px(card.notif.summary) : ""
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

    // auto-expiry: runs for non-persistent toasts while not hovered. Leaving the
    // toast restarts the countdown (running false->true resets the Timer).
    Timer {
        id: expiry
        interval: card.expiryMs
        running: !card.persistent && !hover.containsMouse
        onTriggered: if (card.notif) card.notif.expire()
    }

    // A --replace-id update reuses the SAME Notification object, so no new card
    // is built and the countdown would otherwise keep running from the original
    // arrival. Fresh content means a fresh lifetime.
    Connections {
        target: card.notif
        function onSummaryChanged() { if (expiry.running) expiry.restart(); }
        function onBodyChanged() { if (expiry.running) expiry.restart(); }
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: if (card.notif) card.notif.dismiss()
    }
}

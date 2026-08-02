import QtQuick
import Quickshell

// A single notification toast. Text-only, coloured by urgency, click anywhere to
// dismiss, hover to pause its auto-expiry. Styled to match OsdWindow's card:
// bgAlt fill, hard edges (radius 0), a 2px tinted border and a left urgency
// strip echoing the bar's accent stripe.
//
// A surfer image-download completion toast additionally carries the downloaded
// file's path in the `x-download-image` hint (Notifications.qml extraHints);
// such a toast shows a thumbnail on the left and clicking it OPENS the image
// in the viewer (xdg-open -> the default image handler) before dismissing.
Rectangle {
    id: card

    // The Quickshell Notification object this toast renders.
    required property var notif

    readonly property int urgency: notif ? notif.urgency : 1
    readonly property bool critical: urgency === 2

    // Absolute path of a downloaded image, from surfer's completion toast, or
    // "" when this toast has no openable image (a progress toast, a non-image
    // download, anything else).
    readonly property string imagePath: notif && notif.hints
        ? String(notif.hints["x-download-image"] || "").trim() : ""
    readonly property bool hasImage: imagePath !== ""
    readonly property int thumbSize: 48

    // A local absolute path -> a file:// URL QML Image can load, with each
    // segment percent-encoded (a space, `#` or `?` in a filename must not be
    // read as a URL separator/fragment).
    function fileUrl(p) {
        return "file://" + p.split("/").map(encodeURIComponent).join("/");
    }

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
    implicitHeight: Math.max(Theme.cell,
                             (hasImage ? thumbSize : 0) + 20,
                             content.implicitHeight + 20)
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

    Row {
        id: bodyRow
        anchors {
            left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
            leftMargin: 14; rightMargin: 12
        }
        spacing: 10

        // thumbnail of the downloaded image — only on a surfer image-download
        // completion toast. Fixed slot (reserved only when the hint is present,
        // so its arrival can't reflow the text). Downscaled, async, like the
        // desktop's other thumbs (filer's PreviewTile); a file that vanished
        // since the toast rendered just draws nothing in the box.
        Image {
            id: thumb
            visible: card.hasImage
            width: card.thumbSize
            height: card.thumbSize
            source: card.hasImage ? card.fileUrl(card.imagePath) : ""
            sourceSize.width: card.thumbSize * 2
            sourceSize.height: card.thumbSize * 2
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: true
            smooth: false
        }

        Column {
            id: content
            width: parent.width - (thumb.visible ? thumb.width + bodyRow.spacing : 0)
            spacing: 4

            // who it is from — the tinted header line. Usually the app's own name;
            // for a notification relayed off his phone it is the PHONE's name, since
            // KDE Connect's appName is the same useless "KDE Connect" on every one.
            // Notifications.sender() owns that choice and the font map with it.
            PixelText {
                width: parent.width
                text: Notifications.sender(card.notif)
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
        // An image-download toast also OPENS the downloaded image in the viewer
        // (xdg-open -> the default image handler) — the whole card is the
        // affordance. Anything else keeps the plain dismiss.
        onClicked: {
            if (!card.notif)
                return;
            if (card.hasImage)
                Quickshell.execDetached(["xdg-open", card.imagePath]);
            card.notif.dismiss();
        }
    }
}

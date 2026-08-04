import QtQuick
import Quickshell
import Quickshell.Widgets
import Quickshell.Io

// A single notification toast. Text-only, coloured by urgency, click anywhere to
// dismiss, hover to pause its auto-expiry. Styled to match OsdWindow's card:
// bgAlt fill, hard edges (radius 0), a 2px tinted border and a left urgency
// strip echoing the bar's accent stripe.
//
// A surfer image-download completion toast additionally carries the downloaded
// file's path in the `x-download-image` hint (Notifications.qml extraHints);
// such a toast shows a thumbnail on the left and clicking it OPENS the image
// in the viewer (xdg-open -> the default image handler) before dismissing. The
// path surfer advertises is ~/Downloads/<name>, but `sort-downloads` files
// image downloads out of ~/Downloads into ~/Pictures within seconds — so both
// the thumbnail and the open resolve the file's CURRENT location via
// scripts/dl-resolve.py rather than trusting the (possibly stale) hinted path.
//
// The screenshot and screen-recording completion toasts (Screenshot.qml) use
// the same hint for the same thumbnail. A recording carries TWO paths: the
// thumbnail is a poster frame (`x-download-image`, QML Image cannot decode an
// mp4) while `x-open-path` points the click at the video itself. When
// `x-open-path` differs from the thumbnail it is a path we control (a capture,
// never in ~/Downloads), so the click opens it directly without dl-resolve.
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

    // What clicking the card opens. `x-open-path` overrides the thumbnail path
    // (a recording thumbnails a poster frame but opens the video); it falls back
    // to the thumbnail so a plain image toast keeps opening its own image.
    readonly property string openPath: notif && notif.hints
        ? (String(notif.hints["x-open-path"] || "").trim() || imagePath) : imagePath
    readonly property bool hasOpen: openPath !== ""

    // The file's CURRENT on-disk location, resolved via scripts/dl-resolve.py.
    // Starts at the hinted path and is replaced by the resolver as soon as the
    // process returns (the file may already have been sorted to ~/Pictures).
    property string resolvedPath: ""
    property bool _openPending: false

    // Resolves the real on-disk path for the thumbnail and for the click's
    // xdg-open. Runs on every click so a file sorted away to ~/Pictures after
    // the card rendered still opens. (`running` auto-resets to false after the
    // process exits, so re-setting it to true re-runs — the same one-shot
    // trigger Procs.refresh uses.)
    function resolve() {
        if (!card.hasImage)
            return;
        dlres.running = false;
        dlres.running = true;
    }

    Process {
        id: dlres
        command: [Quickshell.shellDir + "/scripts/dl-resolve.py", card.imagePath]
        stdout: StdioCollector {
            onStreamFinished: {
                const p = this.text.trim();
                if (p)
                    card.resolvedPath = p;
                if (card._openPending) {
                    card._openPending = false;
                    if (p)
                        NixPath.launch(["xdg-open", p]);
                    if (card.notif)
                        card.notif.dismiss();
                }
            }
        }
    }

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

    // The header line — who the toast is from. Notifications.sender() usually
    // returns the app's own name, but names the phone for a KDE Connect relay.
    readonly property string headerText: Notifications.sender(card.notif)

    // The sending app's icon, for the left of the header row. appIcon is the
    // Notify() app_icon field: an icon-theme NAME most of the time, but the spec
    // also allows an absolute path or a file: URI, so those are passed through
    // untouched. When the app sent no usable icon we fall back to its
    // desktopEntry, then to nothing — a name-only header, never a generic box.
    readonly property string iconSource: {
        if (!card.notif)
            return "";
        const ai = (card.notif.appIcon || "").toString();
        if (ai.startsWith("/") || ai.startsWith("file:"))
            return ai;
        if (ai)
            return Quickshell.iconPath(ai, true);
        const de = (card.notif.desktopEntry || "").toString();
        return de ? Quickshell.iconPath(de, true) : "";
    }

    // The summary is dropped when it merely repeats the header (many apps send
    // their own name as both appName and summary), so the name shows ONCE.
    readonly property string summaryText: card.notif ? Glyphs.px(card.notif.summary) : ""
    readonly property bool summaryDupesHeader:
        summaryText.trim().toLowerCase() === headerText.trim().toLowerCase()

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
    Component.onCompleted: {
        opacity = 1;
        // Kick off resolution of the real on-disk path (the hinted ~/Downloads
        // path may already have been sorted to ~/Pictures) so the thumbnail
        // points at the file wherever it actually is.
        card.resolve();
    }
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
            source: card.hasImage ? card.fileUrl(card.resolvedPath || card.imagePath) : ""
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

            // who it is from — the tinted header line, with the sending app's
            // icon to its left. Usually the app's own name; for a notification
            // relayed off his phone it is the PHONE's name, since KDE Connect's
            // appName is the same useless "KDE Connect" on every one.
            // Notifications.sender() owns that choice and the font map with it.
            Row {
                width: parent.width
                spacing: 6

                // A foreign app's icon keeps its own colours here — a toast is
                // the one place an icon is identifying a stranger. Our own
                // seals cannot: they are currentColor sigils, so drawn raw
                // they came out in the file's baked fallback (#cc4400, red) on
                // every wallpaper. AppIcon paints those in the header's tint,
                // the colour the name beside them already rides.
                AppIcon {
                    id: appIcon
                    visible: card.iconSource !== ""
                    width: Theme.fontSize + 4
                    height: Theme.fontSize + 4
                    source: card.iconSource
                    color: card.tint
                    tint: false
                    anchors.verticalCenter: parent.verticalCenter
                }

                PixelText {
                    width: parent.width - (appIcon.visible ? appIcon.width + parent.spacing : 0)
                    anchors.verticalCenter: parent.verticalCenter
                    text: card.headerText
                    color: card.tint
                    font.pixelSize: Theme.fontSize
                    elide: Text.ElideRight
                }
            }

            // summary — the headline. Skips Notifications.plain() on purpose — a
            // headline is not supposed to carry markup — but it is prose from a
            // stranger just like the body, so it still needs the font map (done in
            // card.summaryText). Hidden when it only repeats the header name.
            PixelText {
                width: parent.width
                text: card.summaryText
                color: Theme.text
                font.pixelSize: Theme.fontSize
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                visible: text.length > 0 && !card.summaryDupesHeader
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
            if (!card.hasOpen) {
                card.notif.dismiss();
                return;
            }
            if (card.openPath !== card.imagePath) {
                // A distinct open target (a recording's video): a path we control
                // that is not sorted away, so open it directly and skip resolve.
                NixPath.launch(["xdg-open", card.openPath]);
                card.notif.dismiss();
            } else {
                // Resolve at CLICK time: sort-downloads may have moved the file
                // out of ~/Downloads since the card rendered, so the open must
                // not trust the hinted path. dl-resolve's return opens it.
                card._openPending = true;
                card.resolve();
            }
        }
    }
}

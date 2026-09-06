import QtQuick
import Quickshell
import Quickshell.Widgets
import Quickshell.Io

// A notification toast with urgency styling, expiry/dismissal, optional image
// thumbnail, progress bar, and freedesktop action buttons.
// Download/recording paths are resolved at use time. Progress senders keep the
// toast alive with -t 0 and replace it in place (docs/DESIGN.md §8.1, §10.4).
// `default` remains the card click; explicit actions are rendered only when
// notifActions permits them.
Rectangle {
    id: card

    // The Quickshell Notification object this toast renders.
    required property var notif

    // Attached mode joins the card to the panel like the shortcut notch.
    property bool attached: false
    // Which side contains the panel mouth; false is the right edge.
    property bool mouthOnLeft: false
    // Notch overlap depth used by attached geometry.
    readonly property int mouth: attached ? NotchModel.overlap : 0
    // Floating cards exit toward their corner; attached cards exit into panel.
    property bool floatLeft: false

    // The server may untrack a card while its exit runs; closing forbids reuse.
    property bool closing: false

    // The exit slide landed; NotificationWindow drops the card from its stack.
    signal departed()

    // Keep the notification object alive until the exit animation completes.
    RetainableLock { object: card.notif; locked: true }

    // Reverse entry: attached cards retreat behind the panel; floating cards
    // retreat 48px and fade on the shared slide clock.
    function leave() {
        if (card.closing)
            return;
        card.closing = true;
        exit.start();
    }

    ParallelAnimation {
        id: exit
        NumberAnimation {
            target: card; property: "x"
            to: (card.attached ? card.mouthOnLeft : card.floatLeft)
                ? -(card.attached ? card.width : 48)
                : (card.attached ? card.width : 48)
            duration: ViewMode.ms(ViewMode.slideMs)
            easing.type: ViewMode.slideEasing
        }
        // The floating card's 160ms entry fade, mirrored. An attached card
        // stays opaque — the clip is the exit, as it was the entrance.
        NumberAnimation {
            target: card; property: "opacity"
            to: card.attached ? 1 : 0
            duration: ViewMode.ms(160)
            easing.type: ViewMode.slideEasing
        }
        onFinished: card.departed()
    }
    readonly property int lineW: 2
    // The arms run to the panel's face plus one line width: the corner is
    // painted over the strip rather than shared between two shapes abutting.
    readonly property int armW: width - mouth + lineW

    readonly property int urgency: notif ? notif.urgency : 1
    readonly property bool critical: urgency === 2

    // Absolute path of a downloaded image, from surfer's completion toast, or
    // "" when this toast has no openable image (a progress toast, a non-image
    // download, anything else).
    readonly property string imagePath: notif && notif.hints
        ? String(notif.hints["x-download-image"] || "").trim() : ""
    readonly property bool hasImage: imagePath !== ""
    readonly property int thumbSize: 48

    // What the thumbnail slot draws: our own toasts' downloaded file, else the
    // freedesktop image hint (image-path / image-data, exposed as notif.image)
    // when the images setting is on — the same setting the server advertises
    // `imageSupported` from, so the card renders exactly what was promised.
    // The hint image is display-only (album art, a contact photo): it is not a
    // file of his to open, so the click keeps its plain dismiss.
    readonly property string thumbSource: hasImage
        ? fileUrl(resolvedPath || imagePath)
        : ((SettingsStore.d.notifImages && notif && notif.image)
           ? notif.image : "")

    // A progress toast's fraction, 0..1, from the `value` hint (0-100 — the
    // de-facto freedesktop progress hint every other server reads, asked for by
    // name in Notifications.qml's extraHints). -1 means "no bar", which is
    // every toast that is not reporting on an operation still running:
    // repo-updates' pull-and-rebuild is the first sender.
    readonly property real progress: {
        if (!notif || !notif.hints)
            return -1;
        const raw = notif.hints["value"];
        if (raw === undefined || raw === null || raw === "")
            return -1;
        const v = Number(raw);
        return isNaN(v) ? -1 : Math.max(0, Math.min(1, v / 100));
    }

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
    // untouched. When the app sent no usable icon we resolve its DESKTOP ENTRY
    // and use the icon that entry declares — appIcon-less senders are the rule,
    // not the exception (kitty, KDE Connect), and the raw desktopEntry string
    // ("org.kde.kdeconnect.daemon") is usually not itself an icon name. The
    // appName heuristic covers senders that set no desktop-entry hint at all.
    // Still to nothing when all of that misses — a name-only header, never a
    // generic box.
    readonly property string iconSource: {
        if (!card.notif)
            return "";
        const ai = (card.notif.appIcon || "").toString();
        if (ai.startsWith("/") || ai.startsWith("file:"))
            return ai;
        if (ai)
            return Quickshell.iconPath(ai, true);
        const de = (card.notif.desktopEntry || "").toString();
        const entry = de
            ? (DesktopEntries.byId(de) ?? DesktopEntries.heuristicLookup(de))
            : DesktopEntries.heuristicLookup((card.notif.appName || "").toString());
        if (entry && entry.icon)
            return Quickshell.iconPath(entry.icon, true);
        return de ? Quickshell.iconPath(de, true) : "";
    }

    // The actions this toast carries, split the way the spec splits them: the
    // `default` one is the card's own click, everything else is a button. Capped
    // at three so a sender cannot push the text off a 300px card.
    //
    // A CRITICAL toast draws its buttons whatever `notifActions` says. The
    // setting exists so ordinary toasts stay text-only, and the server only
    // advertises the capability when it is on — but urgency 2 is the level
    // reserved for a question that has to be answered (the rebuild gate asking
    // whether to stop ComfyUI/ollama), and a question whose answer is drawn
    // nowhere is exactly the affordance-that-silently-fails docs/DESIGN.md §10
    // forbids. Drawing MORE than was advertised drops nothing; the bug that
    // rule guards against is advertising buttons and then swallowing them.
    readonly property var allActions:
        ((SettingsStore.d.notifActions || card.critical) && notif && notif.actions)
            ? notif.actions : []
    readonly property var buttonActions: {
        const out = [];
        for (let i = 0; i < card.allActions.length && out.length < 3; i++) {
            if (String(card.allActions[i].identifier) !== "default")
                out.push(card.allActions[i]);
        }
        return out;
    }
    readonly property var defaultAction: {
        for (let i = 0; i < card.allActions.length; i++) {
            if (String(card.allActions[i].identifier) === "default")
                return card.allActions[i];
        }
        return null;
    }

    // Invoke, then close: the sender is waiting on ActionInvoked (notify-send -w
    // prints the key and exits), and a toast whose action has been taken has
    // nothing left to say.
    function fire(a) {
        if (!a || card.closing)
            return;
        a.invoke();
        if (card.notif)
            card.notif.dismiss();
    }

    // The summary is dropped when it merely repeats the header (many apps send
    // their own name as both appName and summary), so the name shows ONCE.
    readonly property string summaryText: card.notif ? Glyphs.px(card.notif.summary) : ""
    readonly property bool summaryDupesHeader:
        summaryText.trim().toLowerCase() === headerText.trim().toLowerCase()

    // Sized to its content plus padding, like every other toast (docs/DESIGN.md
    // §10.4 — "a fixed slab was rejected"): notifWidth is the CAP, not the
    // size, so a short toast carries no blank right side. Only the texts' own
    // implicitWidths feed this — never a positioner's implicit size, which Qt
    // computes from actual child widths and would close a binding loop through
    // the card's own width. The 26 is bodyRow's desktop-visible padding
    // (14 + 12); the mouth is not counted because fitW is the DESKTOP-side
    // width — NotificationWindow adds the mouth on top.
    readonly property int fitW: {
        const text = Math.max(
            (appIcon.visible ? appIcon.width + headerRow.spacing : 0)
                + headerLabel.implicitWidth,
            summaryLabel.visible ? summaryLabel.implicitWidth : 0,
            bodyLabel.visible ? bodyLabel.implicitWidth : 0,
            actionsBox.visible ? actionRow.implicitWidth : 0);
        const pad = 26 + (thumb.visible ? thumbSize + bodyRow.spacing : 0);
        return Math.min(SettingsStore.d.notifWidth, pad + Math.ceil(text));
    }

    width: fitW
    implicitHeight: Math.max(Theme.cell,
                             (thumb.visible ? thumbSize : 0) + 20,
                             content.implicitHeight + 20)
    // Attached cards stay square: their border is the three-rectangle notch
    // construction below, which only meets the panel seam with square corners.
    radius: attached ? 0 : Theme.windowRounding
    color: Theme.bgAlt
    // Attached, the border is the three rectangles below (the notch's
    // construction); a four-sided border would close the mouth.
    border.width: attached ? 0 : Theme.windowBorderWidth
    border.color: tint

    // fade in on arrival (removal mirrors it — the exit animation above).
    // Attached cards slide out of the panel instead (NotificationWindow's add
    // transition), so they arrive at full opacity — a fade under the clip
    // would just dim the emerging card.
    opacity: attached ? 1 : 0
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

    // The mouth: the stretch under the bar body, in the bar's own background,
    // exactly like the notch's overlap. Any opaque pixel of this Overlay
    // surface covers the bar's accent strip beneath it; painting Theme.bg
    // makes the cover invisible against the bar, so the strip simply reads as
    // interrupted — detouring around the card's arms.
    Rectangle {
        visible: card.attached
        x: card.mouthOnLeft ? 0 : card.width - card.mouth
        width: card.mouth
        height: parent.height
        color: Theme.bg
    }

    // ---- the attached outline: three sides, in the urgency tint -----------
    // (DesktopNotch.qml's three-rectangle outline, per card.)
    Rectangle {   // the desktop-facing side
        visible: card.attached
        x: card.mouthOnLeft ? card.width - card.lineW : 0
        width: card.lineW
        height: parent.height
        color: card.tint
    }
    Rectangle {   // top arm
        visible: card.attached
        x: card.mouthOnLeft ? card.mouth - card.lineW : 0
        y: 0
        width: card.armW
        height: card.lineW
        color: card.tint
    }
    Rectangle {   // bottom arm
        visible: card.attached
        x: card.mouthOnLeft ? card.mouth - card.lineW : 0
        y: parent.height - card.lineW
        width: card.armW
        height: card.lineW
        color: card.tint
    }

    // urgency strip, on the desktop-facing edge (left unless the attached
    // mouth puts the bar there)
    Rectangle {
        anchors { top: parent.top; bottom: parent.bottom }
        x: (card.attached && card.mouthOnLeft) ? parent.width - width : 0
        width: 3
        color: card.tint
    }

    Row {
        id: bodyRow
        // Over the dismiss MouseArea, which fills the card and is declared last.
        // Only the action buttons actually take events up here — text and images
        // accept none, so a click anywhere else still falls through to dismiss.
        z: 1
        // The bar-side margin absorbs the mouth, so the text ends where the
        // desktop ends — nothing reads from under the panel.
        anchors {
            left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
            leftMargin: (card.attached && card.mouthOnLeft) ? 12 + card.mouth : 14
            rightMargin: (card.attached && card.mouthOnLeft) ? 14
                       : 12 + (card.attached ? card.mouth : 0)
        }
        spacing: 10

        // thumbnail — a download/capture completion toast's file, or the
        // freedesktop image hint (card.thumbSource decides). Fixed slot
        // (reserved only when a source is present, so its arrival can't reflow
        // the text). Downscaled, async, like the desktop's other thumbs
        // (filer's PreviewTile); a file that vanished since the toast rendered
        // just draws nothing in the box.
        Image {
            id: thumb
            visible: card.thumbSource !== ""
            width: card.thumbSize
            height: card.thumbSize
            source: card.thumbSource
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
                id: headerRow
                width: parent.width
                spacing: 6

                // A foreign app's icon keeps its own colours here — a toast is
                // the one place an icon is identifying a stranger. Our own
                // seals cannot: they are currentColor sigils, so drawn raw
                // they come out in the file's baked fallback — plain white,
                // which states nothing. AppIcon tints those to the header's
                // tint, the colour the name beside them already rides.
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
                    id: headerLabel
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
                id: summaryLabel
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
                id: bodyLabel
                width: parent.width
                text: Notifications.plain(card.notif ? card.notif.body : "")
                color: Theme.textDim
                font.pixelSize: Theme.fontSize
                wrapMode: Text.WordWrap
                maximumLineCount: 4
                elide: Text.ElideRight
                visible: text.length > 0
            }

            // The progress bar (docs/DESIGN.md §8.1: bgAlt box + 1px
            // Theme.border, fill inset margins: 1, width = round((parent-2) *
            // frac)) — the same geometry player's SysthemeToast draws, because
            // a long op reporting itself in a card is one vocabulary whether
            // the card is a toast or in-window. Only present when the sender
            // ships a `value` hint, and the fill eases so a jump from 12% to
            // 40% reads as movement rather than a teleport.
            Rectangle {
                width: parent.width
                height: 8
                visible: card.progress >= 0
                color: Theme.bgAlt
                border.width: 1
                border.color: Theme.border

                Rectangle {
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                    anchors.margins: 1
                    width: Math.max(0, Math.round((parent.width - 2) * card.progress))
                    color: card.tint
                    Behavior on width {
                        NumberAnimation { duration: ViewMode.ms(120); easing.type: Easing.OutCubic }
                    }
                }
            }

            // action buttons — right-aligned under the text, §7.5's dialog
            // button row. The wrapping Item is what lets a Row sit right-aligned
            // inside a Column (a Column owns its children's x, so the Row cannot
            // anchor itself). Sized to their labels rather than the settings
            // pages' 96px floor: three of those would not fit a 300px card.
            Item {
                id: actionsBox
                width: parent.width
                height: card.buttonActions.length > 0 ? actionRow.height + 4 : 0
                visible: card.buttonActions.length > 0

                Row {
                    id: actionRow
                    anchors { right: parent.right; bottom: parent.bottom }
                    spacing: 6

                    Repeater {
                        model: card.buttonActions
                        delegate: SetButton {
                            required property var modelData
                            text: Notifications.plain(modelData.text || modelData.identifier)
                            minWidth: 52
                            maxWidth: 120
                            onClicked: card.fire(modelData)
                        }
                    }
                }
            }
        }
    }

    // auto-expiry: runs for non-persistent toasts while not hovered. Leaving the
    // toast restarts the countdown (running false->true resets the Timer).
    Timer {
        id: expiry
        interval: card.expiryMs
        running: !card.persistent && !hover.containsMouse && !card.closing
        onTriggered: if (card.notif && !card.closing) card.notif.expire()
    }

    // A --replace-id update reuses the SAME Notification object, so no new card
    // is built and the countdown would otherwise keep running from the original
    // arrival. Fresh content means a fresh lifetime.
    Connections {
        target: card.notif
        function onSummaryChanged() { if (expiry.running) expiry.restart(); }
        function onBodyChanged() { if (expiry.running) expiry.restart(); }
        // A step that only moved the bar is still fresh content — and a sender
        // that sent a timeout with its progress toast should not have it die
        // mid-operation just because the wording did not change.
        function onHintsChanged() { if (expiry.running) expiry.restart(); }
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        // A departing card's notification is already closed — nothing left to
        // dismiss, open or invoke on it.
        enabled: !card.closing
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        // An image-download toast also OPENS the downloaded image in the viewer
        // (xdg-open -> the default image handler) — the whole card is the
        // affordance. Anything else keeps the plain dismiss.
        onClicked: {
            if (!card.notif)
                return;
            // The spec's `default` action IS this click. A sender that supplied
            // one gets it instead of a plain dismiss.
            if (card.defaultAction) {
                card.fire(card.defaultAction);
                return;
            }
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

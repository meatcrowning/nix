import QtQuick
import Quickshell

// The media widget's body: source app, track, cover art, cava spectrum, a
// draggable seekbar and the transport row. Everything it shows — including the
// spectrum feed — belongs to the Media singleton; being on screen is this
// component's only contribution, which is what `active` communicates (and what
// starts and stops cava).
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    property int pad: 10
    readonly property real inner: Math.max(180, width - 24)

    onActiveChanged: Media.watch(root, active)
    Component.onCompleted: { Media.watch(root, active); drawerOut = Media.queueOpen; noteRestSlack(); }
    Component.onDestruction: Media.watch(root, false)

    // ---- a transport button: pixel-font glyph, themed frame -------------
    component MediaButton: Rectangle {
        id: btn
        property string kind: "play"   // prev | next | play | pause | shuffle | repeat
        property bool active: true
        property bool toggled: false   // lit accent even without hover (repeat/shuffle on)
        signal clicked()

        // glyph per kind: skip << >>, play/pause > ||, shuffle *, repeat o
        readonly property string glyph: kind === "prev" ? "<<"
            : kind === "next" ? ">>"
            : kind === "pause" ? "||"
            : kind === "shuffle" ? "*"
            : kind === "repeat" ? "o"
            : ">"   // play

        // 24, not 26: five of these now share a row with the seekbar, and at the
        // narrow end of the panel's range every pixel they take comes straight
        // out of the seekbar's width.
        width: 24
        height: 24
        // toggled (repeat/shuffle on) inverts like the titlebar roll button:
        // accent fill + background-coloured glyph. Hover is the lighter bgAlt tint.
        color: btn.toggled ? Theme.accent : ((mba.containsMouse && active) ? Theme.bgAlt : "transparent")
        border.width: 1
        border.color: !active ? Theme.border : ((btn.toggled || mba.containsMouse) ? Theme.accent : Theme.border)
        opacity: active ? 1 : 0.4

        PixelText {
            anchors.centerIn: parent
            text: btn.glyph
            color: btn.toggled ? Theme.bg : ((mba.containsMouse && btn.active) ? Theme.accent : Theme.text)
        }

        MouseArea {
            id: mba
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: btn.active ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: if (btn.active) btn.clicked()
        }
    }

    // ---- spectrum: mediaSpectrumBars vertical bars ----------------------
    // cava's 0-100 is roughly linear in amplitude, and real music spends almost
    // all its time in the bottom third of that (measured medians 15, p90 49), so
    // a straight height mapping draws stubs that twitch by a pixel and reads as
    // "unresponsive". Curve it: gamma 0.55 pulls that same data up to med ~35 /
    // p90 ~68 without touching the top end (100 still maps to 100), so the bars
    // use the widget's full height and the same transient moves visibly further.
    // Do this here rather than raising cava's sensitivity — autosens owns that,
    // and fighting it is what forces per-track fiddling.
    component Spectrum: Item {
        id: spec
        readonly property int nbars: SettingsStore.d.mediaSpectrumBars
        readonly property real gamma: 0.55
        // Bars are gapless, so they can't be laid out by a Row with spacing 0: at
        // 32 buckets the per-bar width is fractional, and rounding each one
        // independently leaves subpixel seams between them. Position from the
        // shared edge instead — bar i spans round(w*i/n)..round(w*(i+1)/n), so one
        // bar's right edge IS the next one's left edge and the row stays exactly
        // `width` wide however the division falls.
        Repeater {
            model: spec.nbars
            Item {
                required property int index
                readonly property int x0: Math.round(spec.width * index / spec.nbars)
                x: x0
                width: Math.max(1, Math.round(spec.width * (index + 1) / spec.nbars) - x0)
                height: spec.height

                // level
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: Math.max(1, spec.height
                        * Math.pow(Math.max(0, Media.spectrumLevels[index] || 0) / 100, spec.gamma))
                    color: Theme.textDim
                    // cava already smooths (noise_reduction) and feeds 60fps, so
                    // this is a second low-pass on top. Keep it just long enough
                    // to absorb a dropped frame, not to re-add lag.
                    Behavior on height { NumberAnimation { duration: 25 } }
                }

                // peak marker — same gamma as the bar so it lines up with the bar
                // top on a fresh hit. Deliberately NOT animated: the fall is
                // already interpolated frame-by-frame by the gravity model, and a
                // Behavior here would drag the marker behind the peak it is
                // supposed to be pinning.
                //
                // The bar/marker pair is a light-on-dark split of the same hue:
                // the bars take Theme.textDim (the elapsed/remaining time colour)
                // and the markers the brighter Theme.accent, so a marker reads
                // both against the background it usually floats over and against
                // its own bar on the frames it rides the top. 2px tall — at 1px a
                // falling marker was too faint to track.
                Rectangle {
                    anchors { left: parent.left; right: parent.right }
                    height: 2
                    y: Math.min(spec.height - height, Math.max(0, spec.height - height - spec.height
                        * Math.pow(Math.max(0, Media.spectrumPeaks[index] || 0) / 100, spec.gamma)))
                    color: Theme.accent
                    visible: (Media.spectrumPeaks[index] || 0) > 0
                }
            }
        }
    }

    // Layout: the text block pinned to the top, the seekbar + transport pinned
    // to the bottom, and the artwork/spectrum row taking EVERYTHING in between.
    // That middle row is what absorbs a tall tile, so the widget has no dead
    // space at the bottom whatever height the grid gives it — and a bigger tile
    // buys a bigger cover and a taller spectrum rather than emptiness.
    readonly property int naturalArt: 60

    implicitWidth: 300
    // The open drawer's 90 is a CONSTANT, not `queueH`: queueH is derived from
    // the item's height, and feeding it back into implicitHeight — which is what
    // the popup takes its height FROM — is a binding loop.
    implicitHeight: pad * 2 + top.height + 6 + naturalArt + 6 + bottom.height
                    + handle.height + (Media.queueOpen ? 90 : 0)

    // ONE line: track on the left, artist on the right. It keeps its height when
    // both are empty, so nothing below it moves when playback stops — which is
    // the whole reason the strings are empty rather than a "nothing playing"
    // placeholder (see Media.dispTitle).
    Item {
        id: top
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 16

        PixelText {
            id: trackTitle
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            // Give the artist at most a third, and only what it actually needs,
            // so a long title uses the rest instead of eliding against a gap.
            width: parent.width - artistText.width - (artistText.width > 0 ? 8 : 0)
            elide: Text.ElideRight
            text: Media.dispTitle
            color: Theme.text
        }
        PixelText {
            id: artistText
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            width: Math.min(implicitWidth, parent.width / 3)
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
            text: Media.dispArtist
            color: Theme.textDim
        }
    }

    // artwork + spectrum, filling the gap between the two blocks
    Row {
        id: mid
        anchors {
            top: top.bottom; topMargin: 6
            bottom: bottom.top; bottomMargin: 6
            horizontalCenter: parent.horizontalCenter
        }
        width: root.inner
        spacing: 8

        // Vertical output volume, left of the cover. Same value and the same
        // absolute setter the bar's VU meter drags (SysInfo.setVolume), so the
        // two never disagree. Click or drag anywhere in the column to set it;
        // the wheel steps it.
        Item {
            id: vol
            width: 12
            height: mid.height

            readonly property real frac: SysInfo.volume < 0 ? 0 : SysInfo.volume / 100

            Rectangle {
                anchors.fill: parent
                color: Theme.bgAlt
                border.width: 1
                border.color: Theme.border
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 1 }
                height: Math.round((parent.height - 2) * vol.frac)
                color: SysInfo.muted ? Theme.textDim : Theme.accent
            }
            // level line, so the exact setting is readable even at a glance
            Rectangle {
                anchors { left: parent.left; right: parent.right }
                y: Math.max(0, Math.min(parent.height - 1,
                       Math.round((parent.height - 1) * (1 - vol.frac))))
                height: 1
                color: Theme.text
            }

            MouseArea {
                anchors { fill: parent; leftMargin: -3; rightMargin: -3 }
                acceptedButtons: Qt.LeftButton
                function setAt(y) {
                    SysInfo.setVolume(100 * (1 - Math.max(0, Math.min(1, y / vol.height))));
                }
                onPressed: (mouse) => setAt(mouse.y)
                onPositionChanged: (mouse) => { if (pressed) setAt(mouse.y); }
                onWheel: (wheel) => SysInfo.adjustVolume(
                    wheel.angleDelta.y > 0 ? SettingsStore.d.volumeStep : -SettingsStore.d.volumeStep)
            }
        }

        Item {
            id: artBox
            width: Math.min(mid.height, mid.width * 0.45)
            height: mid.height
            Rectangle {
                anchors.fill: parent
                color: Theme.bgAlt
                border.width: 1
                border.color: Theme.border
            }
            Image {
                id: art
                anchors { fill: parent; margins: 1 }
                source: Media.dispArt
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                clip: true
                // Decoded at twice the natural size so a tall tile's larger
                // cover is still sharp; NOT bound to the item's width, which
                // changes on every frame of a panel drag.
                sourceSize.width: 240
                sourceSize.height: 240
                visible: status === Image.Ready
            }
            // CP437 note glyph placeholder when there's no cover art
            PixelText {
                anchors.centerIn: parent
                visible: !art.visible
                text: "\u266b"
                color: Theme.textDim
            }
        }

        Spectrum {
            width: mid.width - artBox.width - vol.width - 16
            height: mid.height
        }
    }

    // Transport to the LEFT of the seekbar, on one line — the controls used to
    // sit on their own row under it, which cost a row for five buttons.
    //
    // Widths are tight at the narrow end of the panel's range (14% of screen),
    // so the buttons are compact and the total duration is dropped below
    // ~300px of inner width rather than squeezing the seekbar to nothing.
    Row {
        id: bottom
        anchors { bottom: queueBox.top; bottomMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 22
        spacing: 6

        readonly property real timeW: root.inner >= 300 ? 76 : 34

        Row {
            id: transport
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5

            MediaButton {
                kind: "shuffle"
                active: Media.hasPlayer && Media.player.shuffleSupported
                toggled: Media.hasPlayer && Media.player.shuffle
                onClicked: Media.player.shuffle = !Media.player.shuffle
            }
            MediaButton {
                kind: "prev"
                active: Media.hasPlayer && Media.player.canGoPrevious
                onClicked: Media.player.previous()
            }
            MediaButton {
                kind: Media.playing ? "pause" : "play"
                active: Media.hasPlayer && (Media.player.canPlay || Media.player.canPause)
                onClicked: Media.player.togglePlaying()
            }
            MediaButton {
                kind: "next"
                active: Media.hasPlayer && Media.player.canGoNext
                onClicked: Media.player.next()
            }
            MediaButton {
                kind: "repeat"
                active: Media.canRepeat
                toggled: Media.repeatMode !== 0
                onClicked: Media.cycleRepeat()
            }
        }

        Item {
            id: seek
            width: bottom.width - transport.width - bottom.timeW - bottom.spacing * 2
            height: parent.height
            anchors.verticalCenter: parent.verticalCenter

            readonly property bool seekable: Media.hasPlayer && Media.player.canSeek
                && Media.player.lengthSupported && Media.player.length > 0
            // driven by the DISPLAY position/length, not the live player's, so
            // the fill holds its place through the MPRIS reconnect instead of
            // collapsing to zero and springing back
            readonly property real frac: Media.dispLen > 0
                ? Math.max(0, Math.min(1, Media.dispPos / Media.dispLen)) : 0

            Rectangle { // track
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 6
                color: Theme.bgAlt
                border.width: 1
                border.color: Theme.border
                Rectangle { // fill
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 1 }
                    width: Math.round((parent.width - 2) * seek.frac)
                    color: Theme.accent
                }
            }

            function seekTo(x) {
                if (!seek.seekable) return;
                Media.player.position = Math.max(0, Math.min(1, x / width)) * Media.player.length;
            }
            MouseArea {
                anchors { fill: parent; topMargin: -4; bottomMargin: -4 }
                enabled: seek.seekable
                cursorShape: seek.seekable ? Qt.PointingHandCursor : Qt.ArrowCursor
                onPressed: (mouse) => seek.seekTo(mouse.x)
                onPositionChanged: (mouse) => { if (pressed) seek.seekTo(mouse.x); }
            }
        }

        PixelText {
            width: bottom.timeW
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            text: root.inner >= 300
                ? Media.fmtTime(Media.dispPos) + "/" + Media.fmtTime(Media.dispLen)
                : Media.fmtTime(Media.dispPos)
            color: Theme.textDim
        }
    }

    // ---- the play queue drawer -------------------------------------------
    // The player app serves its own queue over a socket (Media.queue); this is
    // the part of it you can see and click. It slides DOWN out of the bottom of
    // the widget, and the rows it needs come off the forecast tile below, which
    // condenses to its current-conditions line — see DockGrid's `queueRows` and
    // WeatherContent's `condensed`.
    //
    // The drawer takes the height the grid handed over (everything past the
    // widget's natural size) rather than a fixed pixel count, so it is exactly
    // as tall as the rows it was given and the artwork above it goes back to its
    // natural size instead of being squeezed by a guess. A floor of 60 keeps it
    // usable in the popup copy, which has no extra rows to give.
    readonly property real naturalRest:
        pad * 2 + top.height + 6 + naturalArt + 6 + bottom.height + handle.height
    // EXACTLY the height past the widget's natural size, with NO floor and NO
    // animation of its own. Both were wrong, and together they are why the cover
    // art visibly ballooned before the queue arrived.
    //
    // The artwork row (`mid`) is whatever is left over — root.height minus this
    // drawer and the fixed blocks — so `queueH == height - naturalRest` is the
    // one identity that keeps it at `naturalArt` for EVERY frame of the slide.
    // The tile's own height is already gliding (DockTile's Behavior); a second
    // Behavior here was an animation chasing an animating target, so it retargets
    // every frame and permanently trails. Measured on the open: the tile went
    // 217->270px while queueBox was still stuck at 25px, and the artwork row
    // absorbed the whole difference — 111px, 126, 139, 148, 154, 159, 162, 164 —
    // before snapping back to 60 once the lagging drawer finally landed.
    // The 60px floor did the same thing in the other direction at the start of
    // the motion. It is not needed: the popup copy's implicitHeight already adds
    // a constant 90 for the open state, so there is always something to show.
    // …and it tracks `drawerOut`, not `Media.queueOpen`, which is the same flag
    // held true for one animation on the way DOWN. The flag flips in one frame
    // while the tile takes 200ms to shed its rows, so keying the drawer straight
    // off it collapsed the drawer instantly and handed the artwork the whole
    // 124px the tile had not given back yet — measured 60 -> 162px, then
    // shrinking. Holding it lets the drawer ride the tile down, and all that is
    // left at the end is the tile's resting slack (`qs ipc call live tiles`,
    // 7px here), which the artwork picks up in one imperceptible step.
    //
    // A `Behavior on height` gated `enabled: !Media.queueOpen` was tried first
    // and is NOT reliable: both bindings depend on the same flag, and for the
    // dock copy the height was written before `enabled` had been re-evaluated,
    // so the animation was skipped. Measured, not assumed — the popup copy of
    // the same component animated and the tile did not.
    // A CONSTANT initialiser, seeded in Component.onCompleted. Written as
    // `property bool drawerOut: Media.queueOpen` it is a binding, and a binding
    // that has never been overwritten yet wins the first close outright — so a
    // panel reloaded with the drawer already out would balloon the artwork
    // exactly once, on the next close, and behave from then on.
    property bool drawerOut: false

    // The tile's height above the widget's NATURAL size while the drawer is in.
    // The drawer gives back exactly the rows the grid added and no more, so the
    // artwork row — which is the leftover — is the same size open and closed.
    //
    // Without it the drawer took everything above `naturalRest`, including the
    // slack the tile already had (`qs ipc call live tiles` reports it: 7px
    // here, and a whole row on a taller grid). That slack belongs to the
    // artwork when the drawer is in, so the cover measured 65x65 closed and
    // 60x60 open — and because `artBox.width` follows `mid.height`, the cover
    // changed in BOTH dimensions and the spectrum's left edge moved with it.
    // The entire top of the widget visibly reflowed around a queue that is
    // supposed to open underneath it.
    //
    // It is sampled, not derived, because it is only knowable while the drawer
    // is in — and the sample has to be taken on `drawerOut` as well as on
    // height, since the tile has finished gliding by the time the close hold
    // expires and no further height change is coming.
    property real restSlack: 0
    // Both flags, and `Media.queueOpen` is the load-bearing half. On a reload
    // with the drawer already out, the tile is laid out at its OPEN height
    // before this component has decided that the drawer is out — `drawerOut` is
    // seeded from a setting that arrives at the end of the load pass — so a
    // sample taken on `!drawerOut` alone recorded the open slack (measured: 98px
    // instead of 5) and the drawer then computed a height of zero for the rest
    // of the session. `Media.queueOpen` is already true at that point.
    function noteRestSlack() {
        if (!drawerOut && !Media.queueOpen)
            restSlack = Math.max(0, height - naturalRest);
    }
    onHeightChanged: noteRestSlack()
    onDrawerOutChanged: noteRestSlack()

    readonly property real queueH: drawerOut
        ? Math.max(0, root.height - naturalRest - restSlack) : 0

    Timer {
        id: closeHold
        interval: ViewMode.ms(220)
        onTriggered: root.drawerOut = false
    }
    Connections {
        target: Media
        function onQueueOpenChanged() {
            if (Media.queueOpen) { closeHold.stop(); root.drawerOut = true; }
            else closeHold.restart();
        }
    }

    Item {
        id: queueBox
        anchors { bottom: handle.top; left: parent.left; right: parent.right }
        height: root.queueH
        clip: true

        ListView {
            id: queueList
            anchors { fill: parent; leftMargin: root.pad; rightMargin: root.pad }
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: Media.queue
            // Keep the playing track in view as it advances — the drawer is
            // most useful for "what is next", which is the row under it.
            currentIndex: Media.queueIndex
            highlightFollowsCurrentItem: true
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

            delegate: Item {
                id: qrow
                required property var modelData
                required property int index
                width: queueList.width
                height: 16

                readonly property bool isCurrent: index === Media.queueIndex

                Rectangle {
                    anchors.fill: parent
                    color: qrow.isCurrent ? Theme.highlight
                         : (qma.containsMouse ? Theme.bgAlt : "transparent")
                }
                PixelText {
                    id: qnum
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    width: 22
                    // The playing row is marked, not numbered: its number is the
                    // one thing about it you already know.
                    text: qrow.isCurrent ? ">" : (qrow.index + 1)
                    color: qrow.isCurrent ? Theme.accent : Theme.textDim
                }
                PixelText {
                    id: qdur
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    text: Media.fmtTime(qrow.modelData.dur || 0)
                    color: Theme.textDim
                }
                PixelText {
                    id: qartist
                    anchors { right: qdur.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    width: Math.min(implicitWidth, parent.width / 3)
                    horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                    text: qrow.modelData.artist || ""
                    color: Theme.textDim
                }
                PixelText {
                    anchors {
                        left: qnum.right; right: qartist.left; rightMargin: 8
                        verticalCenter: parent.verticalCenter
                    }
                    elide: Text.ElideRight
                    text: qrow.modelData.title || ""
                    color: qrow.isCurrent ? Theme.accent : Theme.text
                }
                MouseArea {
                    id: qma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // Click a row to play it. GOTO goes back down the same
                    // socket the queue arrived on; the player answers with a new
                    // snapshot, so the highlight moves because the PLAYER moved,
                    // never because the panel assumed it would.
                    onClicked: Media.playIndex(qrow.index)
                }
            }
        }

        PixelText {
            anchors.centerIn: parent
            visible: Media.queue.length === 0
            text: Media.queueAvailable ? "queue is empty" : "player not running"
            color: Theme.textDim
        }
    }

    // ---- the handle: the widget's bottom edge -----------------------------
    // A strip across the very bottom that lights up under the pointer and says
    // which way it will go. It is the affordance AND the close button: with the
    // drawer open it is the bottom edge of the drawer, which is where the user
    // reaches for it.
    Item {
        id: handle
        anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
        height: 11

        Rectangle {
            anchors.fill: parent
            color: hma.containsMouse ? Theme.bgAlt : "transparent"
            // A hairline that only appears on hover: the widget already has a
            // tile border, and a second permanent line across the bottom would
            // read as a division rather than a control.
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1
                color: Theme.border
                visible: hma.containsMouse || Media.queueOpen
            }
        }
        PixelText {
            anchors.centerIn: parent
            // "v" opens (it comes down), "^" closes. Dim until hovered, so the
            // strip is a hint rather than a permanent chevron.
            text: Media.queueOpen ? "^" : "v"
            color: hma.containsMouse ? Theme.accent : Theme.textDim
            opacity: hma.containsMouse || Media.queueOpen ? 1 : 0.55
        }
        MouseArea {
            id: hma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: Media.setQueueOpen(!Media.queueOpen)
        }
        Tooltip {
            target: handle
            show: hma.containsMouse
            text: Media.queueOpen ? "hide the queue" : "show the play queue"
        }
    }
}

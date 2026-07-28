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
        // Graduation lines. A bar chart with no rules is just motion; these give
        // the eye something fixed to read a level against. No labels, by
        // request — so they carry no numbers, but they are still placed where
        // the DATA falls rather than at even pixel divisions: the bars are drawn
        // through `gamma`, so 25/50/75 of cava's 0-100 scale lands at 47/68/86%
        // of the height. A peak marker resting on a rule therefore means exactly
        // that fraction of full scale; even pixel thirds would be rules that
        // measure nothing.
        //
        // Those three are also where the bars actually live — measured medians
        // 15 (-> 35% of height) and p90 49 (-> 68%) — so the grid brackets the
        // working range instead of hiding beneath it. A rule below ~40% would
        // spend almost all its time buried under a bar.
        //
        // BEHIND the bars (declared first, so the bars paint over them), in
        // Theme.border — the hairline the volume column and the tile frames are
        // already drawn with, so the widget gains a grid without gaining a
        // colour.
        Repeater {
            model: [25, 50, 75]
            Rectangle {
                required property int modelData
                anchors { left: parent.left; right: parent.right }
                height: 1
                y: Math.round(spec.height * (1 - Math.pow(modelData / 100, spec.gamma)))
                color: Theme.border
                // Nothing true to draw in a spectrum with no room; also keeps
                // the rules out of a degenerate layout pass.
                visible: spec.height > 8
            }
        }

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

    // Layout: the artwork/spectrum row starts at the widget's TOP edge, the
    // seekbar + transport are pinned to the bottom, and that middle row takes
    // EVERYTHING in between. So the widget has no dead space at either end
    // whatever height the grid gives it — and a bigger tile buys a bigger cover
    // and a taller spectrum rather than emptiness.
    //
    // The track line used to be a full-width row ABOVE all of this, which left
    // the cover art and the volume column starting 22px down from the top edge
    // for the sake of a label that only ever described the track. It now lives
    // inside the spectrum's own column (`specCol`), where it labels the one
    // thing it is next to, and the 22px it cost went to the artwork — which is
    // why this constant is 82 (60 + the 16px line + its 6px gap) rather than 60.
    // Keeping the sum identical is deliberate: `implicitHeight` and
    // `naturalRest` are unchanged, so the popup's height, the tile's reported
    // `wants` and the queue drawer's arithmetic all stay exactly where they were.
    readonly property int naturalArt: 82

    // The drawer's own padding, above the first queue row AND below the last.
    // Before it there was 10px above the drawer and nothing below: the last
    // row's bottom edge WAS the handle's top edge, measured gap=0, which is why
    // the toggle was reported as untouchable without hitting the last track.
    //
    // Half of it is paid for by the gap it replaces (10 above became 6 above and
    // 6 below), but only half — the separation does cost queue: measured, the
    // list went from 98px to 87px, so the drawer shows ~5.5 rows where it showed
    // ~6.1. That is the honest price of the margin and it is taken from the
    // drawer's own padding, NOT from `DockGrid`'s row allocation, which is
    // already down to three rows to guarantee the forecast its miniature graph.
    // Do not buy it back by shrinking the artwork: that block is size-invariant
    // by request (see `restSlack`).
    readonly property int drawerPad: 6

    implicitWidth: 300
    // The open drawer's 90 is a CONSTANT, not `queueH`: queueH is derived from
    // the item's height, and feeding it back into implicitHeight — which is what
    // the popup takes its height FROM — is a binding loop.
    implicitHeight: pad + drawerPad + naturalArt + 6 + bottom.height
                    + handle.height + (Media.queueOpen ? 90 : 0)

    // artwork + spectrum, from the widget's top edge down to the transport row
    Row {
        id: mid
        anchors {
            top: parent.top; topMargin: root.pad
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
                // Notch-based on purpose (a discrete control), but a notch is a
                // fixed amount of scroll rather than one event — see
                // WheelNotch.qml.
                WheelNotch { id: notch }
                onWheel: (wheel) => {
                    const n = notch.steps(wheel);
                    if (n !== 0) SysInfo.adjustVolume(n * SettingsStore.d.volumeStep);
                }
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

        // The spectrum, with the track line as its heading. The line is scoped
        // to this column rather than spanning the widget so the cover and the
        // volume bar reach the top edge; the spectrum is the one thing here with
        // nothing of its own to say, so it is the one that gets the label.
        Item {
            id: specCol
            width: mid.width - artBox.width - vol.width - 16
            height: mid.height

            // ONE line: track on the left, artist on the right. It keeps its
            // height when both are empty, so the spectrum below it does not move
            // when playback stops — which is the whole reason the strings are
            // empty rather than a "nothing playing" placeholder (see
            // Media.dispTitle).
            Item {
                id: trackLine
                anchors { top: parent.top; left: parent.left; right: parent.right }
                height: 16

                // Both elide, and in this column they nearly always will —
                // it is roughly half the width the line used to have. That is
                // safe with the pixel font: Qt drops to three ASCII periods on
                // its own when the family has no U+2026 (measured offscreen —
                // `TextMetrics.elidedText` came back "…tr..." with 0x2e 0x2e
                // 0x2e, pixel-identical to a hand-written "..."), so there is
                // no fallback-font ascent drop and nothing to hand-roll here.
                PixelText {
                    id: trackTitle
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    // Give the artist at most a third, and only what it actually
                    // needs, so a long title uses the rest instead of eliding
                    // against a gap.
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

            Spectrum {
                anchors {
                    top: trackLine.bottom; topMargin: 4
                    left: parent.left; right: parent.right; bottom: parent.bottom
                }
            }
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
        anchors { bottom: queueBox.top; bottomMargin: root.drawerPad; horizontalCenter: parent.horizontalCenter }
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
    // pad above the artwork row, drawerPad below the transport row — the two
    // vertical margins the layout below actually uses. It must stay EXACTLY the
    // non-drawer height or the artwork stops being size-invariant.
    readonly property real naturalRest:
        pad + drawerPad + naturalArt + 6 + bottom.height + handle.height
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

        KineticListView {
            id: queueList
            anchors {
                fill: parent
                leftMargin: root.pad; rightMargin: root.pad
                // Clamped, so a closed drawer (height 0) does not hand the
                // list a NEGATIVE height on its way down.
                bottomMargin: Math.min(root.drawerPad, queueBox.height)
            }
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
        height: 14

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
            id: chevron
            // ONE glyph, flipped — never "^" for the open state. More Perfect
            // DOS VGA has no arrow or triangle at all (checked against the
            // cmap: U+2191/2193, U+25B2/25BC/25B4/25BE are all absent), so the
            // pair has to come out of ASCII, and "^" is not "v" upside down in
            // this font: measured from the glyf table, "v" is 1792 units tall
            // sitting on the baseline while "^" is 1024 units hard against the
            // ascender. Rendered into this 14px strip that put the caret's ink
            // on rows 0-2 — on top of the hover hairline and effectively
            // outside the button — against rows 4-10 for the "v". So the open
            // state is the SAME "v", mirrored about its own centre: identical
            // shape, identical band, and it reads as one control.
            //
            // The flip is vertical only and the item's y is ROUNDED, which is
            // what keeps NativeRendering crisp: an integer origin maps pixel
            // centres onto pixel centres, so the mirrored glyph rasterises to
            // pure Theme colour with no antialiased edge (verified offscreen —
            // rows 4-10, one shade). The rounding also drops a stray pixel the
            // old `anchors.centerIn` produced from its half-pixel y (15px of
            // line in a 14px strip).
            text: "v"
            x: Math.round((parent.width - implicitWidth) / 2)
            y: Math.round((parent.height - implicitHeight) / 2)
            transform: Scale {
                yScale: Media.queueOpen ? -1 : 1
                origin.y: chevron.implicitHeight / 2
            }
            // Dim until hovered, so the strip is a hint rather than a permanent
            // chevron.
            color: hma.containsMouse ? Theme.accent : Theme.textDim
            opacity: hma.containsMouse || Media.queueOpen ? 1 : 0.55
        }
        MouseArea {
            id: hma
            // The TARGET is bigger than the strip. Growing the drawn chrome
            // instead would cost a queue row for every pixel and put a heavier
            // line across the bottom of the widget; a negative margin costs
            // nothing at all.
            //
            // `drawerPad - 1`, not `drawerPad`: the extension has to stop one
            // pixel SHORT of the gap it grows into, or it starts swallowing
            // clicks meant for something else. Open, the pixel keeps it clear of
            // the last queue row's own MouseArea (which fills its 16px row and
            // plays that track). Closed there is no drawer, so it grows into the
            // gap under the transport row instead — where the 24px buttons
            // overhang their 22px row by a pixel at each end.
            anchors.fill: parent
            anchors.topMargin: -(root.drawerPad - 1)
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

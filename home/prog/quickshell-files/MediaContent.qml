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

    implicitWidth: 300
    implicitHeight: pad * 2 + col.implicitHeight

    onActiveChanged: Media.watch(root, active)
    Component.onCompleted: Media.watch(root, active)
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

        width: 26
        height: 26
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

    Column {
        id: col
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 6

        // header: the source app, or a generic label when nothing's playing
        PixelText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: Media.dispIdentity
            color: Theme.accent
        }

        // track title / artist
        PixelText {
            width: parent.width
            elide: Text.ElideRight
            text: Media.dispTitle
            color: Theme.text
        }
        PixelText {
            width: parent.width
            elide: Text.ElideRight
            visible: Media.dispArtist !== ""
            text: Media.dispArtist
            color: Theme.textDim
        }

        // artwork + spectrum
        Row {
            width: parent.width
            height: 60
            spacing: 8

            Item {
                width: 60
                height: 60
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
                    sourceSize.width: 120
                    sourceSize.height: 120
                    visible: status === Image.Ready
                }
                // CP437 note glyph placeholder when there's no cover art
                PixelText {
                    anchors.centerIn: parent
                    visible: !art.visible
                    text: "♫"
                    color: Theme.textDim
                }
            }

            Spectrum {
                width: parent.width - 68
                height: 60
            }
        }

        // seekbar: elapsed | draggable track | total
        Row {
            width: parent.width
            height: 14
            spacing: 6

            PixelText {
                width: 36
                anchors.verticalCenter: parent.verticalCenter
                horizontalAlignment: Text.AlignLeft
                text: Media.fmtTime(Media.dispPos)
                color: Theme.textDim
            }

            Item {
                id: seek
                width: parent.width - 84
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
                width: 36
                anchors.verticalCenter: parent.verticalCenter
                horizontalAlignment: Text.AlignRight
                text: Media.fmtTime(Media.dispLen)
                color: Theme.textDim
            }
        }

        // transport controls
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 12
            topPadding: 2

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
    }
}

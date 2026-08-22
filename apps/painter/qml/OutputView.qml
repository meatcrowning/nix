import QtQuick
import QtMultimedia
import "../../qmlcommon"

// ONE OUTPUT, filling the pane — the "View" half of Gwenview's Browse ↔ View.
//
// The grid answers "what have I made"; this answers "what does THIS one look
// like", which a 220px thumbnail cannot. Return or a double-click enters it,
// Escape leaves, Alt+Left/Right (and PgUp/PgDown in here) walk the gallery, and
// the zoom rows in the View menu drive `zoomIn/Out/Fit/Actual` below.
//
// Zoom is a STILL's affordance. A clip plays fitted and its zoom rows are
// disabled rather than present and inert (docs/DESIGN.md §10) — a VideoOutput
// has no natural size to zoom against until the first frame decodes, and a
// control that works only sometimes is worse than one that is not offered.
Item {
    id: view

    property string source: ""
    property bool isVideo: false

    // 0 = fit the pane; anything else is a literal scale, 1 being actual size.
    property real zoom: 0
    readonly property bool fitting: view.zoom <= 0
    readonly property bool canZoom: !view.isVideo && view.natW > 0

    readonly property real natW: img.implicitWidth
    readonly property real natH: img.implicitHeight
    // Fit NEVER upscales: a 512px output blown up to fill a 1400px pane is a
    // blurry lie about what was generated.
    readonly property real fitScale: (natW > 0 && natH > 0)
        ? Math.min(flick.width / natW, flick.height / natH, 1) : 1
    readonly property real scaleNow: view.fitting ? view.fitScale : view.zoom
    readonly property real imgW: view.natW * view.scaleNow
    readonly property real imgH: view.natH * view.scaleNow

    signal menuRequested(real sx, real sy, var items)

    // BEFORE AND AFTER, for an edit output. The same slider viewer opens on a
    // double-click (qmlcommon/CompareView.qml, shared with it), on by default
    // and switched from the toolbar's `compare` button. An output with no
    // recorded source — anything that is not an edit — has nothing to compare
    // and shows normally.
    property bool compare: true
    readonly property string beforePath:
        (view.source === "" || view.isVideo) ? "" : App.compareSource(view.source)
    readonly property bool comparing: view.compare && view.beforePath !== ""

    function setZoom(z) { view.zoom = Math.max(0.05, Math.min(16, z)) }
    function zoomIn() { view.setZoom((view.fitting ? view.fitScale : view.zoom) * 1.25) }
    function zoomOut() { view.setZoom((view.fitting ? view.fitScale : view.zoom) / 1.25) }
    function zoomFit() { view.zoom = 0 }
    function zoomActual() { view.setZoom(1) }

    // A different picture starts fitted: carrying a 4x zoom onto the next
    // output lands you somewhere in its top-left corner with no idea why.
    onSourceChanged: view.zoom = 0

    CompareView {
        anchors.fill: parent
        visible: view.comparing
        beforePath: view.beforePath
        afterPath: view.source
    }

    KineticFlickable {
        id: flick
        anchors.fill: parent
        visible: !view.comparing
        clip: true
        // THE WHEEL ZOOMS HERE, it does not scroll: this is an image viewer,
        // and that is what a wheel means in one. The flickable's own wheel
        // overlay stands down and the handler below takes every notch.
        wheelEnabled: false
        contentWidth: Math.max(flick.width, view.imgW)
        contentHeight: Math.max(flick.height, view.imgH)

        Item {
            width: flick.contentWidth
            height: flick.contentHeight

            Image {
                id: img
                anchors.centerIn: parent
                width: view.imgW
                height: view.imgH
                visible: !view.isVideo && view.source !== ""
                source: (!view.isVideo && view.source !== "") ? "file://" + view.source : ""
                // sourceSize unset on purpose: implicitWidth/Height must be the
                // file's real pixels, which is what every number above is in.
                cache: false
                asynchronous: true
                smooth: true
                // Nearest-neighbour past 2x, because past 2x he is looking at
                // the pixels and smoothing is exactly what hides them.
                mipmap: view.scaleNow < 1
            }

            AudioOutput { id: silent; muted: true }
            MediaPlayer {
                id: player
                source: (view.isVideo && view.source !== "") ? "file://" + view.source : ""
                videoOutput: videoOut
                audioOutput: silent
                loops: MediaPlayer.Infinite
                onSourceChanged: if (source != "") play()
            }
            VideoOutput {
                id: videoOut
                anchors.fill: parent
                visible: view.isVideo && view.source !== ""
                fillMode: VideoOutput.PreserveAspectFit

                // Click to pause and play, the same as the preview pane's.
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: player.playbackState === MediaPlayer.PlayingState
                               ? player.pause() : player.play()
                }
            }

            // WHEEL ZOOMS, LEFT BUTTON PANS. Zoom is a discrete step, so it
            // goes through the notch accumulator and not the pixel path
            // (docs/DESIGN.md §9.2); the pan writes contentX/contentY straight
            // from the pointer, 1:1, because it is direct manipulation (§6.4).
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: panning ? Qt.ClosedHandCursor
                           : (flick.contentWidth > flick.width
                              || flick.contentHeight > flick.height)
                             ? Qt.OpenHandCursor : Qt.ArrowCursor
                property bool panning: false
                property real lastX: 0
                property real lastY: 0
                WheelNotch { id: notch }
                onWheel: function (w) {
                    if (!view.canZoom) { w.accepted = false; return }
                    var n = notch.steps(w)
                    for (var i = 0; i < Math.abs(n); i++) {
                        if (n > 0) view.zoomIn(); else view.zoomOut()
                    }
                }
                onPressed: function (m) {
                    if (m.button !== Qt.LeftButton) return
                    panning = true
                    lastX = m.x
                    lastY = m.y
                }
                onReleased: panning = false
                onCanceled: panning = false
                onPositionChanged: function (m) {
                    if (!panning) return
                    flick.contentX = Math.max(0, Math.min(
                        flick.contentWidth - flick.width, flick.contentX - (m.x - lastX)))
                    flick.contentY = Math.max(0, Math.min(
                        flick.contentHeight - flick.height, flick.contentY - (m.y - lastY)))
                }
                onClicked: function (m) {
                    if (m.button !== Qt.RightButton) return
                    var pt = mapToItem(null, m.x, m.y)
                    view.menuRequested(pt.x, pt.y, [
                        { label: "open in viewer",
                          trigger: () => App.openExternally(view.source) },
                        { label: "fit", trigger: () => view.zoomFit() },
                        { label: "actual size", trigger: () => view.zoomActual() }
                    ])
                }
            }
        }
    }

    // What you are looking at and how big, bottom-left over a scrim — the same
    // corner and the same scrim PreviewPane uses for the same job.
    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 1
        width: tag.implicitWidth + 12
        height: 18
        color: Theme.bg
        opacity: 0.85
        visible: view.source !== ""
        PixelText {
            id: tag
            anchors.centerIn: parent
            text: view.isVideo ? "clip"
                : view.natW > 0
                  ? (view.natW + "x" + view.natH + "  "
                     + Math.round(view.scaleNow * 100) + "%")
                  : "loading"
            color: Theme.textDim
        }
    }

    PixelText {
        anchors.centerIn: parent
        visible: view.source === ""
        text: "nothing selected"
        color: Theme.dim
    }
}

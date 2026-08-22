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

    function setZoom(z) { view.zoom = Math.max(0.05, Math.min(16, z)) }
    function zoomIn() { view.setZoom((view.fitting ? view.fitScale : view.zoom) * 1.25) }
    function zoomOut() { view.setZoom((view.fitting ? view.fitScale : view.zoom) / 1.25) }
    function zoomFit() { view.zoom = 0 }
    function zoomActual() { view.setZoom(1) }

    // A different picture starts fitted: carrying a 4x zoom onto the next
    // output lands you somewhere in its top-left corner with no idea why.
    onSourceChanged: view.zoom = 0

    KineticFlickable {
        id: flick
        anchors.fill: parent
        clip: true
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

            // Ctrl+wheel zooms; a plain wheel is DECLINED and falls through to
            // the flickable's own scroll overlay behind the content
            // (qmlcommon/KineticFlickable.qml explains the z: -1 that makes
            // that ordering work). Zoom is a discrete step, so it goes through
            // the notch accumulator and not the pixel path — docs/DESIGN.md §9.2.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                WheelNotch { id: notch }
                onWheel: function (w) {
                    if (!(w.modifiers & Qt.ControlModifier) || !view.canZoom) {
                        w.accepted = false
                        return
                    }
                    var n = notch.steps(w)
                    for (var i = 0; i < Math.abs(n); i++) {
                        if (n > 0) view.zoomIn(); else view.zoomOut()
                    }
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

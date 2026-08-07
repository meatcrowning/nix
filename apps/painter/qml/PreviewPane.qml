import QtQuick
import QtMultimedia

// THE JOB THAT IS RUNNING, and then what it made.  Off by default, toggled from
// the titlebar ("pv"), and deliberately not a picker:
//
//   [his] "when toggled it should only show the preview frames of the
//          generating image or video and when complete should just show that
//          image or video, no clicking on other outputs or anything"
//
// So it has exactly two states and no controls. While a job runs it shows the
// sampler's own preview frames (the ones ComfyUI pushes down the websocket,
// `App.hasPreview`, fed by main.py's LivePreview image provider). When the job
// lands it shows that output — the newest row in the gallery — and a clip plays
// looped and MUTED, because it is a preview beside a music player, not
// playback. Playback is `viewer`, on a double-click in the grid.
//
// ComfyUI's video preview is a STILL FRAME PER STEP, not a moving clip:
// Latent2RGBPreviewer takes x0[0, :, 0] out of a 5-D latent, i.e. the first
// frame. That is what its own web UI shows too, so a video job previews as a
// single frame that refreshes as it denoises.
Item {
    id: pane

    property bool open: false
    // The height is dragged and remembered, exactly like a prompt box.
    property int paneHeight: Prefs.get("preview.h") > 0 ? Prefs.get("preview.h") : 260
    readonly property int minHeight: 90
    readonly property int maxHeight: 900

    // What the last finished job produced. Nothing else ever sets these — the
    // pane follows the newest output, it is not a way to browse older ones.
    property string source: ""
    property bool sourceIsVideo: false

    function showNewest() {
        if (Gallery.count > 0) {
            pane.source = Gallery.pathAt(0)
            pane.sourceIsVideo = Gallery.isVideoAt(0)
        }
    }

    visible: open
    height: open ? paneHeight : 0

    // A landed job is a new row 0, which is the thing to show.
    Connections {
        target: Gallery
        function onCountChanged() { pane.showNewest() }
    }
    Component.onCompleted: pane.showNewest()

    Rectangle {
        id: frame
        anchors.fill: parent
        anchors.bottomMargin: 6           // the grab strip below
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: 1
        clip: true

        // (1) the live sampler preview
        Image {
            anchors.fill: parent
            anchors.margins: 1
            visible: App.hasPreview
            // A provider image only reloads when the URL CHANGES, so the tick
            // is in it (main.py increments it per frame).
            source: App.hasPreview ? ("image://livepreview/" + App.previewTick) : ""
            fillMode: Image.PreserveAspectFit
            cache: false
            asynchronous: true
        }

        // (2a) the finished still
        Image {
            anchors.fill: parent
            anchors.margins: 1
            visible: !App.hasPreview && pane.source !== "" && !pane.sourceIsVideo
            source: visible ? "file://" + pane.source : ""
            fillMode: Image.PreserveAspectFit
            cache: false
            asynchronous: true
        }

        // (2b) the finished clip — looped, and muted on purpose (see above)
        AudioOutput { id: silent; muted: true }
        MediaPlayer {
            id: player
            source: (!App.hasPreview && pane.source !== "" && pane.sourceIsVideo)
                    ? "file://" + pane.source : ""
            videoOutput: videoOut
            audioOutput: silent
            loops: MediaPlayer.Infinite
            onSourceChanged: if (source != "") play()
        }
        VideoOutput {
            id: videoOut
            anchors.fill: parent
            anchors.margins: 1
            visible: !App.hasPreview && pane.source !== "" && pane.sourceIsVideo
            fillMode: VideoOutput.PreserveAspectFit
        }

        // Nothing to show is a STATE, not a blank box: it says which of the two
        // is missing rather than looking broken.
        PixelText {
            anchors.centerIn: parent
            width: parent.width - 16
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            visible: !App.hasPreview && pane.source === ""
            // BE HONEST ABOUT THE LIKELY REASON. A backend started before the
            // --preview-method flag existed sends nothing at all, and "waiting"
            // would be a lie that never resolves. A first step can genuinely
            // take half a minute on a video model, so the hint waits for the
            // clock rather than firing immediately.
            text: !App.busy ? "nothing generated yet"
                : App.elapsed > 45
                  ? "no preview frames - if the backend has been up a while, restart it from settings so --preview-method takes effect"
                  : "waiting for the first preview frame"
            color: Theme.dim
        }

        // What it is showing, bottom-left, over a scrim. Live frames say so:
        // an in-progress sample looks like a finished one that went wrong.
        Rectangle {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.margins: 1
            width: tag.implicitWidth + 12
            height: 18
            color: Theme.bg
            opacity: 0.85
            visible: App.hasPreview || pane.source !== ""
            PixelText {
                id: tag
                anchors.centerIn: parent
                // A VIDEO JOB PREVIEWS AS ONE FRAME, and the label says which,
                // because a still that never moves while a clip is being made
                // looks like a preview that has frozen. It has not: ComfyUI's
                // Latent2RGB previewer slices `x0[0, :, 0]` out of a 5-D latent
                // — the first frame — and hands back ONE image per step, so
                // that frame is all any client can be shown (its own web UI
                // included). What refreshes is the denoising of frame 1.
                text: App.hasPreview
                      ? (App.isVideo ? "sampling - frame 1 of the clip" : "sampling")
                      : (pane.sourceIsVideo ? "clip" : "still")
                color: App.hasPreview ? Theme.accent : Theme.textDim
            }
        }
    }

    // The grab strip, same shape and same rules as a prompt box's: drawn 5px,
    // ±3px of grab across it, written to Prefs on release rather than on every
    // pixel of the drag.
    Rectangle {
        id: grip
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 5
        color: grab.pressed || grab.containsMouse ? Theme.accent : "transparent"

        Row {
            anchors.centerIn: parent
            spacing: 3
            Repeater {
                model: 3
                Rectangle {
                    width: 3
                    height: 1
                    color: grab.pressed || grab.containsMouse ? Theme.bg : Theme.dim
                }
            }
        }

        MouseArea {
            id: grab
            anchors.fill: parent
            anchors.topMargin: -3
            anchors.bottomMargin: -3
            hoverEnabled: true
            cursorShape: Qt.SizeVerCursor
            preventStealing: true
            property real startY: 0
            property int startH: 0
            onPressed: function (m) {
                startY = mapToItem(null, m.x, m.y).y
                startH = pane.paneHeight
            }
            onPositionChanged: function (m) {
                if (!pressed) return
                var dy = mapToItem(null, m.x, m.y).y - startY
                pane.paneHeight = Math.max(pane.minHeight,
                                           Math.min(pane.maxHeight, Math.round(startH + dy)))
            }
            onReleased: Prefs.set("preview.h", pane.paneHeight)
        }
    }
}

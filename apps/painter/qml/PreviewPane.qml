import QtQuick
import QtMultimedia

// A viewport above the history: what is being made right now, or an output you
// picked out of the grid.  Off by default and toggled from the titlebar ("pv"),
// because a 400px preview is worth the room while you are iterating and dead
// weight while you are reading the list.
//
// Two sources, in this order:
//
//   1. THE SAMPLER'S OWN PREVIEW, while a job runs — the frames ComfyUI pushes
//      down the websocket (`App.hasPreview`, fed by main.py's LivePreview image
//      provider). The backend only sends them with `--preview-method` set, which
//      home/prog/painter.nix does; with it off nothing arrives and this falls
//      through to (2) rather than showing an empty box.
//   2. THE PICKED OUTPUT — right-click an output and choose `preview`, or the
//      newest one otherwise. A video plays here looped and MUTED: it is a
//      thumbnail that moves, next to a music player he is probably listening
//      to. Sound is what `viewer` is for (left-click).
Item {
    id: pane

    property bool open: false
    // The height is dragged and remembered, exactly like a prompt box.
    property int paneHeight: Prefs.get("preview.h") > 0 ? Prefs.get("preview.h") : 260
    readonly property int minHeight: 90
    readonly property int maxHeight: 900

    property string source: ""
    property bool sourceIsVideo: false

    function show(path, isVideo) {
        pane.source = path
        pane.sourceIsVideo = isVideo === true
    }

    visible: open
    height: open ? paneHeight : 0

    // The newest output, until something is picked by hand. `Gallery.count`
    // changing is the signal a job landed; the row it added is row 0.
    Connections {
        target: Gallery
        function onCountChanged() {
            if (Gallery.count > 0 && pane.source === "")
                pane.show(Gallery.pathAt(0), Gallery.isVideoAt(0))
        }
    }
    Component.onCompleted: if (Gallery.count > 0)
        pane.show(Gallery.pathAt(0), Gallery.isVideoAt(0))

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

        // (2a) a picked still
        Image {
            anchors.fill: parent
            anchors.margins: 1
            visible: !App.hasPreview && pane.source !== "" && !pane.sourceIsVideo
            source: visible ? "file://" + pane.source : ""
            fillMode: Image.PreserveAspectFit
            cache: false
            asynchronous: true
        }

        // (2b) a picked clip — looped, and muted on purpose (see above)
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
            text: App.busy ? "waiting for the first preview frame"
                           : "nothing to preview yet - generate, or right-click an output"
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
                text: App.hasPreview ? "sampling" : (pane.sourceIsVideo ? "clip" : "still")
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

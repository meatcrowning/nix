import QtQuick
import QtMultimedia

// WHATEVER IS SELECTED — which, while a job runs, is the job.
//
// It used to be the running job and nothing else, deliberately: [his] "when
// toggled it should only show the preview frames of the generating image or
// video and when complete should just show that image or video, no clicking on
// other outputs or anything". That is superseded [his, 2026-08-28] — "make it
// so the preview element displays the currently selected output, so the user
// can select what's being shown" — and the way it keeps BOTH is his too: the
// generation in flight takes a row in the history (main.py `Gallery.begin_live`)
// and is replaced there by the output it produced, so "the job" and "an older
// output" are the same kind of thing to select, and going back to the running
// job is a click on its tile rather than a mode.
//
// So: the selected row, or the newest output when nothing is selected. The
// selected row being the RUNNING one is what draws the sampler's own preview
// frames (`App.hasPreview`, fed by main.py's LivePreview image provider). A
// clip plays looped and MUTED, because it is a preview beside a music player,
// not playback. Playback is `viewer`, on a double-click in the grid.
//
// ComfyUI's video preview is a STILL FRAME PER STEP, not a moving clip:
// Latent2RGBPreviewer takes x0[0, :, 0] out of a 5-D latent, i.e. the first
// frame. That is what its own web UI shows too, so a video job previews as a
// single frame that refreshes as it denoises.
Item {
    id: pane

    property bool open: false
    //: A finished result, double-clicked: open it in the single-output view.
    //: Only when this pane is showing an OUTPUT — a live sampler frame is not
    //: a file and there is nothing to open.
    signal openRequested(string path)
    // The height is dragged and remembered, exactly like a prompt box.
    property int paneHeight: Prefs.get("preview.h") > 0 ? Prefs.get("preview.h") : 260
    readonly property int minHeight: 90
    readonly property int maxHeight: 900

    //: What the results pane says is selected — one output, the running job's
    //: row, or "" for none and a multiple selection alike (there is no single
    //: thing to show for a set).
    property string selPath: ""
    //: Whether that selection IS the running job. Not a binding: `Gallery.isLive`
    //: is a call, not a notifying property, so a binding over it would answer
    //: with whatever it last evaluated — and it is read from `refresh()`, which
    //: runs in the `selPath` change handler, i.e. one step BEFORE any binding on
    //: `selPath` has re-run. It is set where it is decided instead.
    property bool selLive: false
    //: The sampler's frames, rather than a file: the running job is what is
    //: selected, or nothing is and one is running.
    //:
    //: THE LAST FRAME STAYS UNTIL THE FILE LANDS. `App.hasPreview` goes false
    //: the moment the job reports finished, which is a beat BEFORE its output
    //: has been downloaded and added — and this pane blanking (or falling back
    //: to the previous output) for that beat is the flash he saw [his,
    //: 2026-08-28]. So a selected LIVE row keeps drawing its last frame for as
    //: long as the row exists; `_on_started` zeroes the tick, so a new job
    //: never shows the old one's.
    //: THE HANDOVER. Between "the job finished" and "its file is decoded" there
    //: is a gap, and an `Image` whose source has just changed still holds the
    //: LAST picture it loaded — the previous generation. Made visible in that
    //: gap it flashes it [his, 2026-08-28, twice]. So the sampler's last frame
    //: is held until the new file is actually ready to draw.
    property bool handover: false
    //: ...and WHICH file it is waiting for, so the selection landing on that
    //: file does not read as "he picked something else" and cancel it (the two
    //: happen in the same signal, in whichever order the connections were made).
    property string handoverPath: ""
    readonly property bool showLive: App.previewTick > 0
                                     && (pane.selLive || pane.handover
                                         || (pane.selPath === "" && App.hasPreview))

    // The file being drawn, derived from the selection — never written from
    // anywhere else.
    property string source: ""
    property bool sourceIsVideo: false

    function refresh() {
        pane.selLive = pane.selPath !== "" && Gallery.isLive(pane.selPath)
        if (pane.selLive) { pane.source = ""; pane.sourceIsVideo = false; return }
        var p = pane.selPath
        // THE SENTINEL IS NOT A FILE. The selection can still name the running
        // job's row for an instant after that row has gone (it is a path like
        // any other to the view), and handing `live://generating` to an Image
        // is a broken source that draws whatever the Image last held.
        if (p !== "" && Gallery.indexOf(p) < 0 && p.indexOf("live:") === 0) p = ""
        if (p === "") {
            // Nothing picked: the newest OUTPUT, which is row 0 unless a job is
            // sampling in it.
            for (var i = 0; i < Gallery.count; i++) {
                if (!Gallery.isLiveAt(i)) { p = Gallery.pathAt(i); break }
            }
        }
        pane.source = p
        pane.sourceIsVideo = p === "" ? false
                                      : Gallery.isVideoAt(Gallery.indexOf(p))
    }
    onSelPathChanged: {
        // A DELIBERATE PICK ENDS THE HANDOVER: he asked for that output, so the
        // job's last frame has no claim on the pane any more.
        if (pane.selPath !== pane.handoverPath && !Gallery.isLive(pane.selPath))
            pane.handover = false
        pane.refresh()
    }

    visible: open
    height: open ? paneHeight : 0

    // A row landing or going changes what "the newest output" is, and can also
    // be the file this pane is drawing being deleted.
    Connections {
        target: Gallery
        function onCountChanged() { pane.refresh() }
        function onLiveChanged() { pane.refresh() }
        //: The job's row became its file: hold the last frame until that file
        //: can actually be drawn (see `handover`).
        function onLiveReplaced(path) {
            pane.handoverPath = "" + path
            pane.handover = true
            handoverGuard.restart()
        }
    }

    //: ...and never for longer than it takes to decode one output. A file that
    //: fails to load, or a clip that never starts, must not leave the pane on a
    //: frame from a job that finished.
    Timer {
        id: handoverGuard
        interval: 4000
        onTriggered: { pane.handover = false; pane.handoverPath = "" }
    }
    Component.onCompleted: pane.refresh()

    Rectangle {
        id: frame
        anchors.fill: parent
        anchors.bottomMargin: 6           // the grab strip below
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: Theme.ctrlBorder
        clip: true

        // (1) the live sampler preview
        Image {
            anchors.fill: parent
            anchors.margins: 1
            visible: pane.showLive
            // A provider image only reloads when the URL CHANGES, so the tick
            // is in it (main.py increments it per frame).
            source: (pane.open && pane.showLive)
                    ? ("image://livepreview/" + App.previewTick) : ""
            fillMode: Image.PreserveAspectFit
            cache: false
            asynchronous: true
        }

        // (2a) the finished still
        Image {
            id: finishedStill
            anchors.fill: parent
            anchors.margins: 1
            visible: !pane.showLive && pane.source !== "" && !pane.sourceIsVideo
            // LOADING IS NOT DRAWING. The pane being shut means the file is not
            // decoded at all (see the MediaPlayer below) — but `visible` must
            // NOT be in this condition: during the handover above this item is
            // hidden on purpose while the file loads, and a source bound to
            // `visible` would never start loading, so `status` would never
            // reach Ready and the handover would only ever end on its timeout.
            source: (pane.open && pane.source !== "" && !pane.sourceIsVideo)
                    ? "file://" + pane.source : ""
            fillMode: Image.PreserveAspectFit
            cache: false
            asynchronous: true
            onStatusChanged: if (status === Image.Ready || status === Image.Error) {
                                 pane.handover = false
                                 pane.handoverPath = ""
                             }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                onDoubleClicked: if (pane.source !== "") pane.openRequested(pane.source)
            }
        }

        // (2b) the finished clip — looped, and muted on purpose (see above)
        //
        // `pane.open` is in the source condition, not just in `visible`: a
        // closed pane is height 0 and invisible, but a MediaPlayer with a
        // source is a decoder running a clip on a loop for as long as the app
        // is open, whether or not anything draws it. On book that is a core
        // spent on a pane that is not there.
        AudioOutput { id: silent; muted: true }
        MediaPlayer {
            id: player
            // Same as the still above: not gated on `showLive`, so the clip is
            // already buffering while the last sampler frame is still up.
            source: (pane.open && pane.source !== "" && pane.sourceIsVideo)
                    ? "file://" + pane.source : ""
            videoOutput: videoOut
            audioOutput: silent
            loops: MediaPlayer.Infinite
            onSourceChanged: if (source != "") play()
            onPlaybackStateChanged: if (playbackState === MediaPlayer.PlayingState) {
                                        pane.handover = false
                                        pane.handoverPath = ""
                                    }
        }
        VideoOutput {
            id: videoOut
            anchors.fill: parent
            anchors.margins: 1
            visible: !pane.showLive && pane.source !== "" && pane.sourceIsVideo
            fillMode: VideoOutput.PreserveAspectFit

            // CLICK IT TO STOP IT. A looping clip is the right default for a
            // thing that reports what just finished, and the wrong one when you
            // want to look at a single frame of it.
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: player.playbackState === MediaPlayer.PlayingState
                           ? player.pause() : player.play()
                onDoubleClicked: if (pane.source !== "") pane.openRequested(pane.source)
            }
        }

        // Nothing to show is a STATE, not a blank box: it says which of the two
        // is missing rather than looking broken.
        PixelText {
            anchors.centerIn: parent
            width: parent.width - 16
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            visible: !pane.showLive && pane.source === ""
            // BE HONEST ABOUT THE LIKELY REASON. A backend started before the
            // --preview-method flag existed sends nothing at all, and "waiting"
            // would be a lie that never resolves. A first step can genuinely
            // take half a minute on a video model, so the hint waits for the
            // clock rather than firing immediately.
            text: pane.selLive && !App.busy ? "queued"
                : !App.busy ? "nothing generated yet"
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
            visible: pane.showLive || pane.source !== ""
            PixelText {
                id: tag
                anchors.centerIn: parent
                // WHICH FRAME YOU ARE LOOKING AT. Stock ComfyUI slices a video
                // latent's temporal axis to index 0 and previews frame 1 for
                // the whole sample, on 0.30.0 and on upstream master alike; a
                // LOCAL PATCH to `/home/lam/comfy/latent_preview.py` walks that
                // cursor instead and sends the position in the preview's
                // metadata (apps/painter/AGENTS.md records both halves). With
                // an unpatched backend `previewFrames` is 0 and this says
                // "frame 1", which is what such a backend is showing.
                text: pane.showLive
                      ? (App.previewFrames > 1
                         ? "sampling · frame " + App.previewFrame
                           + " of " + App.previewFrames
                         : (App.isVideo ? "sampling · frame 1" : "sampling"))
                      : (pane.sourceIsVideo ? "clip" : "still")
                color: pane.showLive ? Theme.accent : Theme.textDim
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

import QtQuick
import QtQuick.Controls.Basic
import QtMultimedia
import "../../qmlcommon"

// Results, newest first.  Every image carries the parameters that made it in a
// PNG text chunk, so "reuse" reads them straight back out of the file.
Item {
    id: view

    //: The menu cannot live in here — `CtxMenu` clamps itself into its own root,
    //: and this pane can be 220px wide — so the items travel up to Main.qml,
    //: which owns the one menu, in SCENE coordinates. Same arrangement as
    //: PromptBox's spelling menu.
    signal menuRequested(real sx, real sy, var items)
    //: "Show me this one" — a double-click. The pane above decides what that
    //: means; this view only reports it.
    signal openRequested(string path, bool isVideo)

    // HOW MANY COLUMNS TO LAY OUT: 0 asks for the automatic width-driven count
    // below, 1..6 fixes it. Set from the View menu's `Columns` radio set and
    // remembered there (Root.qml `gridColumns`).
    property int columns: 0

    // ------------------------------------------------------------ selection
    //
    // Click, ctrl-click, shift-click — a file manager's three, because that is
    // what he asked for and what his hands already know ([his] "make it so i
    // can shift / cntrl shift a selection of outputs"). Two rules make it
    // behave rather than merely work:
    //
    //   * IT IS KEPT AS PATHS, not indices. A finished job inserts a row at 0,
    //     which would renumber a set of indices under him mid-selection.
    //   * A PRESS INSIDE AN EXISTING MULTI-SELECTION DOES NOT COLLAPSE IT —
    //     the drag that may follow has to carry the whole set, so that click is
    //     deferred to the release and applied only if no drag happened. Same
    //     rule as filer's rows (docs/DESIGN.md §13).
    property var selection: []
    property string anchorPath: ""

    // FOLLOWING THE JOB. The preview viewport shows what is SELECTED, and the
    // running job is a row like any other (`Gallery.begin_live`), so "show me
    // the generation" and "show me that output" are the same gesture. This is
    // the one piece of state that keeps: while it is true the selection moves
    // onto each job as it starts and onto the file it produced when it lands,
    // which is the behaviour the pane had when it could show nothing else.
    // Clicking any other output turns it off; clicking the running job turns it
    // back on [his, 2026-08-28].
    property bool followLive: true

    function isSelected(p) { return view.selection.indexOf(p) >= 0 }

    function setSelection(paths) {
        view.selection = paths
        // Warm the collage for what a drag would now carry: it is a few hundred
        // ms of decoding and half a dozen encodes, and at the press there is no
        // time for either (App.dragUriListFor).
        App.prepareCollage(paths)
    }

    function selectSingle(p) {
        // A DELIBERATE pick decides whether the pane keeps following the job.
        view.followLive = Gallery.isLive(p)
        view.anchorPath = p
        view.setSelection([p])
    }

    //: The automatic move — onto the job that just started, onto the output it
    //: just produced. It must not touch `followLive`, or landing on a finished
    //: file would stop the batch's next job being followed.
    function followTo(p) {
        if (p === "") return
        view.anchorPath = p
        view.setSelection([p])
    }

    function toggleSelect(p) {
        view.followLive = false
        var s = view.selection.slice()
        var i = s.indexOf(p)
        if (i >= 0) s.splice(i, 1)
        else s.push(p)
        view.anchorPath = p
        view.setSelection(s)
    }

    function extendTo(p) {
        view.followLive = false
        var to = Gallery.indexOf(p)
        var from = view.anchorPath === "" ? to : Gallery.indexOf(view.anchorPath)
        if (to < 0) return
        if (from < 0) from = to
        var lo = Math.min(from, to), hi = Math.max(from, to)
        var s = []
        for (var i = lo; i <= hi; i++) s.push(Gallery.pathAt(i))
        view.setSelection(s)
    }

    function clearSelection() {
        // Nothing selected means the pane is back on "whatever is newest", which
        // is where a job in flight would put it anyway — so this re-arms the
        // follow rather than leaving it stuck on an output that is no longer
        // selected.
        view.followLive = true
        view.anchorPath = ""
        view.setSelection([])
    }

    // What a drag from `p` should carry: the whole selection when p is part of
    // one, otherwise just p — pressing an unselected tile and dragging it must
    // not hand over somebody else's set.
    function dragPathsFor(p) {
        return (view.isSelected(p) && view.selection.length > 1)
               ? view.selection : [p]
    }

    // A row that goes (a file deleted outside painter, a reset) must not stay
    // selected: the collage would be built from a path that is not there.
    // The running job appeared, or the file it made replaced it: move with it
    // while nothing else has been picked.
    Connections {
        target: Gallery
        function onLiveChanged() {
            if (Gallery.livePath === "") return
            // A NEWLY QUEUED BATCH TAKES THE PREVIEW BACK, whatever was being
            // looked at [his, 2026-08-28] — pressing generate is a statement
            // about what you want to watch. The later jobs of that same batch
            // do not (`Gallery.liveGrab` is false for them): four images asked
            // for in one press are one request, and being yanked off an output
            // mid-batch is the thing this whole pane stopped doing.
            if (Gallery.liveGrab) view.followLive = true
            if (view.followLive) view.followTo(Gallery.livePath)
        }
        function onLiveReplaced(path) {
            if (view.followLive) view.followTo(path)
        }
    }

    Connections {
        target: Gallery
        function onCountChanged() {
            if (view.selection.length === 0) return
            var s = []
            for (var i = 0; i < view.selection.length; i++)
                if (Gallery.indexOf(view.selection[i]) >= 0) s.push(view.selection[i])
            if (s.length !== view.selection.length) view.setSelection(s)
        }
    }

    // An output carries the whole job that made it — a still in its PNG chunk, a
    // clip in its MP4 tag — so the useful question
    // is WHICH PART to take: its words, its numbers, or both. That is a choice,
    // and a choice is a menu — it used to be an unlabelled right-click that took
    // everything, with no way to ask for less.
    function menuFor(index, path, isVideo) {
        var p = Gallery.paramsAt(index)
        if (!p) {
            return [{ label: "no parameters stored in this file", enabled: false },
                    { separator: true }].concat(view.commonItems(index, path, isVideo, p))
        }
        return [
            { label: "inject all", trigger: () => { root.injectAll(p); root.view = 0 } },
            { label: "inject prompt", trigger: () => { root.injectPrompt(p); root.view = 0 } },
            { label: "inject params", trigger: () => { root.injectParams(p); root.view = 0 } },
            { separator: true }
        ].concat(view.commonItems(index, path, isVideo, p))
    }

    //: The running job's own menu — one verb, because there is exactly one
    //: thing to do to a job that has not finished. `cancel` is the titlebar's
    //: `x` and stops the whole batch, which is what its label has to say.
    function liveMenu() {
        return [{ label: "cancel generation", trigger: () => App.cancel() }]
    }

    // The items every output gets, parameters or not. The last two are offered
    // only when there is something to offer: the prompt when the file kept one
    // (a clip does too now — its own tag, or the graph SaveVideo wrote), the
    // muted copy on a video, there being nothing to strip off a still. An action
    // with nothing to act on is not offered greyed, it is not offered
    // (docs/DESIGN.md §10).
    function commonItems(index, path, isVideo, params) {
        var items = [{ label: "open in viewer", trigger: () => App.openExternally(path) }]
        if (params && params.positive) {
            items.push({ label: "copy prompt",
                         trigger: () => App.copyPrompt(path) })
        }
        var seed = params ? Number(params.seed) : -1
        if (Number.isFinite(seed) && seed >= 0) {
            items.push({ label: "copy seed",
                         trigger: () => App.copySeed(path) })
        }
        if (isVideo) {
            items.push({ label: "copy muted copy",
                         trigger: () => App.copyMuted(path) })
        }
        return items
    }

    // THE HEADING IS GONE, and with it the only thing between the chrome and
    // the grid. It said "output" and a tally; the tally now lives in the status
    // bar with the other standing facts (Root.qml `statusRight`), and the strip
    // it occupied is what you DRAG THE WINDOW BY (ResultsPane.qml). A word over
    // a grid of pictures was labelling the obvious.
    //
    // A multiple selection still has to report itself, and it does so where the
    // count it qualifies already is — beside it, in the status bar.
    Item { id: head; width: parent.width; height: 0 }

    // Empty space clears the selection, the way it does in a file manager. It
    // sits UNDER the grid, so a click only reaches it where there is no tile.
    MouseArea {
        anchors.fill: grid
        onClicked: view.clearSelection()
    }

    KineticGridView {
        id: grid
        anchors.top: head.bottom
        anchors.topMargin: 8
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        // The room the hint line below needs, and no more.
        anchors.bottomMargin: 22
        clip: true
        model: Gallery
        // The results are the unbounded side, so this is where the desktop's
        // scrollbar belongs (docs/DESIGN.md §9.2); the parameter column gave its
        // gutter back to the controls.
        ScrollBar.vertical: VScroll { id: gscroll }
        // Fit whole columns to the pane, and NEVER a cell wider than the pane:
        // the old 150px floor meant a 140px-wide pane laid out a 150px cell, so
        // the single column was clipped and the grid looked empty — the
        // "outputs don't show when the window is small" bug, once the pane
        // itself stopped being hidden. One column is a legitimate answer.
        // Whole columns in what is left AFTER the bar's gutter — a cell sized to
        // the full width would run under it.
        readonly property real usable: Math.max(1, width - gscroll.barW)
        // A CHOSEN column count is still clamped by what fits: a 220px pane
        // cannot lay out six 60px-floor cells, and honouring the number over
        // the pane is how the grid goes empty again (the bug in the note
        // above). So the floor wins and the count falls back to what fits.
        readonly property int autoCols: Math.max(1, Math.round(usable / 210))
        readonly property int cols: view.columns > 0
            ? Math.max(1, Math.min(view.columns, Math.floor(usable / 60)))
            : autoCols
        cellWidth: Math.max(60, Math.floor(usable / Math.max(1, cols)))
        cellHeight: cellWidth
        // The decode size, in 60px steps rather than tracking `cellWidth`: a
        // sourceSize that moved with every pixel of a window resize would throw
        // away and re-decode every thumbnail on the way. 2x the cell, capped,
        // so a HiDPI screen still has pixels to draw with.
        readonly property int thumbPx:
            Math.min(560, Math.max(120, Math.ceil(cellWidth * 2 / 60) * 60))
        // Keep a screenful of delegates alive either side of the viewport: the
        // churn at the edges is what a scroll actually costs.
        cacheBuffer: Math.max(600, cellHeight * 3)
        // NO ROW-SIZED WHEEL STEP. This was `wheelLines: 1, wheelStep: cellHeight`,
        // i.e. one notch = exactly one row — which reads as the grid SNAPPING
        // an output to the top on every notch instead of scrolling. The default
        // line step is the same one every other view on this desktop uses.

        delegate: Item {
            id: tile
            width: grid.cellWidth
            height: grid.cellHeight

            // A clip with no poster frame yet asks for one once it has been on
            // screen for a moment. Extracting every one up front is a few
            // hundred ffmpeg runs for thumbnails nobody has scrolled to
            // (main.py `requestPoster`) — and asking the INSTANT a delegate is
            // built is nearly as bad, because flicking through the grid builds
            // and destroys hundreds of them, and each one queued a job that
            // then ran, one after another, while he was still scrolling. That
            // is what made the wheel feel heavy. A row passed in a quarter of a
            // second was never looked at.
            // A still asks for its cached thumbnail the moment it is built.
            // No dwell timer, unlike the poster below: the answer is usually
            // already on the row (the model fills it in at scan time), and the
            // queue behind it is a bounded stack, so a flick past this tile
            // costs a request that is then dropped for a newer one.
            // `=== true` rather than a bare role for the same reason the hover
            // player below uses one: a delegate being torn down evaluates this
            // with its model context already gone.
            readonly property bool live: isLive === true

            Component.onCompleted: if (!tile.live && isVideo === false && thumb === "")
                                       Gallery.requestThumb(path)

            Timer {
                id: posterDwell
                interval: 250
                running: !tile.live && isVideo && poster === ""
                onTriggered: if (isVideo && poster === "") Gallery.requestPoster(path)
            }

            // DRAG AN OUTPUT OUT OF THE WINDOW, into anything that takes a file
            // — a browser upload field, filer, a chat window. Same idiom as
            // filer's rows (docs/DESIGN.md §13), and its findings are why it is
            // written this way: `Drag.active` bound to a MouseArea dragging an
            // INVISIBLE proxy is what actually starts a cross-app QDrag under
            // Wayland (a bare `Drag.startDrag()` did not), and the payload is
            // built on PRESS rather than bound, since building it can cost real
            // work (a clip is muted first — see below) and a binding would do
            // that for every realised tile.
            // A JOB IN FLIGHT IS NOT A FILE. Nothing that hands a path to
            // something else — the drag, the double-click, the menu's inject
            // and copy rows — may act on the running job's row, and the way it
            // is kept honest is that its "path" is a sentinel that exists
            // nowhere (main.py `LIVE_PATH`).
            Drag.active: !tile.live && tileMa.drag.active
            Drag.dragType: Drag.Automatic
            Drag.supportedActions: Qt.CopyAction
            Drag.hotSpot.x: 6
            Drag.hotSpot.y: 6

            Item { id: dragProxy }

            // The chip that follows the cursor: the filename on a small badge,
            // grabbed into Drag.imageSource on press (off-screen + layered so
            // grabToImage always has something to render).
            Rectangle {
                id: dragBadge
                x: -10000
                width: Math.min(badgeText.implicitWidth + 16, 320)
                height: badgeText.implicitHeight + 10
                color: Theme.bgAlt
                radius: Theme.rounding
                border.color: Theme.accent
                border.width: Theme.ctrlBorder
                layer.enabled: true
                PixelText {
                    id: badgeText
                    anchors {
                        left: parent.left; right: parent.right
                        verticalCenter: parent.verticalCenter
                        leftMargin: 8; rightMargin: 8
                    }
                    elide: Text.ElideMiddle
                    // What is actually being handed over, which for a set is one
                    // picture and not the files: a chip saying "4 outputs" over
                    // a drag that drops a collage would be a lie about the thing
                    // in his hand (docs/DESIGN.md §10).
                    text: tile.dragPaths.length > 1
                          ? (tile.dragPaths.length + " outputs as one collage")
                          : (isVideo && !tile.dragOriginal ? name + " (muted)" : name)
                    color: Theme.text
                }
            }

            // Shift at the moment of the press means "with its sound" on a lone
            // clip (ctrl+shift once a selection is in play, since shift is the
            // range key); see App.dragUriList.
            property bool dragOriginal: false
            // What the press decided this drag carries — the selection when the
            // tile is part of one, otherwise this file alone.
            property var dragPaths: []
            // Metadata is only read when this tile is hovered. Half the history
            // may be over sshfs, so asking every realised tile for its seed
            // just to hide most of the answers would make scrolling expensive.
            readonly property var outputParams:
                (!tile.live && tileMa.containsMouse) ? Gallery.paramsAt(index) : null
            readonly property var outputSeed:
                outputParams && outputParams.seed !== undefined ? outputParams.seed : null

            Rectangle {
                anchors.fill: parent
                anchors.margins: 4
                // Selected reads as the desktop's selection everywhere else:
                // the `highlight` fill, and the accent border a hover already
                // uses — held rather than momentary (docs/DESIGN.md §3.1).
                color: view.isSelected(path) ? Theme.highlight : Theme.bgAlt
                border.color: (view.isSelected(path) || tileMa.containsMouse)
                              ? Theme.accent : Theme.border
                border.width: Theme.ctrlBorder

                // A video tile shows its poster frame, extracted once into
                // ~/.cache/painter/posters (main.py, Gallery). Until that lands
                // — or if ffmpeg is not there at all — the cell stays empty
                // rather than trying to decode an mp4 as an image.
                Image {
                    id: still
                    objectName: tile.live ? "liveHistoryImage" : "historyImage"
                    anchors.fill: parent
                    anchors.margins: 1
                    // THE CACHED THUMBNAIL, not the output. Half this history
                    // is top's output directory over sshfs and the originals
                    // are 1-2 MB PNGs — measured 0.70s to read ONE, paid again
                    // every time a delegate was rebuilt. main.py `_ThumbJob`.
                    // Empty until one exists, the way a clip's poster is: a
                    // tile that shows nothing for a moment beats a grid that
                    // stalls the scroll.
                    // The running job draws the sampler's own preview frames —
                    // the same provider the preview viewport reads, and the
                    // reason the tick is in the URL is that an Image whose URL
                    // never changes never reloads (main.py `LivePreview`).
                    source: tile.live
                            ? (App.previewTick > 0
                               ? "image://livepreview/" + App.previewTick : "")
                            : (isVideo ? poster : thumb)
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    // Live ticks replace this URL asynchronously; the old
                    // step remains the honest preview until the new one is
                    // ready instead of flashing the empty tile background.
                    retainWhileLoading: tile.live
                    // CACHED, and decoded at the size actually drawn.
                    //
                    // This was `cache: false` at a fixed 420px, and it is what
                    // made scrolling the grid feel heavy: a GridView destroys a
                    // delegate the moment it leaves the viewport and builds it
                    // again when it comes back, so every row that scrolled past
                    // and back re-read a multi-megabyte PNG off disk and
                    // re-decoded it — for a cell a third of that size. The
                    // cache is Qt's own (QML_PIXMAP_CACHE_LIMIT) and holds the
                    // decoded thumbnails, not the originals.
                    // ...but a live frame is a NEW picture at the same URL every
                    // step, so that one is never cached and never scaled to the
                    // thumbnail size.
                    cache: !tile.live
                    sourceSize.width: tile.live ? 0 : grid.thumbPx
                }

                // HOVER A CLIP AND IT PLAYS, silently — the preview a video
                // thumbnail has on the web, and the reason a poster frame is
                // not enough: which of five takes this is shows in the motion,
                // not in frame 0. Loaded ONLY while the pointer is on the tile,
                // so a grid of sixty clips is never sixty decoders — the mouse
                // is in one cell at a time, and leaving it destroys the player
                // rather than pausing one that goes on holding a file open.
                //
                // MUTED, and not merely quiet: the model generates sound with
                // the picture and he listens to music while these run — the
                // same rule the preview pane and the muted drag copy follow.
                // The poster stays underneath, so the tile shows the frame it
                // always did until there are real frames to draw over it.
                Loader {
                    id: hoverPlay
                    anchors.fill: still
                    // `=== true`, not a bare role: a delegate being torn down
                    // (a gallery reset while the pointer is on a tile) evaluates
                    // this once with its model context already gone, and a bare
                    // `isVideo` is then `undefined` — a QML warning, which in
                    // this app fails the harness.
                    active: isVideo === true && !tile.live && tileMa.containsMouse
                    sourceComponent: Item {
                        // Aliased so the harness can assert what a person can
                        // only hear: an AudioOutput is a plain QObject, not an
                        // Item, so nothing walking the scene can reach it.
                        property alias playing: mp.playing
                        property alias muted: hush.muted
                        property alias volume: hush.volume
                        AudioOutput { id: hush; muted: true; volume: 0 }
                        MediaPlayer {
                            id: mp
                            source: url
                            videoOutput: vo
                            audioOutput: hush
                            loops: MediaPlayer.Infinite
                            Component.onCompleted: play()
                        }
                        VideoOutput {
                            id: vo
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                        }
                    }
                }

                // The play marker: this tile is a clip, not a still. DRAWN, not
                // lettered — "▶" is glyph 0 in two of the three pixel fonts, so
                // it is a staircase of 1px rows (docs/DESIGN.md §2.3), the same
                // construction filer's video tiles use. It says "this is a
                // clip", so it goes while the clip is the thing on screen.
                Loader {
                    active: isVideo === true && !tile.live && !hoverPlay.active
                    anchors { left: parent.left; top: parent.top; margins: 5 }
                    sourceComponent: Rectangle {
                        width: 15
                        height: 15
                        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.72)
                        radius: Theme.rounding
                        border.width: Theme.ctrlBorder
                        border.color: root.winActive ? Theme.border : Theme.inactive
                        Item {
                            anchors.centerIn: parent
                            width: 7
                            height: 7
                            Repeater {
                                model: 7
                                Rectangle {
                                    required property int index
                                    // 1,2,3,4,3,2,1 — a symmetric arrowhead.
                                    x: 0
                                    y: index
                                    height: 1
                                    width: 4 - Math.abs(index - 3)
                                    color: root.winActive ? Theme.text : Theme.inactive
                                }
                            }
                        }
                    }
                }

                // A JOB WITH NO FRAME YET IS A STATE, not an empty cell — the
                // first step of a video model can take half a minute, and a
                // blank tile at the top of the history reads as a broken one.
                PixelText {
                    anchors.centerIn: parent
                    width: parent.width - 16
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    visible: tile.live && App.previewTick === 0
                    // A ROW EXISTS FROM THE PRESS, not from the first sample:
                    // a prompt queued behind another job says so rather than
                    // looking like one that is producing nothing.
                    text: App.busy ? "waiting for the first frame" : "queued"
                    color: Theme.dim
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 1
                    height: 18
                    color: Theme.bg
                    // The running job says what it is at all times: it is the
                    // one tile in the grid whose picture is not what it will
                    // end up being.
                    opacity: (tileMa.containsMouse || tile.live) ? 0.9 : 0
                    PixelText {
                        anchors.centerIn: parent
                        width: parent.width - 8
                        elide: Text.ElideMiddle
                        text: !tile.live ? name
                              : !App.busy ? "queued"
                              : App.previewFrames > 1
                                ? "sampling - frame " + App.previewFrame
                                  + " of " + App.previewFrames
                                : "sampling"
                        color: tile.live ? Theme.accent : Theme.text
                    }
                }

                MouseArea {
                    id: tileMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    // Nothing above may take the press-drag and scroll with it.
                    preventStealing: true
                    // The proxy is what moves, so the tile stays where it is.
                    // Left button only: a right-press opens the menu and must
                    // not arm a drag on the way.
                    property bool deferSelect: false
                    property bool dragged: false
                    drag.onActiveChanged: if (tileMa.drag.active) tileMa.dragged = true

                    onPressed: function (m) {
                        if (tile.live) {
                            // Selecting it is the whole interaction: that is
                            // how you get the preview viewport back onto the
                            // generation after looking at something else.
                            tileMa.drag.target = null
                            view.selectSingle(path)
                            return
                        }
                        tileMa.drag.target = m.button === Qt.LeftButton ? dragProxy : null
                        if (m.button !== Qt.LeftButton) {
                            // A right-press opens the menu; it must not collapse
                            // a selection the menu is about to act on, and it
                            // must not arm a drag on the way.
                            if (!view.isSelected(path)) view.selectSingle(path)
                            return
                        }
                        tileMa.dragged = false
                        var ctrl = (m.modifiers & Qt.ControlModifier) !== 0
                        var shift = (m.modifiers & Qt.ShiftModifier) !== 0
                        // SHIFT MEANS RANGE HERE, so it cannot also mean "with
                        // the sound" the way it does on a lone clip: the
                        // original-audio drag is ctrl+shift when a selection is
                        // in play, and plain shift only when it is a single
                        // unselected tile being dragged.
                        tileMa.deferSelect = false
                        if (ctrl && shift) {
                            tile.dragOriginal = true
                        } else if (shift) {
                            view.extendTo(path)
                        } else if (ctrl) {
                            view.toggleSelect(path)
                        } else if (view.isSelected(path) && view.selection.length > 1) {
                            tileMa.deferSelect = true      // let a drag carry the set
                        } else {
                            view.selectSingle(path)
                        }
                        if (!(ctrl && shift)) tile.dragOriginal = false

                        // Built here, not bound: for a clip this makes the muted
                        // copy and for a selection it collects the collage, and
                        // the payload has to name a file that exists by the time
                        // the drop lands.
                        tile.dragPaths = view.dragPathsFor(path)
                        tile.Drag.mimeData = {
                            "text/uri-list": App.dragUriListFor(tile.dragPaths,
                                                                tile.dragOriginal)
                        }
                        // Staged now; ready by the time the drag passes the
                        // threshold and Drag.active turns on.
                        dragBadge.grabToImage(function (res) {
                            tile.Drag.imageSource = res.url
                        })
                    }

                    onReleased: {
                        if (tileMa.deferSelect && !tileMa.dragged) view.selectSingle(path)
                        tileMa.deferSelect = false
                    }
                    // DOUBLE-CLICK OPENS, right-click asks what else, and a
                    // single left click SELECTS — which since 2026-08-28 is
                    // also what puts that output in the preview viewport above.
                    // It used to do nothing at all, because the pane could only
                    // ever show the running job ("no clicking on other outputs
                    // or anything"); the running job is a row in this grid now,
                    // so selecting one is how you choose between them.
                    onClicked: function (m) {
                        if (m.button === Qt.LeftButton) return
                        var pt = mapToItem(null, m.x, m.y)
                        view.menuRequested(pt.x, pt.y,
                                           tile.live ? view.liveMenu()
                                                     : view.menuFor(index, path, isVideo))
                    }
                    onDoubleClicked: function (m) {
                        // There is no file to open until it lands.
                        if (tile.live) return
                        // IN-APP NOW, not the external viewer. A double-click
                        // in a thumbnail grid means "look at this one", and
                        // since the pane grew a View mode that is a thing this
                        // window can do (docs/DESIGN.md §7.6, ResultsPane).
                        // `viewer` is still one row up the right-click menu and
                        // in the File menu, for the times you want the real
                        // image tool.
                        if (m.button === Qt.LeftButton)
                            view.openRequested(path, isVideo)
                    }
                }
            }
        }
    }

    // Both of these are prose in a pane that can now be 220px wide, so both
    // wrap instead of running off the edge and taking the layout with them.
    PixelText {
        anchors.centerIn: parent
        width: Math.min(implicitWidth, parent.width - 8)
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        visible: Gallery.count === 0
        text: "nothing yet - Ctrl+Enter or the gen button"
        color: Theme.dim
    }

    PixelText {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 3
        width: parent.width
        elide: Text.ElideRight
        // Dragging one out is the only affordance here with no visible handle,
        // so it is the part the line keeps when there is no room for the rest.
        text: view.width > 400 ? "drag one out, double-click to open, right-click for more"
            : view.width > 250 ? "drag out, double-click opens"
                               : "drag out"
        color: Theme.dim
    }

}

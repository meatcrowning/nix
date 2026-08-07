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

    function isSelected(p) { return view.selection.indexOf(p) >= 0 }

    function setSelection(paths) {
        view.selection = paths
        // Warm the collage for what a drag would now carry: it is a few hundred
        // ms of decoding and half a dozen encodes, and at the press there is no
        // time for either (App.dragUriListFor).
        App.prepareCollage(paths)
    }

    function selectSingle(p) {
        view.anchorPath = p
        view.setSelection([p])
    }

    function toggleSelect(p) {
        var s = view.selection.slice()
        var i = s.indexOf(p)
        if (i >= 0) s.splice(i, 1)
        else s.push(p)
        view.anchorPath = p
        view.setSelection(s)
    }

    function extendTo(p) {
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

    // An output's PNG carries the whole job that made it, so the useful question
    // is WHICH PART to take: its words, its numbers, or both. That is a choice,
    // and a choice is a menu — it used to be an unlabelled right-click that took
    // everything, with no way to ask for less.
    function menuFor(index, path, isVideo) {
        var p = Gallery.paramsAt(index)
        if (!p) {
            return [{ label: isVideo ? "a video carries its ComfyUI graph, not these settings"
                                     : "no parameters stored in this file", enabled: false },
                    { separator: true }].concat(view.commonItems(index, path, isVideo, p))
        }
        return [
            { label: "inject all", trigger: () => { root.injectAll(p); root.view = 0 } },
            { label: "inject prompt", trigger: () => { root.injectPrompt(p); root.view = 0 } },
            { label: "inject params", trigger: () => { root.injectParams(p); root.view = 0 } },
            { separator: true }
        ].concat(view.commonItems(index, path, isVideo, p))
    }

    // The items every output gets, parameters or not. The last two are offered
    // only when there is something to offer: the prompt when the file kept one
    // (a clip never does — its metadata is ComfyUI's graph), the muted copy on a
    // video, there being nothing to strip off a still. An action with nothing
    // to act on is not offered greyed, it is not offered (docs/DESIGN.md §10).
    function commonItems(index, path, isVideo, params) {
        var items = [{ label: "open in viewer", trigger: () => App.openExternally(path) }]
        if (params && params.positive) {
            items.push({ label: "copy prompt",
                         trigger: () => App.copyPrompt(path) })
        }
        if (isVideo) {
            items.push({ label: "copy muted copy",
                         trigger: () => App.copyMuted(path) })
        }
        return items
    }

    Row {
        id: head
        spacing: 10
        width: parent.width
        PixelText { text: "output"; color: root.fgAccent }
        // Dropped rather than squeezed when the pane is narrow: the count is
        // the least of the three things this pane owes you (docs/DESIGN.md §5.4).
        PixelText {
            // "outputs", not "images": a video family's results are clips.
            // A selection says so here rather than in a bar of its own — it is
            // one number and it belongs beside the other one.
            text: view.selection.length > 1
                  ? (view.selection.length + " of " + Gallery.count + " selected")
                  : (Gallery.count + " outputs")
            color: view.selection.length > 1 ? Theme.text : Theme.textDim
            visible: view.width > 190
        }
    }

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
        anchors.bottomMargin: 28
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
        cellWidth: Math.max(60, Math.floor(usable / Math.max(1, Math.round(usable / 210))))
        cellHeight: cellWidth
        wheelLines: 1
        wheelStep: cellHeight

        delegate: Item {
            id: tile
            width: grid.cellWidth
            height: grid.cellHeight

            // DRAG AN OUTPUT OUT OF THE WINDOW, into anything that takes a file
            // — a browser upload field, filer, a chat window. Same idiom as
            // filer's rows (docs/DESIGN.md §13), and its findings are why it is
            // written this way: `Drag.active` bound to a MouseArea dragging an
            // INVISIBLE proxy is what actually starts a cross-app QDrag under
            // Wayland (a bare `Drag.startDrag()` did not), and the payload is
            // built on PRESS rather than bound, since building it can cost real
            // work (a clip is muted first — see below) and a binding would do
            // that for every realised tile.
            Drag.active: tileMa.drag.active
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
                border.color: Theme.accent
                border.width: 1
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

            Rectangle {
                anchors.fill: parent
                anchors.margins: 4
                // Selected reads as the desktop's selection everywhere else:
                // the `highlight` fill, and the accent border a hover already
                // uses — held rather than momentary (docs/DESIGN.md §3.1).
                color: view.isSelected(path) ? Theme.highlight : Theme.bgAlt
                border.color: (view.isSelected(path) || tileMa.containsMouse)
                              ? Theme.accent : Theme.border
                border.width: 1

                // A video tile shows its poster frame, extracted once into
                // ~/.cache/painter/posters (main.py, Gallery). Until that lands
                // — or if ffmpeg is not there at all — the cell stays empty
                // rather than trying to decode an mp4 as an image.
                Image {
                    id: still
                    anchors.fill: parent
                    anchors.margins: 1
                    source: isVideo ? poster : url
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: false
                    sourceSize.width: 420
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
                    active: isVideo === true && tileMa.containsMouse
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
                    active: isVideo === true && !hoverPlay.active
                    anchors { left: parent.left; top: parent.top; margins: 5 }
                    sourceComponent: Rectangle {
                        width: 15
                        height: 15
                        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.72)
                        border.width: 1
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

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 1
                    height: 18
                    color: Theme.bg
                    opacity: tileMa.containsMouse ? 0.9 : 0
                    PixelText {
                        anchors.centerIn: parent
                        width: parent.width - 8
                        elide: Text.ElideMiddle
                        text: name
                        color: Theme.text
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
                    // DOUBLE-CLICK OPENS, right-click asks what else. A single
                    // left click does nothing on purpose: the preview viewport
                    // above shows the job that is running and then what it made
                    // (his words: "no clicking on other outputs or anything"),
                    // so a click here would have nowhere to put an old output.
                    onClicked: function (m) {
                        if (m.button === Qt.LeftButton) return
                        var pt = mapToItem(null, m.x, m.y)
                        view.menuRequested(pt.x, pt.y, view.menuFor(index, path, isVideo))
                    }
                    onDoubleClicked: function (m) {
                        if (m.button === Qt.LeftButton) App.openExternally(path)
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
        anchors.bottomMargin: 6
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

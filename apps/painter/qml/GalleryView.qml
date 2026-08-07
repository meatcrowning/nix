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

    // An output's PNG carries the whole job that made it, so the useful question
    // is WHICH PART to take: its words, its numbers, or both. That is a choice,
    // and a choice is a menu — it used to be an unlabelled right-click that took
    // everything, with no way to ask for less.
    function menuFor(index, path, isVideo) {
        var p = Gallery.paramsAt(index)
        if (!p) {
            return [{ label: isVideo ? "a video carries its ComfyUI graph, not these settings"
                                     : "no parameters stored in this file", enabled: false },
                    { separator: true }].concat(view.commonItems(index, path, isVideo))
        }
        return [
            { label: "inject all", trigger: () => { root.injectAll(p); root.view = 0 } },
            { label: "inject prompt", trigger: () => { root.injectPrompt(p); root.view = 0 } },
            { label: "inject params", trigger: () => { root.injectParams(p); root.view = 0 } },
            { separator: true }
        ].concat(view.commonItems(index, path, isVideo))
    }

    // The items every output gets, parameters or not. The muted copy is
    // video-only: there is nothing to strip off a still.
    function commonItems(index, path, isVideo) {
        var items = [{ label: "open in viewer", trigger: () => App.openExternally(path) }]
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
            text: Gallery.count + " outputs"
            color: Theme.textDim
            visible: view.width > 190
        }
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
                    text: isVideo && !tile.dragOriginal ? name + " (muted)" : name
                    color: Theme.text
                }
            }

            // Shift at the moment of the press means "with its sound"; see
            // App.dragUriList.
            property bool dragOriginal: false

            Rectangle {
                anchors.fill: parent
                anchors.margins: 4
                color: Theme.bgAlt
                border.color: tileMa.containsMouse ? Theme.accent : Theme.border
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
                    onPressed: function (m) {
                        tileMa.drag.target = m.button === Qt.LeftButton ? dragProxy : null
                        if (m.button !== Qt.LeftButton) return
                        tile.dragOriginal = (m.modifiers & Qt.ShiftModifier) !== 0
                        // Built here, not bound: for a clip this makes the muted
                        // copy, and the payload has to name a file that exists
                        // by the time the drop lands.
                        tile.Drag.mimeData = {
                            "text/uri-list": App.dragUriList(path, tile.dragOriginal)
                        }
                        // Staged now; ready by the time the drag passes the
                        // threshold and Drag.active turns on.
                        dragBadge.grabToImage(function (res) {
                            tile.Drag.imageSource = res.url
                        })
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

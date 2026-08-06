import QtQuick
import QtQuick.Controls.Basic
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
            width: grid.cellWidth
            height: grid.cellHeight

            Rectangle {
                anchors.fill: parent
                anchors.margins: 4
                color: Theme.bgAlt
                border.color: hover.containsMouse ? Theme.accent : Theme.border
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

                // The play marker: this tile is a clip, not a still. DRAWN, not
                // lettered — "▶" is glyph 0 in two of the three pixel fonts, so
                // it is a staircase of 1px rows (docs/DESIGN.md §2.3), the same
                // construction filer's video tiles use.
                Loader {
                    active: isVideo
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
                    opacity: hover.containsMouse ? 0.9 : 0
                    PixelText {
                        anchors.centerIn: parent
                        width: parent.width - 8
                        elide: Text.ElideMiddle
                        text: name
                        color: Theme.text
                    }
                }

                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
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
        text: view.width > 340 ? "double-click to open in viewer, right-click for more"
                               : "double-click opens"
        color: Theme.dim
    }

}

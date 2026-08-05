import QtQuick
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
    function menuFor(index, path) {
        var p = Gallery.paramsAt(index)
        if (!p) {
            return [{ label: "no parameters stored in this file", enabled: false },
                    { separator: true },
                    { label: "open in viewer", trigger: () => App.openExternally(path) }]
        }
        return [
            { label: "inject all", trigger: () => { root.injectAll(p); root.view = 0 } },
            { label: "inject prompt", trigger: () => { root.injectPrompt(p); root.view = 0 } },
            { label: "inject params", trigger: () => { root.injectParams(p); root.view = 0 } },
            { separator: true },
            { label: "open in viewer", trigger: () => App.openExternally(path) }
        ]
    }

    Row {
        id: head
        spacing: 10
        width: parent.width
        PixelText { text: "output"; color: root.fgAccent }
        // Dropped rather than squeezed when the pane is narrow: the count is
        // the least of the three things this pane owes you (docs/DESIGN.md §5.4).
        PixelText {
            text: Gallery.count + " images"
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
        // Fit whole columns to the pane, and NEVER a cell wider than the pane:
        // the old 150px floor meant a 140px-wide pane laid out a 150px cell, so
        // the single column was clipped and the grid looked empty — the
        // "outputs don't show when the window is small" bug, once the pane
        // itself stopped being hidden. One column is a legitimate answer.
        cellWidth: Math.max(60, Math.floor(width / Math.max(1, Math.round(width / 210))))
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

                Image {
                    anchors.fill: parent
                    anchors.margins: 1
                    source: url
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: false
                    sourceSize.width: 420
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
                    // Either button opens the same menu: §7.1 says everything is
                    // right-clickable, and left-click is where he reaches first.
                    onClicked: function (m) {
                        var pt = mapToItem(null, m.x, m.y)
                        view.menuRequested(pt.x, pt.y, view.menuFor(index, path))
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
        text: view.width > 340 ? "click an image to inject its prompt, params or both"
                               : "click an image to inject"
        color: Theme.dim
    }

}

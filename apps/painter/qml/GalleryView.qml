import QtQuick
import "../../qmlcommon"

// Results, newest first.  Every image carries the parameters that made it in a
// PNG text chunk, so "reuse" reads them straight back out of the file.
Item {
    id: view

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
                    onClicked: function (m) {
                        if (m.button === Qt.RightButton) {
                            var p = Gallery.paramsAt(index)
                            if (p) view.reuse(p)
                        } else {
                            App.openExternally(path)
                        }
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
        text: view.width > 340 ? "click opens in viewer / right-click reuses parameters"
                               : "click opens / right-click reuses"
        color: Theme.dim
    }

    // Pull an old image's settings back into the panel.
    function reuse(p) {
        // A CLONE, not the live object: `gen` is a `property var`, and assigning
        // back the same object emits no change signal, so a reuse would land in
        // the data and never appear on any control (see Main.qml's `set`).
        var g = root.clone(root.gen)
        if (p.positive !== undefined) g.positive = p.positive
        if (p.negative !== undefined) g.negative = p.negative
        if (p.steps !== undefined) g.steps = p.steps
        if (p.cfg !== undefined) g.cfg = p.cfg
        if (p.denoise !== undefined) g.denoise = p.denoise
        if (p.sampler_name !== undefined) g.sampler_name = p.sampler_name
        if (p.scheduler !== undefined) g.scheduler = p.scheduler
        // Size comes back as the CONTROLS that produce it, not as raw pixels:
        // width/height are derived now, so setting them here would be undone by
        // the next recompute and the panel would quietly disagree with the
        // image it was reused from. Reduce the ratio (gcd) and back out the
        // megapixels, which reproduces the original size exactly whenever it
        // was on the family's step to begin with.
        if (p.width !== undefined && p.height !== undefined
                && p.width > 0 && p.height > 0) {
            var a = p.width, b = p.height
            while (b) { var t = a % b; a = b; b = t }
            g.aspectW = Math.round(p.width / a)
            g.aspectH = Math.round(p.height / a)
            g.megapixels = Math.round(p.width * p.height / 100000) / 10
        }
        if (p.seed !== undefined) { g.seed = p.seed; g.randomSeed = false }
        if (p.toggles) {
            g.negpip = p.toggles.negpip === true
            g.modelSampling = p.toggles.model_sampling === true
        }
        if (p.model_sampling) {
            g.ms = root.clone(g.ms)
            for (var k in p.model_sampling) g.ms[k] = p.model_sampling[k]
        }
        root.gen = g
        root.recomputeDims()
        root.view = 0
    }
}

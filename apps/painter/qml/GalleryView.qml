import QtQuick
import "../../qmlcommon"

// Results, newest first.  Every image carries the parameters that made it in a
// PNG text chunk, so "reuse" reads them straight back out of the file.
Item {
    id: view

    Row {
        id: head
        spacing: 10
        PixelText { text: "output"; color: root.fgAccent }
        PixelText { text: Gallery.count + " images"; color: Theme.textDim }
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
        cellWidth: Math.max(150, Math.floor(width / Math.max(1, Math.floor(width / 210))))
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

    PixelText {
        anchors.centerIn: parent
        visible: Gallery.count === 0
        text: "nothing yet - Ctrl+Enter or the gen button"
        color: Theme.dim
    }

    PixelText {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 6
        text: "click opens in viewer / right-click reuses parameters"
        color: Theme.dim
    }

    // Pull an old image's settings back into the panel.
    function reuse(p) {
        var g = root.gen
        if (p.positive !== undefined) g.positive = p.positive
        if (p.negative !== undefined) g.negative = p.negative
        if (p.steps !== undefined) g.steps = p.steps
        if (p.cfg !== undefined) g.cfg = p.cfg
        if (p.denoise !== undefined) g.denoise = p.denoise
        if (p.sampler_name !== undefined) g.sampler_name = p.sampler_name
        if (p.scheduler !== undefined) g.scheduler = p.scheduler
        if (p.width !== undefined) g.width = p.width
        if (p.height !== undefined) g.height = p.height
        if (p.seed !== undefined) { g.seed = p.seed; g.randomSeed = false }
        if (p.toggles) {
            g.negpip = p.toggles.negpip === true
            g.modelSampling = p.toggles.model_sampling === true
        }
        if (p.model_sampling) {
            for (var k in p.model_sampling) g.ms[k] = p.model_sampling[k]
        }
        root.gen = g
        root.view = 0
    }
}

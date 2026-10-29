import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Aspect plus a pixel budget, quantised to whatever step the family needs
// (Flux 2 downscales by 16, Krea 2 by 8).
//
// The aspect is TWO INTEGERS you type, not a list to choose from: the fixed
// list could not express 5:3 or 21:9, and the width/height boxes that used to
// sit beside it were a second, contradicting source of truth — set a size by
// hand and the aspect above it was simply wrong, with nothing saying which one
// the graph would use. One place decides now: ratio + megapixels -> the pixels
// in the badge, which are the pixels submitted.
// IMAGE-TO-VIDEO HAS NO ASPECT TO SET. The video workflow scales the dropped
// image to the pixel budget and reads the frame size back OUT of it
// (ImageScaleToTotalPixels -> GetImageSize), so an aspect box there would be a
// control that changes nothing — §10 again. It goes, and the readout says where
// the size is coming from instead of quoting numbers painter did not decide.
Panel {
    id: panel
    title: "Latent"
    // Whether the image, not this panel, is deciding the shape.
    // EITHER dropped frame decides it — the workflow measures whichever one is
    // there (the first when both are), so the aspect goes for both modes.
    readonly property bool fromImage: App.isVideo && !root.gen.still
                                      && (root.gen.useInputImage || root.gen.useLastFrame)
    badge: App.isEdit ? "" : fromImage ? "from the image" : (root.gen.width + "x" + root.gen.height)

    Field {
        objectName: "latentDimensionsRow"
        label: panel.fromImage ? "MP" : "AR"
        labelWidth: 24
        visible: !App.isEdit
        hint: "Aspect ratio and target megapixels determine the generated dimensions."
        RowLayout {
            width: parent.width
            spacing: 6
            Spin {
                visible: !panel.fromImage
                Layout.preferredWidth: 52
                value: root.gen.aspectW; from: 1; to: 999; step: 1
                onEdited: function (v) {
                    root.set("aspectW", Math.round(v))
                    root.recomputeDims()
                }
            }
            PixelText {
                visible: !panel.fromImage
                text: ":"
                color: Theme.dim
            }
            Spin {
                visible: !panel.fromImage
                Layout.preferredWidth: 52
                value: root.gen.aspectH; from: 1; to: 999; step: 1
                onEdited: function (v) {
                    root.set("aspectH", Math.round(v))
                    root.recomputeDims()
                }
            }
            PixelText {
                visible: !panel.fromImage
                text: "MP"
                color: Theme.textDim
            }
            Spin {
                trimZeros: App.layoutSupport
                Layout.preferredWidth: App.layoutSupport ? 100 : 60
                value: root.gen.megapixels; from: App.layoutSupport ? 0.05 : 0.1; to: App.layoutSupport ? 16 : 8; step: 0.1; decimals: App.layoutSupport ? 6 : 1
                onEdited: function (v) {
                    root.set("megapixels", v)
                    root.recomputeDims()
                }
            }
            PixelText {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: panel.fromImage ? "from the image" : (root.gen.width + "×" + root.gen.height)
                color: Theme.textDim
                elide: Text.ElideRight
            }
        }
    }

    Column {
        objectName: "latentSeedRow"
        width: parent.width
        spacing: 6
        function seedMode(random) {
            root.set("seed", random ? -1 : (root.gen.seed < 0 ? App.freshSeed() : root.gen.seed))
            root.set("randomSeed", random)
            root.set("reuseSeed", false)
        }
        RowLayout {
            width: parent.width
            spacing: 4
            Button {
                icon.name: "media-playlist-shuffle"
                display: AbstractButton.IconOnly
                implicitWidth: implicitHeight
                Accessible.name: "Randomize seed"
                ToolTip.visible: hovered
                ToolTip.text: "Randomize seed for each generation"
                onClicked: parent.parent.seedMode(true)
            }
            Button {
                icon.name: "document-new"
                display: AbstractButton.IconOnly
                implicitWidth: implicitHeight
                Accessible.name: "New fixed seed"
                ToolTip.visible: hovered
                ToolTip.text: "New fixed seed"
                onClicked: {
                    root.set("seed", App.freshSeed())
                    parent.parent.seedMode(false)
                }
            }
            ComboBox {
                model: ["Fixed", "Random", "Reuse last"]
                currentIndex: root.gen.reuseSeed ? 2 : root.gen.randomSeed ? 1 : 0
                onActivated: index => {
                    if (index === 2) {
                        root.set("randomSeed", false)
                        root.set("reuseSeed", true)
                        if (App.lastSeed >= 0) root.set("seed", App.lastSeed)
                    } else parent.parent.seedMode(index === 1)
                }
            }
            PixelText {
                text: "Seed number"
                Layout.alignment: Qt.AlignVCenter
            }
            SeedInput {
                Layout.fillWidth: true
                Layout.minimumWidth: 40
                Layout.preferredWidth: 100
                enabled: !root.gen.randomSeed && !root.gen.reuseSeed
                value: root.gen.reuseSeed && App.lastSeed >= 0 ? App.lastSeed : root.gen.seed
                onEdited: value => root.set("seed", value)
            }
        }
    }

}

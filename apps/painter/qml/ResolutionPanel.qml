import QtQuick

// Aspect plus a pixel budget, quantised to whatever step the family needs
// (Flux 2 downscales by 16, Krea 2 by 8).  Width and height stay editable for
// the times a specific size is wanted.
Panel {
    title: "resolution"
    badge: root.gen.width + "x" + root.gen.height

    Field {
        label: "aspect"
        Row {
            spacing: 8
            Picker {
                width: 110
                options: App.aspects
                value: root.gen.aspect
                onPicked: function (v) {
                    var g = root.gen; g.aspect = v; root.gen = g; root.recomputeDims()
                }
            }
            PixelText { text: "MP"; color: Theme.textDim; anchors.verticalCenter: parent.verticalCenter }
            Spin {
                width: 60
                value: root.gen.megapixels; from: 0.1; to: 8; step: 0.1; decimals: 1
                onEdited: function (v) {
                    var g = root.gen; g.megapixels = v; root.gen = g; root.recomputeDims()
                }
            }
        }
    }

    Field {
        label: "size"
        Row {
            spacing: 8
            Spin {
                width: 74
                value: root.gen.width; from: 64; to: 8192; step: root.gen.multiple
                onEdited: function (v) { var g = root.gen; g.width = v; root.gen = g }
            }
            PixelText { text: "x"; color: Theme.dim; anchors.verticalCenter: parent.verticalCenter }
            Spin {
                width: 74
                value: root.gen.height; from: 64; to: 8192; step: root.gen.multiple
                onEdited: function (v) { var g = root.gen; g.height = v; root.gen = g }
            }
            PixelText {
                text: "/" + root.gen.multiple
                color: Theme.dim
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}

import QtQuick

// Aspect plus a pixel budget, quantised to whatever step the family needs
// (Flux 2 downscales by 16, Krea 2 by 8).
//
// The aspect is TWO INTEGERS you type, not a list to choose from: the fixed
// list could not express 5:3 or 21:9, and the width/height boxes that used to
// sit beside it were a second, contradicting source of truth — set a size by
// hand and the aspect above it was simply wrong, with nothing saying which one
// the graph would use. One place decides now: ratio + megapixels -> the pixels
// in the badge, which are the pixels submitted.
Panel {
    id: panel
    title: "resolution"
    badge: root.gen.width + "x" + root.gen.height

    Field {
        label: "aspect"
        hint: "Any two whole numbers - 3:2, 5:3, 21:9. The pixel size comes from this and MP."
        Row {
            spacing: 6
            Spin {
                width: 52
                value: root.gen.aspectW; from: 1; to: 999; step: 1
                onEdited: function (v) {
                    root.set("aspectW", Math.round(v))
                    root.recomputeDims()
                }
            }
            PixelText {
                text: ":"
                color: Theme.dim
                anchors.verticalCenter: parent.verticalCenter
            }
            Spin {
                width: 52
                value: root.gen.aspectH; from: 1; to: 999; step: 1
                onEdited: function (v) {
                    root.set("aspectH", Math.round(v))
                    root.recomputeDims()
                }
            }
        }
    }

    Field {
        label: "MP"
        hint: "Target megapixels. Width and height are derived from this and the aspect, rounded to the family's step."
        Row {
            spacing: 6
            Spin {
                width: 60
                value: root.gen.megapixels; from: 0.1; to: 8; step: 0.1; decimals: 1
                onEdited: function (v) {
                    root.set("megapixels", v)
                    root.recomputeDims()
                }
            }
            // What the two controls actually produce, spelled out rather than
            // left to the header badge alone — with the family's rounding step,
            // which is why the size is rarely the round number you asked for
            // (docs/DESIGN.md §10: report what will happen, not what was meant).
            PixelText {
                text: "= " + root.gen.width + "x" + root.gen.height + " /" + root.gen.multiple
                color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}

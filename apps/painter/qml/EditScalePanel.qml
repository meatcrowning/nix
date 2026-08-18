import QtQuick

// OUTPUT SIZE FOR EDIT MODE. The edit graph reads the size out of the dropped
// image, so unlike the text-to-image path there is no aspect and no MP to set —
// [his] the only thing left to decide is how big the RESULT is relative to the
// picture that went in.
//
// Two mutually-exclusive controls, exactly as the image path's ResolutionPanel
// is one source of truth for its size: a "no scaling" toggle keeps the output at
// the original image's dimensions, and turning it off reveals a single scale
// multiplier (1.5, 2, ...) the output is enlarged/reduced by. The primary image
// still sizes the latent AND the scheduler AND the reference latent (they all
// read the same scaled node), so the three stay aligned by construction — see
// registry._build_edit and graphs/edit_flux2.json.
Panel {
    id: panel
    title: "output size"
    badge: root.gen.editNoScale ? "original size"
                                : ("x" + (+root.gen.editScale).toFixed(2).replace(/\.?0+$/, ""))

    Toggle {
        label: "no scaling (keep the original's size)"
        checked: root.gen.editNoScale
        onToggled: function (v) { root.set("editNoScale", v) }
    }

    // Only offered when scaling is on — a disabled multiplier that does nothing
    // would be a control that lies (docs/DESIGN.md §10). The Column skips the
    // hidden child, so it leaves no gap.
    Field {
        label: "scale"
        visible: !root.gen.editNoScale
        hint: "The output is the dropped image's size times this. 2 doubles each side (4x the pixels)."
        Row {
            spacing: 6
            Spin {
                width: 60
                value: root.gen.editScale; from: 0.25; to: 4; step: 0.25; decimals: 2
                onEdited: function (v) { root.set("editScale", v) }
            }
            PixelText {
                text: "x the original"
                color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    PixelText {
        text: root.gen.editNoScale
              ? "  the result keeps the dropped image's width and height"
              : "  the result is the dropped image, enlarged by the multiplier"
        color: Theme.dim
        width: parent.width
        wrapMode: Text.Wrap
    }
}

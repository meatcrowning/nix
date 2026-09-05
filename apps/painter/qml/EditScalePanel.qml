import QtQuick

// OUTPUT SIZE FOR EDIT MODE. The edit graph reads the size out of the dropped
// image, so unlike the text-to-image path there is no aspect and no width/height
// to set — [his] the only thing left to decide is how big the RESULT is.
//
// Two mutually-exclusive controls, exactly as the image path's ResolutionPanel
// is one source of truth for its size: a "no scaling" toggle keeps the output at
// the original image's exact dimensions, and turning it off reveals a single
// MEGAPIXEL budget — the SAME control the video path offers when a frame is
// dropped (ResolutionPanel/VideoPanel): name the pixels, the image's own aspect
// is kept. The primary image still sizes the latent AND the scheduler AND the
// reference latent (they all read the same scaled node), so the three stay
// aligned by construction — see registry._build_edit and graphs/edit_flux2.json.
Panel {
    id: panel
    title: "Output Size"
    badge: root.gen.editNoScale ? "original size"
                                : ((+root.gen.editMegapixels).toFixed(1) + "MP")

    Toggle {
        label: "No Scaling (Keep the Original Size)"
        checked: root.gen.editNoScale
        onToggled: function (v) { root.set("editNoScale", v) }
    }

    // Only offered when scaling is on — a disabled field that does nothing would
    // be a control that lies (docs/DESIGN.md §10). The Column skips the hidden
    // child, so it leaves no gap. Same MP box as the resolution/video panels.
    Field {
        label: "MP"
        visible: !root.gen.editNoScale
        hint: "Target megapixels. The dropped image is scaled to this many pixels, keeping its aspect."
        Row {
            spacing: 6
            Spin {
                width: 60
                value: root.gen.editMegapixels; from: 0.1; to: 8; step: 0.1; decimals: 1
                onEdited: function (v) { root.set("editMegapixels", v) }
            }
            // Where the size comes from, spelled out rather than left to the
            // badge alone (docs/DESIGN.md §10) — the aspect is the image's own.
            PixelText {
                text: "= the dropped image, at this budget"
                color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    PixelText {
        text: root.gen.editNoScale
              ? "  the result keeps the dropped image's width and height"
              : "  the result is the dropped image, scaled to the megapixels above"
        color: Theme.dim
        width: parent.width
        wrapMode: Text.Wrap
    }
}

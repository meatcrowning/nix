import QtQuick

// EDIT MODE'S LEFT COLUMN IS A PLACE TO DROP IMAGES AND A PROMPT BOX, and this
// is the first half [his] "the left side of the program when edit is selected
// should really just be a box to drop the image in and a prompt box".
// Everything else is hidden by Main.qml rather than shown doing nothing: the
// edit graph reads the size out of the FIRST dropped image, takes no negative
// prompt (its negative conditioning is the positive one zeroed out) and carries
// the family's own steps/cfg/shift.
//
// Flux 2 Klein takes MULTIPLE reference images (comfy attaches each as a
// reference latent, chained), so the primary well is joined by a stack of
// extra wells and one empty "add another" well. The primary is the SAME slot as
// the video first frame (App.inputImage) on purpose: painter holds one dropped
// picture, so a frame dropped for a clip is still there if you switch to edit,
// and it is remembered across launches by the prefs key that already existed.
// The extras are their own list (App.editExtraImages).
Panel {
    id: panel
    title: "images"
    badge: App.inputImage === "" ? "drop one" : ""

    // The primary — it decides the output size, the rest are references.
    FrameWell {
        active: true
        path: App.inputImage
        url: App.inputImageUrl
        emptyText: "drag or paste the image to edit here (this one sets the size)"
        winActive: root.winActive
        accepts: function (u) { return App.setInputImage(u) }
        paste: function () { return App.pasteInputImage() }
        // Order-independent: moving straight from one well to the other must
        // not have the leave clear the target the enter just set.
        onHoveredChanged: {
            if (hovered) root.hoveredWell = "input"
            else if (root.hoveredWell === "input") root.hoveredWell = ""
        }
    }

    Row {
        spacing: 8
        visible: App.inputImage !== ""
        TextButton {
            label: "[ clear ]"
            tone: Theme.textDim
            winActive: root.winActive
            onClicked: { App.clearInputImage(); App.clearEditImages() }
        }
    }

    // The additional reference images, each with its own remove.
    Repeater {
        model: App.editExtraImages
        delegate: Column {
            width: panel.width
            required property int index
            required property string modelData
            FrameWell {
                width: parent.width
                active: true
                path: modelData
                url: App.fileUrl(modelData)
                emptyText: ""
                winActive: root.winActive
                // A filled reference well is not a drop target: use the add well.
                accepts: function (u) { return false }
                paste: function () { return false }
            }
            Row {
                spacing: 8
                TextButton {
                    label: "[ remove ]"
                    tone: Theme.textDim
                    winActive: root.winActive
                    onClicked: App.removeEditImage(index)
                }
            }
        }
    }

    // Always-empty "add another reference image" well — only once there is a
    // primary, since a reference with nothing to size against makes no sense.
    FrameWell {
        active: App.inputImage !== ""
        path: ""
        url: ""
        emptyText: "drag or paste another reference image here"
        winActive: root.winActive
        accepts: function (u) { return App.addEditImage(u) }
        paste: function () { return App.pasteEditImage() }
        onHoveredChanged: {
            if (hovered) root.hoveredWell = "editadd"
            else if (root.hoveredWell === "editadd") root.hoveredWell = ""
        }
    }
}

import QtQuick

// EDIT MODE'S LEFT COLUMN IS A PLACE TO DROP AN IMAGE AND A PROMPT BOX, and
// this is the first half [his] "the left side of the program when edit is
// selected should really just be a box to drop the image in and a prompt box".
// Everything else is hidden by Main.qml rather than shown doing nothing: the
// edit graph reads the size out of the dropped image, takes no negative prompt
// (its negative conditioning is the positive one zeroed out) and carries the
// family's own steps/cfg/shift.
//
// It is the SAME slot as the video first frame (App.inputImage) on purpose:
// painter holds one dropped picture, so a frame dropped for a clip is still
// there if you switch to edit, and it is remembered across launches by the one
// prefs key that already existed.
Panel {
    id: panel
    title: "image"
    badge: App.inputImage === "" ? "drop one" : ""

    FrameWell {
        active: true
        path: App.inputImage
        url: App.inputImageUrl
        emptyText: "drag or paste the image to edit here"
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
            onClicked: App.clearInputImage()
        }
    }
}

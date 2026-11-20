import QtQuick

Column {
    width: parent.width
    spacing: 5
    // The primary input also sets the output size in edit mode.
    FrameWell {
        enabled: !root.comparisonMode
        active: true
        path: App.inputImage
        url: App.inputImageUrl
        emptyText: App.referenceImages ? "drag or paste an image here" : App.optionalEditImage ? "leave blank to generate; add an image to edit" : "drag or paste the image to edit here (this one sets the size)"
        winActive: root.winActive
        accepts: function (u) { return App.setInputImage(u) }
        paste: function () { return App.pasteInputImage() }
        clearAction: function () { App.clearInputImage(); App.clearEditImages() }
        // Order-independent: moving straight from one well to the other must
        // not have the leave clear the target the enter just set.
        onHoveredChanged: {
            if (hovered) root.hoveredWell = "input"
            else if (root.hoveredWell === "input") root.hoveredWell = ""
        }
    }

    TextButton {
        label: "[ Choose image… ]"
        enabled: !root.comparisonMode
        visible: App.optionalEditImage || App.referenceImages
        winActive: root.winActive
        onClicked: root.importImage()
    }

    // The additional reference images, each with its own remove.
    Repeater {
        model: App.editMultipleImages ? App.editExtraImages : []
        delegate: Column {
            width: parent.width
            required property int index
            required property string modelData
            FrameWell {
                enabled: !root.comparisonMode
                width: parent.width
                active: true
                path: modelData
                url: App.fileUrl(modelData)
                emptyText: ""
                winActive: root.winActive
                accepts: function (u) { return App.setEditImage(index, u) }
                paste: function () { return App.pasteEditImageAt(index) }
                property string pasteTarget: "edit:" + index
                onHoveredChanged: {
                    if (hovered) root.hoveredWell = pasteTarget
                    else if (root.hoveredWell === pasteTarget) root.hoveredWell = ""
                }
                onPasteTargetChanged: if (hovered) root.hoveredWell = pasteTarget
                Component.onDestruction: {
                    if (root.hoveredWell === pasteTarget) root.hoveredWell = ""
                }
                clearLabel: "[ Remove ]"
                clearAction: function () { App.removeEditImage(index) }
            }
        }
    }

    // Add references below the last used well without reserving a preview.
    FrameWell {
        enabled: !root.comparisonMode
        compact: true
        active: App.editMultipleImages && App.inputImage !== ""
        path: ""
        url: ""
        emptyText: "drag or paste another image here"
        winActive: root.winActive
        accepts: function (u) { return App.addEditImage(u) }
        paste: function () { return App.pasteEditImage() }
        onHoveredChanged: {
            if (hovered) root.hoveredWell = "editadd"
            else if (root.hoveredWell === "editadd") root.hoveredWell = ""
        }
    }
}

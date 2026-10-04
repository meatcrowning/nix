import QtQuick

// Video-only controls.  The panel exists at all only for a `kind: video`
// family (App.isVideo) — the left column follows what the selected model can
// actually do rather than showing controls the graph would ignore.
//
// TWO INDEPENDENT FRAMES. `first_frame` and `last_frame` are both optional
// inputs on the node, so the two toggles are independent: first only, last
// only, both, or neither. With EITHER of them the dropped image decides the
// aspect (the workflow reads the size back out of it after scaling to the pixel
// budget), which is why ResolutionPanel drops to the MP box alone; with neither
// it is plain text-to-video and the normal aspect + MP controls come back.
// Drop the same file in both wells for a clip that loops.
//
// STILL asks for one picture instead of a clip (registry._build_still). Time
// and the frame wells go — a dropped first frame would simply BE the output —
// and ResolutionPanel's aspect comes back; everything else is the same job.
Panel {
    id: panel
    title: "Video"
    readonly property bool still: root.gen.still === true
    badge: still ? "still"
           : App.videoFrames(root.gen.duration) + "f"
             + (root.gen.useInputImage ? " first" : "")
             + (root.gen.useLastFrame ? " last" : "")

    Toggle {
        label: "Still"
        checked: panel.still
        onToggled: function (v) { root.set("still", v) }
    }

    Toggle {
        label: "First Frame"
        visible: !panel.still
        checked: root.gen.useInputImage
        onToggled: function (v) { root.set("useInputImage", v) }
    }

    Toggle {
        label: "Last Frame"
        visible: !panel.still
        checked: root.gen.useLastFrame
        onToggled: function (v) { root.set("useLastFrame", v) }
    }

    PixelText {
        text: panel.still
              ? "  one picture: the first frame of the shortest clip the model makes"
              : "  drop or paste an image in a well below to start from it, end "
                + "on it, or both; neither is text-to-video"
        color: Theme.dim
        width: parent.width
        wrapMode: Text.Wrap
    }

    // Each well says which end it is, because with either toggle able to stand
    // alone the position in the column no longer says it for them.
    PixelText {
        text: "  first frame"
        color: Theme.textDim
        visible: root.gen.useInputImage && !panel.still
    }

    FrameWell {
        active: root.gen.useInputImage && !panel.still
        path: App.inputImage
        url: App.inputImageUrl
        emptyText: "drag or paste the frame to start from here"
        winActive: root.winActive
        accepts: function (u) { return App.setInputImage(u) }
        paste: function () { return App.pasteInputImage() }
        clearAction: function () { App.clearInputImage() }
        // Order-independent: moving straight from one well to the other must
        // not have the leave clear the target the enter just set.
        onHoveredChanged: {
            if (hovered) root.hoveredWell = "input"
            else if (root.hoveredWell === "input") root.hoveredWell = ""
        }
    }

    PixelText {
        text: "  last frame"
        color: Theme.textDim
        visible: root.gen.useLastFrame && !panel.still
    }

    FrameWell {
        active: root.gen.useLastFrame && !panel.still
        path: App.lastImage
        url: App.lastImageUrl
        emptyText: "drag or paste the frame to end on here"
        winActive: root.winActive
        accepts: function (u) { return App.setLastImage(u) }
        paste: function () { return App.pasteLastImage() }
        clearAction: function () { App.clearLastImage() }
        // Order-independent: moving straight from one well to the other must
        // not have the leave clear the target the enter just set.
        onHoveredChanged: {
            if (hovered) root.hoveredWell = "last"
            else if (root.hoveredWell === "last") root.hoveredWell = ""
        }
    }

    Field {
        label: "Duration"
        visible: !panel.still
        hint: "Seconds. The model takes frames in groups, so the count lands on the nearest length it accepts."
        Row {
            spacing: 6
            Spin {
                width: 62
                value: root.gen.duration; from: 0.5; to: 30; step: 0.5; decimals: 1
                onEdited: function (v) { root.set("duration", v) }
            }
            // What that becomes, spelled out — the same honesty the resolution
            // panel's "= WxH" readout owes the size (docs/DESIGN.md §10).
            PixelText {
                text: "= " + App.videoFrames(root.gen.duration) + " frames @" + root.gen.fps
                color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}

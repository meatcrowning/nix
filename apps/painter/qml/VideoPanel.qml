import QtQuick

// Video-only controls.  The panel exists at all only for a `kind: video`
// family (App.isVideo) — the left column follows what the selected model can
// actually do rather than showing controls the graph would ignore.
//
// TWO MODES, ONE TOGGLE. With a first frame this is image-to-video: the
// dropped image decides the aspect (the workflow reads the size back out of it
// after scaling to the pixel budget), which is why ResolutionPanel drops to the
// MP box alone. Without one it is plain text-to-video and the normal aspect +
// MP controls come back.
Panel {
    id: panel
    title: "video"
    badge: App.videoFrames(root.gen.duration) + "f"
           + (root.gen.useInputImage && root.gen.useLastFrame ? " +last" : "")

    Toggle {
        label: "first frame"
        checked: root.gen.useInputImage
        onToggled: function (v) { root.set("useInputImage", v) }
    }

    PixelText {
        text: "  drop an image below for image-to-video; off is text-to-video"
        color: Theme.dim
        width: parent.width
        wrapMode: Text.Wrap
    }

    FrameWell {
        active: root.gen.useInputImage
        path: App.inputImage
        url: App.inputImageUrl
        accepts: function (u) { return App.setInputImage(u) }
    }

    Row {
        spacing: 8
        visible: root.gen.useInputImage && App.inputImage !== ""
        TextButton {
            label: "[ clear ]"
            tone: Theme.textDim
            winActive: root.winActive
            onClicked: App.clearInputImage()
        }
    }

    // THE OTHER END OF THE CLIP. `last_frame` is an optional input on the node,
    // so a second dropped image is one more link, not another graph — the clip
    // is made to arrive at it. Only offered with a first frame: there is nothing
    // to end on in text-to-video. Drop the SAME image in both wells to loop.
    Toggle {
        label: "last frame"
        visible: root.gen.useInputImage
        checked: root.gen.useLastFrame
        onToggled: function (v) { root.set("useLastFrame", v) }
    }

    FrameWell {
        active: root.gen.useInputImage && root.gen.useLastFrame
        path: App.lastImage
        url: App.lastImageUrl
        emptyText: "drag the frame to end on here"
        accepts: function (u) { return App.setLastImage(u) }
    }

    Row {
        spacing: 8
        visible: root.gen.useInputImage && root.gen.useLastFrame && App.lastImage !== ""
        TextButton {
            label: "[ clear ]"
            tone: Theme.textDim
            winActive: root.winActive
            onClicked: App.clearLastImage()
        }
    }

    Field {
        label: "duration"
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

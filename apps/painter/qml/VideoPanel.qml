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

    // The drop target. It highlights while a drag is over it (docs/DESIGN.md
    // §13) and says what it holds afterwards — a target that looks the same
    // empty and full is a target you cannot check.
    Item {
        width: parent.width
        height: root.gen.useInputImage ? 92 : 0
        visible: root.gen.useInputImage
        clip: true

        Rectangle {
            id: well
            anchors.fill: parent
            anchors.topMargin: 4
            color: Theme.bg
            border.width: 1
            border.color: drop.containsDrag ? Theme.accent : Theme.border

            Image {
                id: shot
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 4
                width: height
                source: App.inputImageUrl
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: false
                sourceSize.width: 200
                visible: App.inputImage !== ""
            }

            PixelText {
                anchors.left: shot.visible ? shot.right : parent.left
                anchors.leftMargin: 8
                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideMiddle
                wrapMode: Text.Wrap
                text: App.inputImage === ""
                      ? (drop.containsDrag ? "drop it" : "drag an image here")
                      : App.inputImage
                color: App.inputImage === "" ? Theme.dim : Theme.text
            }

            DropArea {
                id: drop
                anchors.fill: parent
                keys: ["text/uri-list"]
                // NEVER decode a uri-list in QML (docs/DESIGN.md §13) — QUrl does
                // it once, in python, in App.setInputImage.
                onDropped: function (d) {
                    if (d.hasUrls && d.urls.length > 0 && App.setInputImage(d.urls[0]))
                        d.accept()
                }
            }
        }
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

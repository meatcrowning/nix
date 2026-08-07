import QtQuick

// The drop target for ONE video frame. There are two of them now (first frame
// and last frame) and they must not drift apart, so the well is a component
// rather than a copy: it highlights while a drag is over it (docs/DESIGN.md
// §13) and says what it holds afterwards — a target that looks the same empty
// and full is a target you cannot check.
Item {
    id: root_well
    property string path: ""
    property string url: ""
    property bool active: false
    property string emptyText: "drag an image here"
    // NEVER decode a uri-list in QML (docs/DESIGN.md §13) — QUrl does it once,
    // in python, so `accepts` is handed the raw url and answers whether painter
    // could take it. A drop it refused is not accepted, so the drag says no.
    property var accepts: function (url) { return false }

    width: parent ? parent.width : 0
    height: active ? 92 : 0
    visible: active
    clip: true

    Rectangle {
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
            source: root_well.url
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: false
            sourceSize.width: 200
            visible: root_well.path !== ""
        }

        PixelText {
            anchors.left: shot.visible ? shot.right : parent.left
            anchors.leftMargin: 8
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideMiddle
            wrapMode: Text.Wrap
            text: root_well.path === ""
                  ? (drop.containsDrag ? "drop it" : root_well.emptyText)
                  : root_well.path
            color: root_well.path === "" ? Theme.dim : Theme.text
        }

        DropArea {
            id: drop
            anchors.fill: parent
            keys: ["text/uri-list"]
            onDropped: function (d) {
                if (d.hasUrls && d.urls.length > 0 && root_well.accepts(d.urls[0]))
                    d.accept()
            }
        }
    }
}

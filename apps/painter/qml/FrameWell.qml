import QtQuick

// The drop target for ONE video frame. There are three of them now (edit's
// image, the video's first and last frame) and they must not drift apart, so
// the well is a component rather than a copy: it highlights while a drag is
// over it (docs/DESIGN.md §13) and says what it holds afterwards — a target
// that looks the same empty and full is a target you cannot check.
//
// A PASTE puts an image here too, and the well carries both halves of that: the
// `[ paste ]` button, which needs no keyboard and cannot be aimed at the wrong
// well, and `hovered`, which is how Main.qml's Ctrl+V knows which well is
// meant. The pixels come from `paste`, a callback like `accepts`, so nothing
// about the clipboard is decided in QML.
Item {
    id: root_well
    property string path: ""
    property string url: ""
    property bool active: false
    property string emptyText: "drag or paste an image here"
    // NEVER decode a uri-list in QML (docs/DESIGN.md §13) — QUrl does it once,
    // in python, so `accepts` is handed the raw url and answers whether painter
    // could take it. A drop it refused is not accepted, so the drag says no.
    property var accepts: function (url) { return false }
    // Read the clipboard and take what is on it, reporting for itself. Same
    // shape as `accepts`: python owns the decision.
    property var paste: function () { return false }
    // The pointer is over this well — Main.qml aims Ctrl+V with it.
    readonly property alias hovered: hoverH.hovered
    // Chrome greys with the titlebar when the window is unfocused, like every
    // other button here. Threaded in rather than read off the window through
    // QML's dynamic scoping, so the well stays usable outside painter's Main.
    property bool winActive: true

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
            anchors.right: pasteBtn.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideMiddle
            wrapMode: Text.Wrap
            text: root_well.path === ""
                  ? (drop.containsDrag ? "drop it" : root_well.emptyText)
                  : root_well.path
            color: root_well.path === "" ? Theme.dim : Theme.text
        }

        // Always offered, never greyed: whether there is anything to paste is
        // only knowable once the clipboard offer has reached a focused window,
        // so a disabled state here would grey a button that is about to work.
        // Nothing fails silently — an empty clipboard toasts (docs/DESIGN.md §10).
        TextButton {
            id: pasteBtn
            anchors.right: parent.right
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            label: "[ paste ]"
            tone: Theme.textDim
            winActive: root_well.winActive
            onClicked: root_well.paste()
        }

        // Passive: it takes no press, so the drop target and the button below
        // it are untouched.
        HoverHandler { id: hoverH }

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

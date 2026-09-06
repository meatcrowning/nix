import QtQuick
import QtQuick.Controls as QQC

// One picture, filling the window, over the conversation — in an Oxygen session.
//
// IT STAYS AN OVERLAY, not a `Dialog` or a `Popup`, and that is a decision
// rather than an omission:
//
//   * a `Popup` in this window lives in the QQuickWidget's own overlay and
//     cannot leave its rect, so it would occupy exactly the pixels this Item
//     already does — but with a second surround and a second shadow drawn
//     inside a window that already has real KDE chrome. Nothing gained, one
//     more edge;
//   * a Dialog raised as a real WINDOW would be a second titlebar and a second
//     taskbar entry for looking at a picture, and it would break what the
//     lightbox is FOR here: `currentRow` scrolls the conversation behind it as
//     he steps through the set, which is invisible from a separate window;
//   * and the call site (`Root.qml`) reads `opened`, `currentRow` and calls
//     `openAt()` on an Item that fills its parent. A Dialog changes that
//     contract, and a face may not.
//
// So the same object, drawn by the style: the scrim is the style's own window
// brush, the picture sits in a `Frame`, the captions are `Label`s, and the
// three affordances — step back, step on, close — are `ToolButton`s wearing the
// icon theme's `go-previous` / `go-next` / `window-close` instead of a mirrored
// `>` and the word "esc". The fade runs at Oxygen's own
// `GenericAnimationsDuration`, published live by `DeskStyle.styleMs`.
Item {
    id: box

    property string face: "oxygen"

    anchors.fill: parent
    z: 300

    property var entries: []
    property int index: 0
    readonly property var current:
        (entries && index >= 0 && index < entries.length) ? entries[index] : null
    readonly property int count: entries ? entries.length : 0

    signal closed()
    signal contextRequested(string path, real x, real y)

    // Which chat row each entry lives on, parallel to `entries`: stepping
    // through the set takes the log with it, so closing leaves him where the
    // picture is rather than where he opened it.
    property var rows: []
    readonly property int currentRow:
        (rows && index >= 0 && index < rows.length) ? rows[index] : -1

    function openAt(list, i, rowList) {
        entries = list || [];
        rows = rowList || [];
        index = Math.max(0, Math.min(i, (list ? list.length : 1) - 1));
        opened = true;
        forceActiveFocus();
    }
    function close() {
        opened = false;
        closed();
    }
    function step(d) {
        if (count < 2)
            return;
        index = (index + d + count) % count;
    }

    // The style's own numbers: Oxygen's generic animation duration, and its
    // window brush for the scrim. Both fall back to the documented default
    // when no style is publishing (a harness, a stubbed DeskStyle).
    readonly property int oxMs: DeskStyle.styleMs > 0 ? DeskStyle.styleMs : 150
    readonly property color surface: pal.palette.window
    QQC.Label { id: pal; visible: false }

    property bool opened: false
    // `visible` follows the FADE, not the flag, so the overlay stops taking
    // clicks the moment it is gone.
    visible: opacity > 0.001
    enabled: opened
    opacity: opened ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: box.oxMs; easing.type: Easing.InOutQuad }
    }

    focus: opened
    onOpenedChanged: if (opened) forceActiveFocus()
    Keys.onEscapePressed: box.close()
    Keys.onLeftPressed: box.step(-1)
    Keys.onRightPressed: box.step(1)

    // The ground: the style's own window colour at 92%, so the scrim is this
    // session's surface rather than a black sheet.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(box.surface.r, box.surface.g, box.surface.b, 0.92)
        MouseArea {
            anchors.fill: parent
            onClicked: box.close()
        }
    }

    // The picture: fitted to what is left after the caption row, and NEVER
    // upscaled past its own pixels — an enlarged thumbnail that is really a
    // 200px file must look like a 200px file.
    Item {
        id: stage
        anchors { left: parent.left; right: parent.right; top: topBar.bottom
                  bottom: caption.top; margins: 12; topMargin: 6
                  bottomMargin: 6 }

        QQC.Frame {
            id: bigFrame
            anchors.centerIn: parent
            readonly property real inset: leftPadding + rightPadding
            readonly property real vinset: topPadding + bottomPadding
            width: big.width + inset
            height: big.height + vinset
            visible: big.status !== Image.Error && box.current !== null

            contentItem: Item {
                Image {
                    id: big
                    readonly property real natW:
                        (box.current && box.current.w > 0) ? box.current.w
                                                           : stage.width
                    readonly property real natH:
                        (box.current && box.current.h > 0) ? box.current.h
                                                           : stage.height
                    readonly property real scaleFit:
                        Math.min(1,
                                 (stage.width - bigFrame.inset) / Math.max(1, natW),
                                 (stage.height - bigFrame.vinset) / Math.max(1, natH))
                    width: Math.max(1, Math.round(natW * scaleFit))
                    height: Math.max(1, Math.round(natH * scaleFit))
                    sourceSize.width: Math.max(1, Math.round(width))
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    source: box.current ? "file://" + box.current.path : ""
                }
            }

            // Clicking the picture steps forward, so a set can be walked
            // without going back to the grid; clicking the ground closes.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: box.count > 1 ? Qt.PointingHandCursor
                                           : Qt.ArrowCursor
                onClicked: function (m) {
                    if (m.button === Qt.RightButton) {
                        var p = mapToItem(null, m.x, m.y);
                        box.contextRequested(
                            box.current ? (box.current.path || "") : "", p.x, p.y);
                    } else if (box.count > 1) {
                        box.step(1);
                    }
                }
            }
        }

        QQC.Label {
            anchors.centerIn: parent
            visible: big.status === Image.Error || !box.current
            text: "image: could not display"
            color: Theme.crit
        }
    }

    // CLOSE, as the style's own tool button with the theme's own mark. Esc
    // still works; this is the same act with an affordance on it.
    Item {
        id: topBar
        anchors { left: parent.left; right: parent.right; top: parent.top
                  margins: 6 }
        height: closeBtn.height

        QQC.ToolButton {
            id: closeBtn
            anchors.right: parent.right
            icon.name: "window-close"
            display: QQC.AbstractButton.IconOnly
            QQC.ToolTip.visible: hovered
            QQC.ToolTip.text: "close"
            onClicked: box.close()
        }
    }

    // The caption band: the model's alt text, and the position in the set.
    Item {
        id: caption
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  margins: 12 }
        height: Math.max(altText.implicitHeight, posText.implicitHeight)

        QQC.Label {
            id: altText
            anchors { left: parent.left; right: posText.left
                      rightMargin: 10; verticalCenter: parent.verticalCenter }
            wrapMode: Text.Wrap
            text: {
                if (!box.current) return "";
                var a = box.current.alt || "";
                var m = box.current.meta || "";
                return m === "" ? a : (a === "" ? m : a + "\n" + m);
            }
        }
        QQC.Label {
            id: posText
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            visible: box.count > 1
            text: (box.index + 1) + " / " + box.count
            opacity: 0.7
        }
    }

    // Prev/next — the icon theme's own `go-previous` / `go-next`, which is what
    // every other picture viewer in this session steps with. They are absent,
    // not disabled, when there is nothing to step to.
    QQC.ToolButton {
        anchors { left: parent.left; leftMargin: 6
                  verticalCenter: parent.verticalCenter }
        visible: box.count > 1
        icon.name: "go-previous"
        display: QQC.AbstractButton.IconOnly
        QQC.ToolTip.visible: hovered
        QQC.ToolTip.text: "previous"
        onClicked: box.step(-1)
    }
    QQC.ToolButton {
        anchors { right: parent.right; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        visible: box.count > 1
        icon.name: "go-next"
        display: QQC.AbstractButton.IconOnly
        QQC.ToolTip.visible: hovered
        QQC.ToolTip.text: "next"
        onClicked: box.step(1)
    }
}

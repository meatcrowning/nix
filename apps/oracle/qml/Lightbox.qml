import QtQuick
import "../../qmlcommon"

// One picture, filling the window, over the conversation.
//
// [his, 2026-08-23] — "the user can click on one to enlarge it". A tile in
// `ImageGallery` opens this; Escape or a click on the ground closes it, and
// left/right step through the set the tile came from.
//
// It is an OVERLAY, not a window: chatter's chrome is the compositor's (§12)
// and a second window would be a second titlebar, a second entry in the
// switcher and a geometry to remember. So it sits at the top of the scene,
// inside the same Item both roofs mount (Root.qml), and the two faces get it
// alike.
//
// Motion is §6.7 — a composite element fades in as ONE object, at the desk's
// own duration and curve (`Motion`), never a per-widget literal (§6.2). Nothing
// slides, scales or bounces (§6.3): the picture is already where it belongs.
Item {
    id: box

    anchors.fill: parent
    z: 300

    property var entries: []
    property int index: 0
    readonly property var current:
        (entries && index >= 0 && index < entries.length) ? entries[index] : null
    readonly property int count: entries ? entries.length : 0

    signal closed()
    // Right-click on the enlarged picture — Root puts the rows on it.
    signal contextRequested(string path, real x, real y)

    // Which chat row each entry lives on, parallel to `entries`. The lightbox
    // walks the WHOLE conversation now [his, 2026-08-24], so stepping through
    // it also has to take the log with it — Root reads this on `index` and
    // scrolls the reply to the picture being looked at, so closing the
    // lightbox leaves him where the picture is rather than where he opened it.
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

    property bool opened: false
    // `visible` follows the FADE, not the flag, so the fade-out is seen and the
    // overlay stops taking clicks the moment it is gone.
    visible: opacity > 0.001
    enabled: opened
    opacity: opened ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: motion.ms(motion.slideMs)
                          easing.type: motion.slideEasing }
    }
    Motion { id: motion }

    // Focus follows `opened` however it was set — `openAt()` asks for it, and
    // this catches the property being set directly (a harness, a restore).
    // Without it the Keys handlers below are dead: they need ACTIVE focus, not
    // the scope-local `focus` flag.
    focus: opened
    onOpenedChanged: if (opened) forceActiveFocus()
    Keys.onEscapePressed: box.close()
    Keys.onLeftPressed: box.step(-1)
    Keys.onRightPressed: box.step(1)

    // The ground. `bg` at 92% rather than black: the scrim is the window's own
    // surface, so the palette still owns the colour (§3.1).
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.92)
        MouseArea {
            anchors.fill: parent
            onClicked: box.close()
        }
    }

    // The picture: fit to what is left after the caption row, and NEVER
    // upscaled past its own pixels — an enlarged thumbnail that is really a
    // 200px file must look like a 200px file (§1, honesty).
    Item {
        id: stage
        anchors { left: parent.left; right: parent.right; top: parent.top
                  bottom: caption.top; margins: 12; bottomMargin: 6 }

        Image {
            id: big
            anchors.centerIn: parent
            readonly property real natW:
                (box.current && box.current.w > 0) ? box.current.w : stage.width
            readonly property real natH:
                (box.current && box.current.h > 0) ? box.current.h : stage.height
            readonly property real scaleFit:
                Math.min(1, stage.width / Math.max(1, natW),
                         stage.height / Math.max(1, natH))
            width: Math.max(1, Math.round(natW * scaleFit))
            height: Math.max(1, Math.round(natH * scaleFit))
            sourceSize.width: Math.max(1, Math.round(width))
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            source: box.current ? "file://" + box.current.path : ""
        }
        // The frame every surface here wears (§4), drawn AROUND the fitted
        // picture rather than around the stage — so it says where the image
        // ends, which at native size is not the window edge.
        Rectangle {
            anchors.centerIn: big
            width: big.width + 2
            height: big.height + 2
            z: -1
            color: "transparent"
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
        }
        PixelText {
            anchors.centerIn: parent
            visible: big.status === Image.Error || !box.current
            text: "image: could not display"
            color: Theme.crit
        }
        // Clicking the picture itself steps forward, so a set can be walked
        // without going back to the grid; clicking anywhere else closes.
        MouseArea {
            anchors.fill: big
            enabled: box.count > 1
            cursorShape: Qt.PointingHandCursor
            onClicked: box.step(1)
        }
        MouseArea {
            anchors.fill: big
            acceptedButtons: Qt.RightButton
            onClicked: function (m) {
                var p = mapToItem(null, m.x, m.y);
                box.contextRequested(
                    box.current ? (box.current.path || "") : "", p.x, p.y);
            }
        }
    }

    // The caption band: the model's alt text, and the position in the set.
    Item {
        id: caption
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  margins: 12 }
        height: Math.max(altText.height, posText.height)

        PixelText {
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
            color: Theme.text
        }
        PixelText {
            id: posText
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            visible: box.count > 1
            text: (box.index + 1) + " / " + box.count
            color: Theme.textDim
        }
    }

    // Prev/next. ONE glyph, mirrored — `<` is `>` flipped about its own centre
    // (§2.4), on an integer origin so NativeRendering stays crisp under the
    // flip. They stand down when there is nothing to step to.
    Repeater {
        model: box.count > 1 ? 2 : 0
        delegate: Item {
            readonly property int dir: index === 0 ? -1 : 1
            width: 44
            height: box.height
            x: dir < 0 ? 0 : box.width - width
            MouseArea {
                id: arrowHit
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: box.step(dir)
            }
            PixelText {
                anchors.centerIn: parent
                // The flip is about the item's centre; y is rounded by the
                // anchor and x by the integer width above.
                transform: Scale { origin.x: arrowGlyph.width / 2
                                   origin.y: arrowGlyph.height / 2
                                   xScale: dir < 0 ? -1 : 1 }
                id: arrowGlyph
                text: ">"
                color: arrowHit.containsMouse ? Theme.accent : Theme.textDim
            }
        }
    }

    // What closes it, stated once, dim, out of the picture's way (§8.1's
    // register: the fact and nothing else).
    PixelText {
        anchors { right: parent.right; top: parent.top; margins: 12 }
        text: "esc"
        color: Theme.textDim
    }
}

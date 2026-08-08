import QtQuick

// "Pick one of these": a boxed control showing the current choice, which opens
// the app's OWN menu under itself. There is no combo box anywhere on this
// desktop and there should not be one — docs/DESIGN.md §7.2, menus are ours.
//
// It owns no menu. Clicking emits `picked` with the point to open at, in SCENE
// coordinates, and the pane maps that into whatever item its one shared
// CtxMenu fills (§7.3 — one popup at a time). A menu per button would put a
// dozen of them in a rule editor, each clamping against its own 110px box.
//
// filer and player each hold a VERBATIM copy, the CtxMenu rule (apps/AGENTS.md:
// it needs PixelText, which a qmlcommon component cannot reach). Retune both
// or neither.
Item {
    id: root
    property string label: ""
    // Handed in already faded by the owning pane (docs/DESIGN.md §3.1.1).
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    signal picked(real sceneX, real sceneY)

    implicitWidth: 110
    height: 24

    Rectangle {
        anchors.fill: parent
        color: mouse.containsMouse ? Theme.highlight : Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        PixelText {
            anchors {
                left: parent.left; leftMargin: 5
                right: parent.right; rightMargin: 5
                verticalCenter: parent.verticalCenter
            }
            elide: Text.ElideRight
            text: root.label
            color: mouse.containsMouse ? root.fgAccent : root.fgText
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            // Under the button's bottom-left corner, the way a menu opens from
            // the thing it belongs to.
            var p = mapToItem(null, 0, root.height + 1);
            root.picked(p.x, p.y);
        }
    }
}

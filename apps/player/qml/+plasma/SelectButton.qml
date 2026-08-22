import QtQuick
import QtQuick.Controls

// SelectButton, in a Plasma session: a real Button with the style's own menu
// indicator, opening the same shared CtxMenu the Hyprland one does — which in
// this session is the style's own Menu (+plasma/CtxMenu.qml).
//
// NOT a ComboBox, deliberately: the API here is `label` plus a `picked(x, y)`
// signal and the owning pane holds the model, so there is nothing for a
// ComboBox to bind to. The pair (Button + styled Menu) is what a KDE program's
// pick-one-of-N looks like anyway, and it keeps §7.3's one-popup-at-a-time
// rule — a menu per button would put one behind every row of a settings page.
//
// Same API as ../SelectButton.qml, so no call site changes.
Item {
    id: root
    property string face: "plasma"
    property string label: ""
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    signal picked(real sceneX, real sceneY)

    implicitWidth: 110
    implicitHeight: btn.implicitHeight
    height: implicitHeight

    Button {
        id: btn
        anchors.fill: parent
        text: root.label
        // The style draws the little arrow, so the button reads as "opens
        // something" without the app drawing a glyph for it.
        indicator: Text {
            x: btn.width - width - btn.rightPadding
            y: btn.topPadding + (btn.availableHeight - height) / 2
            text: "▾"
            color: btn.palette.buttonText
        }
        onClicked: {
            // Under the button's bottom-left corner, the way a menu opens from
            // the thing it belongs to.
            var p = root.mapToItem(null, 0, root.height + 1);
            root.picked(p.x, p.y);
        }
    }
}

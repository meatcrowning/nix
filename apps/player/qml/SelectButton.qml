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
// THE CHOICES ARE DECLARED, NOT BUILT IN THE HANDLER. `options` is the list —
// `[{ label, value }]`, or bare strings where the two are the same thing — and
// the button hands the owner a ready-made items array along with the point, so
// the owner still opens its one shared menu and the button still owns nothing.
// It was the handler's job until 2026-08-23, and that is what stopped
// `+plasma/SelectButton.qml` being the KStyle's own control: a ComboBox needs a
// MODEL, and a call site that builds its menu inside `onPicked` has none to
// give it. Picking emits `chose(value)`.
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

    // [{ label, value }] or bare strings. `label` above is still what the box
    // SHOWS — the owner binds it to the live setting, so this list never has to
    // say which entry is current.
    property var options: []

    signal picked(real sceneX, real sceneY, var items)
    signal chose(var value)

    // The `options` list as CtxMenu entries, each trigger closing over its own
    // value — which is exactly the thing a for-loop gets wrong, so it is
    // written once here rather than at every call site.
    function menuItems() {
        var out = [], list = root.options || [];
        for (var i = 0; i < list.length; i++) {
            var o = list[i];
            var lab = (o !== null && typeof o === "object" && o.label !== undefined)
                    ? String(o.label) : String(o);
            var val = (o !== null && typeof o === "object" && o.value !== undefined)
                    ? o.value : lab;
            out.push({ label: lab, trigger: (function (v) {
                return function () { root.chose(v); };
            })(val) });
        }
        return out;
    }

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
            root.picked(p.x, p.y, root.menuItems());
        }
    }
}

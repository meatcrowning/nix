import QtQuick
import QtQuick.Controls

// CtxMenu, in a Plasma session: the style's own Menu, built from the same
// `open(x, y, items)` array every call site already passes —
// { label, enabled?, separator?, trigger? }.
//
// A Controls Menu is its own window, so the three things ../CtxMenu.qml has to
// do by hand — clamping into the window, re-parenting above `clip: true` panes,
// and handing the keyboard back to whatever had it — are the toolkit's problem
// here. Same API, so no call site changes (main.py -> select_plasma_files).
Item {
    id: root
    property string face: "plasma"
    property var items: []
    visible: false
    z: 3000

    function open(x, y, list) {
        root.items = list || [];
        menu.popup(root, x, y);
    }
    function close() { menu.close(); }

    Menu {
        id: menu
        Instantiator {
            model: root.items
            onObjectAdded: (i, obj) => menu.insertItem(i, obj)
            onObjectRemoved: (i, obj) => menu.removeItem(obj)
            delegate: MenuItem {
                required property var modelData
                required property int index
                text: modelData.separator === true ? "" : String(modelData.label || "")
                enabled: modelData.separator !== true && modelData.enabled !== false
                // A separator is a THIN row, and it has to be thin in
                // `implicitHeight` too. A popup sizes itself from its delegates'
                // IMPLICIT heights, so overriding only `height` left a whole
                // row's worth of dead space per separator hanging off the BOTTOM
                // of the menu — 47px under painter's prompt-box menu, which
                // carries two. The non-separator branch is Control's own default
                // binding, restated because assigning implicitHeight replaces it.
                implicitHeight: modelData.separator === true ? 8
                    : Math.max(implicitBackgroundHeight + topInset + bottomInset,
                               implicitContentHeight + topPadding + bottomPadding,
                               implicitIndicatorHeight + topPadding + bottomPadding)
                height: implicitHeight
                onTriggered: {
                    if (modelData.separator !== true
                            && typeof modelData.trigger === "function")
                        modelData.trigger();
                }
            }
        }
    }
}

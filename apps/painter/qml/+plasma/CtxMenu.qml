import QtQuick
import QtQuick.Controls

// CtxMenu, in a Plasma session: the style's own Menu, built from the same
// `open(x, y, items)` array every call site already passes —
// { label, enabled?, separator?, trigger? }.
//
// A Controls Menu is its own window, so the two things ../CtxMenu.qml has to do
// by hand — clamping into the window and re-parenting above `clip: true`
// panels — are the toolkit's problem here. Focus restoration is too: a popup
// hands the keyboard back to what had it when it closes, which is the bug that
// section of ../CtxMenu.qml exists to prevent.
Item {
    id: root
    property string face: "plasma"
    property var items: []
    visible: false
    z: 3000

    function open(x, y, list) {
        root.items = list || []
        menu.popup(root, x, y)
    }
    function close() { menu.close() }

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
                height: modelData.separator === true ? 8 : implicitHeight
                onTriggered: {
                    if (modelData.separator !== true
                            && typeof modelData.trigger === "function")
                        modelData.trigger()
                }
            }
        }
    }
}

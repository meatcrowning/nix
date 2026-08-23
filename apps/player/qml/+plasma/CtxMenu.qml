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
//
// A SEPARATOR IS A `MenuSeparator`, not a short empty row. It was one until
// 2026-08-23 — an `Instantiator` can only make ONE delegate type, so a
// separator arrived as a disabled `MenuItem` with no text and a hardcoded 8px
// implicitHeight, i.e. a gap where Oxygen draws an etched line at Oxygen's own
// margins. The menu is therefore built imperatively, from two components, which
// is also what lets the row keep the style's own implicit height instead of
// restating Control's default binding.
Item {
    id: root
    property string face: "plasma"
    property var items: []
    visible: false
    z: 3000

    function open(x, y, list) {
        root.items = list || [];
        root._rebuild();
        menu.popup(root, x, y);
    }
    function close() { menu.close(); }

    // Rebuilt per open rather than bound to the model: every call site here
    // hands in a freshly-built array with closures in it, so there is nothing
    // for an Instantiator's incremental add/remove to preserve. The menu is
    // closed at this point (a call site opens it), so emptying it is safe.
    function _rebuild() {
        while (menu.count > 0) {
            var gone = menu.takeItem(0);
            if (gone)
                gone.destroy();
        }
        for (var i = 0; i < root.items.length; i++) {
            var d = root.items[i];
            var obj = (d && d.separator === true)
                    ? sepComp.createObject(menu)
                    : rowComp.createObject(menu, { entry: d });
            if (obj)
                menu.addItem(obj);
        }
    }

    Menu { id: menu }

    Component { id: sepComp; MenuSeparator { } }
    Component {
        id: rowComp
        MenuItem {
            property var entry: null
            text: entry ? String(entry.label || "") : ""
            enabled: entry ? entry.enabled !== false : false
            onTriggered: {
                if (entry && typeof entry.trigger === "function")
                    entry.trigger();
            }
        }
    }
}

import QtQuick
import QtQuick.Window

// DeskMenuBar renders the app's inner-titlebar button array as a menubar in
// Plasma (`docs/DESIGN.md` §7.4). Hyprland gets hyprvtb's double-wide titlebar;
// Plasma gets the same verbs across the top of the window.
//
// One source, two roofs: the same `tbButtons` array drives both chrome paths,
// and the click handler stays on the window so either surface can call it.
//
// `menu:` only matters here, where the flat column becomes grouped menus. The
// visual rules still follow §7.2, and disabled rows stay visible so the action
// set remains learnable.
Item {
    id: root

    // ---- API -------------------------------------------------------------

    // The app's titlebar button array, verbatim: objects
    // { id, label, state, tip, menu? } and "-" spacers.
    property var buttons: []
    // Where an entry with no `menu:` goes.
    property string defaultMenu: "actions"
    // Left-to-right order of the top-level menus, by name. Menus not listed
    // follow, in the order they first appear in `buttons`. It is a separate
    // property because the ARRAY's order is the titlebar column's, which is a
    // different question — filer's `up` cell leads the column and its `go` menu
    // does not lead the bar.
    property var menuOrder: []
    // A row was chosen: the button's id, exactly as the titlebar reports it.
    signal triggered(string buttonId)

    // THE session switch, and the same one the palette uses (kdetheme.is_plasma
    // -> DeskStyle.plasma). Guarded with typeof so a harness that builds a
    // component without DeskStyle installed gets a 0-height bar, not a
    // ReferenceError.
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

    // AN APP WITH A REAL KDE MENUBAR STANDS THIS ONE DOWN. Where the app's
    // Plasma face is a QMainWindow hosting this QML in a QQuickWidget
    // (pylib/kdeshell.py), the menubar is a genuine QMenuBar painted by the
    // system style from the same `buttons` array — two menubars would be drawn,
    // one of them ours and wrong. Apps still on the QML-only Plasma face leave
    // this false and get the bar below, unchanged.
    property bool systemBar: false
    readonly property bool shown: plasma && !systemBar

    visible: shown
    height: shown ? Math.max(20, Theme.lineHeight + 8) : 0
    // above the window's content, below the apps' own overlays (CtxMenu is at
    // 3000): the bar and its dropdown are chrome, not a modal.
    z: 500

    // ---- the model -------------------------------------------------------

    readonly property var menus: root._order(root._group(root.buttons, root.defaultMenu),
                                             root.menuOrder)

    // Buttons -> [{ name, items: [{ id, label, enabled, on } | { separator }] }]
    function _group(list, fallback) {
        var out = [];
        var index = ({});
        var pendingSep = false;
        for (var i = 0; i < (list ? list.length : 0); i++) {
            var b = list[i];
            if (b === undefined || b === null)
                continue;
            if (typeof b === "string") {     // "-" — the spacer token
                pendingSep = true;
                continue;
            }
            var name = (b.menu !== undefined && b.menu !== "") ? String(b.menu) : fallback;
            var g = index[name];
            if (g === undefined) {
                g = { name: name, items: [] };
                index[name] = g;
                out.push(g);
            }
            // `menuSep: true` asks for a divider ABOVE this entry, in the menu
            // only — filer's column deliberately carries no "-" spacers at all
            // ("the column reads cleaner as one uniform grid"), and `move to
            // trash` still has to sit behind a separator once it is a menu row
            // (§10.3).
            if (b.menuSep === true && g.items.length > 0)
                pendingSep = true;
            if (pendingSep && g.items.length > 0)
                g.items.push({ separator: true, id: "", label: "", enabled: false, on: false });
            pendingSep = false;
            var tip = (b.tip !== undefined && String(b.tip).length > 0) ? String(b.tip)
                                                                       : String(b.label);
            g.items.push({ separator: false, id: String(b.id), label: tip,
                           enabled: Number(b.state) !== 2, on: Number(b.state) === 1 });
        }
        return out;
    }

    // `menuOrder` first, in its order; everything else after, as it came.
    function _order(groups, order) {
        if (!order || order.length === 0)
            return groups;
        var listed = [];
        for (var i = 0; i < order.length; i++)
            for (var j = 0; j < groups.length; j++)
                if (groups[j].name === String(order[i]))
                    listed.push(groups[j]);
        var rest = [];
        for (var k = 0; k < groups.length; k++)
            if (listed.indexOf(groups[k]) < 0)
                rest.push(groups[k]);
        return listed.concat(rest);
    }

    // index of the open menu, -1 for none
    property int openAt: -1
    function close() { root.openAt = -1; }
    // Chosen from a ROW — and the closing has to happen here, in the bar's own
    // scope, not in the row's. `close()` empties the popup's model, which
    // destroys the delegate that is mid-click: the rest of that handler is then
    // abandoned silently, so a `close(); triggered()` pair inside the delegate
    // shut the menu and emitted nothing at all. Measured, not reasoned
    // (pylib/tools/menubar-test.py).
    function choose(buttonId) {
        root.close();
        root.triggered(buttonId);
    }
    // The set changed under an open menu (a tab closed, a mode flipped): the
    // popup is positioned against a title cell that may no longer be the same
    // menu, so shut it rather than redraw somebody else's rows under the
    // pointer.
    onMenusChanged: root.close()
    onPlasmaChanged: root.close()

    // ---- the bar ---------------------------------------------------------

    Rectangle {
        anchors.fill: parent
        visible: root.shown
        color: Theme.bg

        // The seam under the bar, the one line that says the chrome ends here.
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: Theme.ctrlBorder
            color: Theme.border
        }

        Row {
            id: titles
            objectName: "deskMenuTitles"   // pylib/tools/menubar-test.py finds it
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom; leftMargin: 4 }

            Repeater {
                model: root.menus
                delegate: Item {
                    id: titleCell
                    required property var modelData
                    required property int index

                    width: titleText.implicitWidth + 20
                    height: titles.height

                    readonly property bool open: root.openAt === titleCell.index

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 2
                        radius: Theme.rounding
                        color: titleCell.open ? Theme.highlight
                                              : (titleMa.containsMouse ? Theme.highlight : "transparent")
                        opacity: titleCell.open ? 1.0 : (titleMa.containsMouse ? 0.6 : 0)
                    }

                    PixelText {
                        id: titleText
                        anchors.centerIn: parent
                        text: titleCell.modelData.name
                        color: titleCell.open ? Theme.accent : Theme.text
                    }

                    MouseArea {
                        id: titleMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (titleCell.open)
                                root.close();
                            else
                                popup.openFor(titleCell.index, titleCell);
                        }
                        // menubar behaviour everywhere: with one menu down,
                        // sliding along the bar walks the menus.
                        onEntered: if (root.openAt >= 0 && !titleCell.open)
                                       popup.openFor(titleCell.index, titleCell);
                    }
                }
            }
        }
    }

    // ---- the dropdown ----------------------------------------------------

    // Parented to the WINDOW's content item, not to this bar: an item outside
    // its parent's bounds still RENDERS but never receives a click (Qt hit-tests
    // through the parent), which is how a popup hung off a 23px-tall bar ends up
    // visible and dead — measured exactly that way in
    // pylib/tools/menubar-test.py before this was fixed. Same shape the apps'
    // CtxMenu uses: fill the window, put the scrim and the panel inside it.
    //
    // Re-parented imperatively by walking to the top of the item tree, because
    // `Window.contentItem` reads back null under a QQuickView (which is what the
    // harness builds) and a popup that silently stays parented to the bar is the
    // whole bug this comment is about.
    Component.onCompleted: root._attachOverlay()
    onParentChanged: root._attachOverlay()
    function _attachOverlay() {
        var top = root;
        while (top.parent)
            top = top.parent;
        if (top !== root)
            popup.parent = top;
    }

    Item {
        id: popup
        anchors.fill: parent
        visible: root.shown && root.openAt >= 0
        z: 2900

        readonly property var items: (root.openAt >= 0 && root.openAt < root.menus.length)
                                     ? root.menus[root.openAt].items : []

        function openFor(index, cell) {
            root.openAt = index;
            var p = cell.mapToItem(popup, 0, cell.height);
            panel.x = Math.max(4, p.x);
            panel.y = Math.max(0, p.y);
            panel.remeasure();
            panel.clampIntoView();
            focusSink.forceActiveFocus();
        }

        // outside click dismisses and is swallowed — it never reaches the page
        // underneath, which is the CtxMenu rule.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onPressed: root.close()
        }

        Item {
            id: focusSink
            focus: popup.visible
            Keys.onEscapePressed: root.close()
        }

        Rectangle {
            id: panel
            objectName: "deskMenuPanel"    // pylib/tools/menubar-test.py finds it
            // Width tracks the widest row's NATURAL width, remeasured off the
            // delegates' implicitWidth — never bound to the Column's own
            // implicitWidth, which is defined in terms of the rows' actual width
            // and so in terms of this panel (§7's zero-size popup rule: the
            // self-referential version resolves to ~0).
            width: Math.max(1, contentWidth + 2)
            height: Math.max(1, col.implicitHeight + 2)
            color: Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            property real contentWidth: 24
            function remeasure() {
                var w = 24;
                for (var i = 0; i < rows.count; i++) {
                    var it = rows.itemAt(i);
                    if (it && it.implicitWidth > w)
                        w = it.implicitWidth;
                }
                contentWidth = w;
            }
            function clampIntoView() {
                if (x + width > popup.width - 4) x = Math.max(4, popup.width - width - 4);
                if (y + height > popup.height - 4) y = Math.max(4, popup.height - height - 4);
                if (x < 4) x = 4;
                if (y < 0) y = 0;
            }
            onWidthChanged:  if (popup.visible) clampIntoView();
            onHeightChanged: if (popup.visible) clampIntoView();

            Column {
                id: col
                anchors { top: parent.top; left: parent.left; margins: 1 }

                Repeater {
                    id: rows
                    model: popup.items
                    onCountChanged: panel.remeasure()
                    delegate: Item {
                        id: rowItem
                        required property var modelData

                        // implicitWidth is text-derived and drives the panel's
                        // width; the actual width fills the panel so the hover
                        // fill runs edge to edge.
                        implicitWidth: rowItem.modelData.separator ? 24
                                                                   : rowText.implicitWidth + 34
                        width: panel.contentWidth
                        height: rowItem.modelData.separator ? 5 : Math.max(18, Theme.lineHeight + 4)

                        Rectangle {     // separator
                            visible: rowItem.modelData.separator
                            anchors.centerIn: parent
                            width: parent.width - 8
                            height: 1
                            color: Theme.border
                        }

                        Rectangle {     // hover fill — one step LIGHTER (§7.2)
                            anchors.fill: parent
                            visible: !rowItem.modelData.separator && rowMa.containsMouse
                                     && rowItem.modelData.enabled
                            color: Theme.highlight
                        }

                        // The lit gutter: reserved on every row so nothing
                        // shifts when a toggle flips (§5.4).
                        PixelText {
                            id: onMark
                            visible: !rowItem.modelData.separator
                            anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
                            text: rowItem.modelData.on ? "*" : " "
                            color: Theme.accent
                        }

                        PixelText {
                            id: rowText
                            visible: !rowItem.modelData.separator
                            anchors { left: onMark.right; leftMargin: 6; right: parent.right
                                      rightMargin: 10; verticalCenter: parent.verticalCenter }
                            text: rowItem.modelData.label
                            elide: Text.ElideRight
                            color: !rowItem.modelData.enabled ? Theme.inactive
                                   : (rowItem.modelData.on ? Theme.accent : Theme.text)
                        }

                        MouseArea {
                            id: rowMa
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: !rowItem.modelData.separator && rowItem.modelData.enabled
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.choose(rowItem.modelData.id)
                        }
                    }
                }
            }
        }
    }
}

import QtQuick

// "Pick one of N": a boxed value that opens a menu of the options under
// itself — the desktop's dropdown (docs/DESIGN.md §7.2: menus are ours, no
// combo box, no arrow glyph; the box, the hover and the pointer cursor already
// say it is a control). Until 2026-08-08 this was an in-place ‹ › cycler; he
// asked for regular dropdowns, here and in every matching enum control
// desktop-wide (apps/qmlcommon/SelectButton.qml is the app-side face).
//
// Same API as the cycler it replaces, so no call site changed: `options` are
// the values, `labels` optionally maps a value to a display string, `value` is
// two-way and `changed(v)` fires on pick — controlled, the value stays bound
// to the store.
//
// The menu itself is created on demand, parented to the WINDOW's contentItem:
// the settings pages live inside a clipped Flickable, and a child popup would
// be cut off at the viewport edge. Menu spec per §7.2 / TaskMenu.qml: bgAlt
// box, 1px border, kitty-exact text rows, hover fills Theme.highlight (one
// step UP the ladder), lowercase labels; dismissed on pick, outside click,
// Escape, or a 400ms leave timer. The current value's row reads in accent.
Rectangle {
    id: root
    property var options: []          // array of values
    property var labels: ({})         // optional { value: "display" }
    property string value: ""
    // The options ARE font families (the font picker): each menu row — and the
    // closed box — draws its label in the face it names, so the menu is its
    // own specimen sheet. Row heights stay uniform regardless: PixelText pins
    // every line to Theme.lineHeight.
    property bool optionsAreFonts: false
    signal changed(string value)

    function _display(v) { return (labels && labels[v] !== undefined) ? labels[v] : v; }

    // Sized to the value, margins and nothing else — the old 96px floor left
    // a chunk of dead space right of every short value once the label stopped
    // being centred between arrows.
    width: label.implicitWidth + 16
    height: 22
    color: (ma.containsMouse || root._menu) ? Theme.bgAlt : "transparent"
    border.width: 1
    border.color: (ma.containsMouse || root._menu) ? Theme.accent : Theme.border

    PixelText {
        id: label
        anchors { left: parent.left; leftMargin: 8; right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
        elide: Text.ElideRight
        text: root._display(root.value)
        font.family: root.optionsAreFonts && root.value !== "" ? root.value : Theme.font
        color: ma.containsMouse ? Theme.accent : Theme.text
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.openMenu()
    }

    // The open menu overlay, or null. While open, the whole window is covered
    // by the overlay's own MouseArea, so this box cannot be clicked again —
    // an outside click (including on this box) dismisses, like every menu.
    property var _menu: null
    function openMenu() {
        if (_menu || !options.length) return;
        const win = root.Window.window;
        if (!win) return;
        _menu = menuComp.createObject(win.contentItem, { prevFocus: win.activeFocusItem });
    }

    Component {
        id: menuComp
        FocusScope {
            id: overlay
            // Focus is borrowed for Escape and HANDED BACK on dismissal —
            // the settings window quits on Escape (content's handler), and a
            // menu must never leave that dead.
            property Item prevFocus: null
            anchors.fill: parent
            z: 1000
            focus: true
            Component.onCompleted: forceActiveFocus()

            function dismiss() {
                root._menu = null;
                if (prevFocus && prevFocus.forceActiveFocus) prevFocus.forceActiveFocus();
                overlay.destroy();
            }
            Keys.onEscapePressed: dismiss()

            // Outside click dismisses and is SWALLOWED; so is the wheel — the
            // page must not scroll out from under an open menu.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                onClicked: overlay.dismiss()
                onWheel: (w) => { w.accepted = true; }
            }

            Rectangle {
                id: mbox
                // Under the box's bottom-left corner, the way a menu opens
                // from the thing it belongs to — clamped to the window.
                readonly property point at: root.mapToItem(overlay, 0, root.height + 1)
                x: Math.max(0, Math.min(at.x, overlay.width - width))
                y: Math.max(0, Math.min(at.y, overlay.height - height))
                width: Math.max(root.width, col.implicitWidth + 2)
                height: col.implicitHeight + 2
                color: Theme.bgAlt
                border.width: 1
                border.color: Theme.border
                radius: 3

                // Close a beat after the pointer leaves the menu (§7.2).
                HoverHandler {
                    id: hov
                    onHoveredChanged: hovered ? leave.stop() : leave.restart()
                }
                Timer {
                    id: leave
                    interval: 400
                    onTriggered: if (!hov.hovered) overlay.dismiss()
                }

                Column {
                    id: col
                    anchors.fill: parent
                    anchors.margins: 1

                    Repeater {
                        model: root.options
                        Rectangle {
                            id: row
                            required property string modelData
                            width: col.width
                            implicitWidth: rowText.implicitWidth + 20
                            // kitty-exact menu row: the text's own line box,
                            // no padding (§4.1).
                            implicitHeight: rowText.implicitHeight
                            height: implicitHeight
                            color: rma.containsMouse ? Theme.highlight : "transparent"

                            PixelText {
                                id: rowText
                                anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                                textFormat: Text.PlainText
                                text: root._display(row.modelData)
                                font.family: root.optionsAreFonts ? row.modelData : Theme.font
                                // The row you already have reads in accent —
                                // state said in place, not by an extra mark.
                                color: row.modelData === root.value ? Theme.accent : Theme.text
                            }
                            MouseArea {
                                id: rma
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.changed(row.modelData);
                                    overlay.dismiss();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

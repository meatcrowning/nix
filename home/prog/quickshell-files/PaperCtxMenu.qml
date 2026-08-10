import QtQuick

// Shared right-click context menu for a wallpaper/paper tile — one action:
// hide this paper (or unhide it, when "show hidden" is revealing it). Written
// ONCE and used by both surfaces that draw those tiles: the settings paper grid
// (SetPaperGrid.qml) and the Meta+W wallpaper picker (WallpaperPicker.qml). A
// menu offered from more than one place is authored once (docs/DESIGN.md §7.2).
//
// Hiding excludes the paper from BOTH renderers at once; the reveal path is the
// Appearance page's "show hidden papers" toggle, so hiding is never a one-way
// trap (docs/DESIGN.md §10.2). The menu itself follows the §7.2 spec, cribbed
// verbatim from SetSelect.qml's dropdown: a bgAlt box, 1px border, kitty-exact
// text row, hover fills Theme.highlight, lowercase label, dismissed on pick,
// outside click, Escape or a 400ms leave timer.
//
// Like SetSelect, the overlay is parented to the WINDOW's contentItem rather
// than to a tile: in the settings window the grid lives inside a clipped
// Flickable, and a child popup would be cut off at the viewport edge; parenting
// to contentItem also means the menu can never map at a degenerate size the way
// a PopupWindow's positioner can (docs/DESIGN.md §7). This Item carries no size
// and no interactive children of its own — it exists only to resolve
// Window.window and to host the on-demand overlay.
Item {
    id: root
    width: 0
    height: 0

    signal hide(string path)
    signal unhide(string path)

    // The open overlay, or null. One menu at a time (§7.3): a fresh open
    // dismisses the previous.
    property var _menu: null

    // originItem: the tile the pointer is over; localX/localY: the click point
    // within it. The menu opens under the click, clamped to the window.
    function openFor(originItem, path, isHidden, localX, localY) {
        if (_menu)
            _menu.dismiss();
        const win = root.Window.window;
        if (!win || !originItem)
            return;
        const p = originItem.mapToItem(win.contentItem, localX, localY);
        _menu = menuComp.createObject(win.contentItem,
            { atX: p.x, atY: p.y, path: path, isHidden: isHidden });
    }

    Component {
        id: menuComp
        FocusScope {
            id: overlay
            property real atX: 0
            property real atY: 0
            property string path: ""
            property bool isHidden: false

            anchors.fill: parent   // parent is the window's contentItem
            z: 1000
            focus: true
            Component.onCompleted: forceActiveFocus()

            function dismiss() {
                root._menu = null;
                overlay.destroy();
            }
            Keys.onEscapePressed: dismiss()

            // Outside click dismisses and is SWALLOWED; so is the wheel, so the
            // grid/picker cannot scroll out from under an open menu (§7.2).
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                onClicked: overlay.dismiss()
                onWheel: (w) => { w.accepted = true; }
            }

            Rectangle {
                id: mbox
                // Under the click, clamped to the window (never off-screen).
                x: Math.max(0, Math.min(overlay.atX, overlay.width - width))
                y: Math.max(0, Math.min(overlay.atY, overlay.height - height))
                width: Math.max(1, col.implicitWidth + 2)
                height: Math.max(1, col.implicitHeight + 2)
                color: Theme.bgAlt
                border.width: Theme.ctrlBorder
                border.color: Theme.border
                radius: Math.max(3, Theme.windowRounding)

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

                    Rectangle {
                        id: hideRow
                        width: col.width
                        implicitWidth: rowText.implicitWidth + 20
                        // kitty-exact menu row: the text's own line box, no
                        // padding (§4.1).
                        implicitHeight: rowText.implicitHeight
                        height: implicitHeight
                        color: rma.containsMouse ? Theme.highlight : "transparent"

                        PixelText {
                            id: rowText
                            anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                            textFormat: Text.PlainText
                            text: overlay.isHidden ? "unhide" : "hide"
                            color: Theme.text
                        }
                        MouseArea {
                            id: rma
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (overlay.isHidden)
                                    root.unhide(overlay.path);
                                else
                                    root.hide(overlay.path);
                                overlay.dismiss();
                            }
                        }
                    }
                }
            }
        }
    }
}

import QtQuick

// Reusable right-click menu. Deliberately generic — no web/file specifics — so
// filer and the desktop can reuse it verbatim. Populate + show with
// open(x, y, items), where items is a JS array of plain objects:
//   { label, enabled?, separator?, trigger? }
//     separator: true  -> a divider row (other fields ignored)
//     enabled:   false -> greyed, unclickable (default true)
//     trigger:   function called when the row is chosen
// Dismisses on selection, an outside click, or Escape. Give it z above the
// content and anchors.fill of the window so it overlays everything.
Item {
    id: root
    visible: false
    z: 3000

    property var items: []

    // WHOEVER HAD THE KEYBOARD GETS IT BACK — see the same block in the apps'
    // `CtxMenu.qml`. Opening the menu takes the active focus (that is how
    // Escape and the outside-click reach the sink below), so a row that acts on
    // a text box acted on one the keyboard was no longer pointed at.
    property Item prevFocus: null

    function open(x, y, list) {
        root.prevFocus = root.Window.activeFocusItem;
        root.items = list || [];
        panel.x = x;
        panel.y = y;
        root.visible = true;
        panel.remeasure();
        panel.clampIntoView();
        focusSink.forceActiveFocus();
    }
    function close() {
        root.visible = false;
        root.items = [];
        if (root.prevFocus)
            root.prevFocus.forceActiveFocus();
        root.prevFocus = null;
    }

    // outside-click / right-click scrim: dismiss and swallow the event so it
    // never reaches the page underneath.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPressed: root.close()
    }

    Item {
        id: focusSink
        focus: root.visible
        Keys.onEscapePressed: root.close()
    }

    Rectangle {
        id: panel
        // Width tracks the WIDEST row's natural (text-derived) width, remeasured
        // imperatively from the delegates' implicitWidth. It deliberately does
        // NOT bind to col.implicitWidth: a Column derives its own implicitWidth
        // from its children's *actual* width, and each row's width is bound back
        // to this panel (so rows fill it edge-to-edge for the hover highlight).
        // That made the size self-referential — the text-derived width never
        // propagated and the panel collapsed to ~2px ("menu smaller than the
        // cursor"). implicitWidth is text-only and independent of the filled
        // width, so measuring it directly breaks the loop.
        width: contentWidth + 2
        height: col.implicitHeight + 2
        color: Theme.bgAlt
        border.width: 1
        border.color: Theme.windowBorder

        property real contentWidth: 24
        function remeasure() {
            var w = 24;
            for (var i = 0; i < menuRepeater.count; i++) {
                var it = menuRepeater.itemAt(i);
                if (it && it.implicitWidth > w)
                    w = it.implicitWidth;
            }
            contentWidth = w;
        }

        function clampIntoView() {
            if (x + width > root.width - 4) x = Math.max(4, root.width - width - 4);
            if (y + height > root.height - 4) y = Math.max(4, root.height - height - 4);
            if (x < 4) x = 4;
            if (y < 4) y = 4;
        }
        // the panel grows as the rows' text finishes laying out; keep the (now
        // wider/taller) menu fully on-screen as that settles.
        onWidthChanged:  if (root.visible) clampIntoView();
        onHeightChanged: if (root.visible) clampIntoView();

        Column {
            id: col
            anchors { top: parent.top; left: parent.left; margins: 1 }

            Repeater {
                id: menuRepeater
                model: root.items
                onCountChanged: panel.remeasure()
                delegate: Item {
                    id: rowItem
                    required property var modelData
                    // implicitWidth is text-derived and drives the panel width
                    // (via panel.remeasure); actual width fills the panel so the
                    // hover highlight spans edge to edge. The two are decoupled —
                    // implicitWidth never depends on width — so there's no loop.
                    implicitWidth: rowText.implicitWidth + 24
                    width: panel.contentWidth
                    // Row height IS the font's line box (Theme.fontSize; this
                    // pixel font has leading 0, so lineSpacing == fontSize and the
                    // glyph fills the cell exactly) — kitty-exact, one cell per
                    // row with no dead space, vs the old fixed 22px. Separators
                    // keep their small deliberate gap.
                    height: modelData.separator === true ? 7 : Theme.lineHeight
                    onImplicitWidthChanged: panel.remeasure()

                    readonly property bool en: modelData.enabled !== false

                    Rectangle {   // separator
                        visible: rowItem.modelData.separator === true
                        anchors.centerIn: parent
                        width: parent.width - 12
                        height: 1
                        color: Theme.border
                    }

                    Rectangle {   // clickable row
                        visible: rowItem.modelData.separator !== true
                        anchors.fill: parent
                        color: rowMa.containsMouse && rowItem.en ? Theme.highlight : "transparent"

                        PixelText {
                            id: rowText
                            anchors {
                                left: parent.left; leftMargin: 12
                                right: parent.right; rightMargin: 12
                                verticalCenter: parent.verticalCenter
                            }
                            elide: Text.ElideRight
                            text: rowItem.modelData.label || ""
                            color: !rowItem.en ? Theme.inactive
                                 : rowMa.containsMouse ? Theme.accent : Theme.text
                        }

                        MouseArea {
                            id: rowMa
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: rowItem.en
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var t = rowItem.modelData.trigger;
                                root.close();
                                if (t) t();
                            }
                        }
                    }
                }
            }
        }
    }
}

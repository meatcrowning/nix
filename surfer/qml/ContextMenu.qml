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

    function open(x, y, list) {
        root.items = list || [];
        panel.x = x;
        panel.y = y;
        root.visible = true;
        panel.clampIntoView();
        focusSink.forceActiveFocus();
    }
    function close() {
        root.visible = false;
        root.items = [];
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
        width: col.implicitWidth + 2
        height: col.implicitHeight + 2
        color: Theme.bgAlt
        border.width: 1
        border.color: Theme.windowBorder

        function clampIntoView() {
            if (x + width > root.width - 4) x = Math.max(4, root.width - width - 4);
            if (y + height > root.height - 4) y = Math.max(4, root.height - height - 4);
            if (x < 4) x = 4;
            if (y < 4) y = 4;
        }

        Column {
            id: col
            anchors { top: parent.top; left: parent.left; margins: 1 }

            Repeater {
                model: root.items
                delegate: Item {
                    id: rowItem
                    required property var modelData
                    // natural width drives the panel; actual width fills it so
                    // the hover highlight spans edge to edge (no feedback loop:
                    // implicitWidth is text-derived, width flows down from panel)
                    implicitWidth: rowText.implicitWidth + 24
                    width: panel.width - 2
                    height: modelData.separator === true ? 7 : 22

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

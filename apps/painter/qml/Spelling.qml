import QtQuick
import QtQuick.Window
import "../../qmlcommon"

Item {
    id: root
    required property var target
    property var viewport: null
    readonly property bool menuOpen: menu.visible
    anchors.fill: target
    SpellMarks {
        id: marks
        objectName: root.target.objectName + "Spelling"
        anchors.fill: parent
        target: root.target
        replaceFn: (start, end, word) => App.correctSpelling(root.target, start, end, word)
        active: root.enabled
        viewport: root.viewport
        textLeft: root.target.leftPadding || 0
    }
    CtxMenu {
        id: menu
        parent: root.Window.window ? root.Window.window.contentItem : root
        anchors.fill: parent
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onPressed: mouse => {
            root.target.forceActiveFocus()
            var pos = root.target.positionAt(mouse.x, mouse.y)
            var selected = root.target.selectionEnd > root.target.selectionStart
            var items = marks.menuItems(pos).concat([
                {label: "Undo", enabled: root.target.canUndo, trigger: () => root.target.undo()},
                {label: "Redo", enabled: root.target.canRedo, trigger: () => root.target.redo()},
                {separator: true},
                {label: "Cut", enabled: selected, trigger: () => root.target.cut()},
                {label: "Copy", enabled: selected, trigger: () => root.target.copy()},
                {label: "Paste", trigger: () => root.target.paste()},
                {label: "Select All", trigger: () => root.target.selectAll()}
            ])
            var p = mapToItem(menu, mouse.x, mouse.y)
            menu.open(p.x, p.y, items)
        }
    }
}

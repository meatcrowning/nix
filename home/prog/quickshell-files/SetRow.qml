import QtQuick

// One labelled setting: a name (and optional one-line description) on the left,
// its control docked to the right. The control is this item's default child, so
// callers write:  SetRow { label: "..."; SetToggle { ... } }
Item {
    id: root
    property string label: ""
    property string desc: ""
    default property alias control: holder.data

    width: parent ? parent.width : 480
    implicitHeight: Math.max(28, textCol.implicitHeight + 8, holder.childrenRect.height + 8)

    Column {
        id: textCol
        anchors {
            left: parent.left
            right: holder.left
            rightMargin: 14
            verticalCenter: parent.verticalCenter
        }
        spacing: 2
        PixelText {
            width: parent.width
            text: root.label
            color: Theme.text
            elide: Text.ElideRight
        }
        PixelText {
            width: parent.width
            visible: root.desc.length > 0
            text: root.desc
            color: Theme.textDim
            wrapMode: Text.WordWrap
        }
    }

    Item {
        id: holder
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        width: childrenRect.width
        height: childrenRect.height
    }
}

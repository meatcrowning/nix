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
    // A settings row is its text or its control, whichever is taller.  The
    // old +8/minimum-28 box put a blank half-cell above and below every label:
    // process rows do not have that leading, so the two panel surfaces looked
    // as if they were using different fonts even when the glyph metrics
    // matched.  Keep controls' own hit targets intact; this removes only
    // unoccupied layout space.
    implicitHeight: Math.max(Theme.lineHeight, textCol.implicitHeight,
                             holder.childrenRect.height)

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

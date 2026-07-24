import QtQuick

// A titled group of setting rows. Pages are just a stack of these. The title
// sits in an accent rule; children flow in a full-width column below it.
Column {
    id: root
    property string title: ""
    default property alias content: body.data

    width: parent ? parent.width : 480
    spacing: 6

    Item {
        width: parent.width
        height: 20
        PixelText {
            id: t
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: root.title
            color: Theme.accent
        }
        // hairline rule filling the rest of the header line
        Rectangle {
            anchors { left: t.right; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 10 }
            height: 1
            color: Theme.border
        }
    }

    Column {
        id: body
        width: parent.width
        spacing: 2
        // pad the group's rows in a touch from the section rule
        leftPadding: 4
        rightPadding: 4
    }

    // breathing room under each section
    Item { width: parent.width; height: 10 }
}

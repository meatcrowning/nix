import QtQuick

// A titled, collapsible box.  The left column is a stack of these.
Rectangle {
    id: panel
    property string title: ""
    property bool collapsed: false
    property bool collapsible: true
    property string badge: ""
    default property alias content: inner.data

    width: parent ? parent.width : 320
    implicitHeight: header.height + (collapsed ? 0 : inner.childrenRect.height + 14)
    height: implicitHeight
    color: Theme.bgAlt
    border.color: Theme.border
    border.width: 1
    radius: 2
    clip: true

    Item {
        id: header
        width: parent.width
        height: 24

        PixelText {
            id: caret
            visible: panel.collapsible
            x: 6
            anchors.verticalCenter: parent.verticalCenter
            text: panel.collapsed ? "+" : "-"
            color: Theme.dim
        }
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            x: panel.collapsible ? 20 : 8
            text: panel.title
            color: Theme.accent
        }
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 8
            text: panel.badge
            color: Theme.textDim
        }
        MouseArea {
            anchors.fill: parent
            enabled: panel.collapsible
            onClicked: panel.collapsed = !panel.collapsed
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.border
            visible: !panel.collapsed
        }
    }

    Column {
        id: inner
        anchors.top: header.bottom
        anchors.topMargin: 7
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: 5
        visible: !panel.collapsed
    }
}

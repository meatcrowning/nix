import QtQuick

// A titled, collapsible box.  The left column is a stack of these.
Rectangle {
    id: panel
    property string title: ""
    // Collapsed or not is remembered per panel, under this key. A panel without
    // one still collapses; it just forgets (nothing in-tree does that).
    property string persistKey: ""
    property bool collapsed: false
    Component.onCompleted: if (persistKey) collapsed = Prefs.get(persistKey) === true
    onCollapsedChanged: if (persistKey) Prefs.set(persistKey, collapsed)
    property bool collapsible: true
    property string badge: ""
    default property alias content: inner.data

    width: parent ? parent.width : 320
    // A PANEL FOLLOWS ITS CONTENT DOWN AS WELL AS UP. This used to size from
    // `inner.childrenRect.height`, which only ever GREW once a child was
    // hidden: an invisible child keeps the y a Column last positioned it at,
    // and childrenRect still spans to it — so with the negative prompt box
    // hidden (any video or edit family) dragging the positive box SMALLER left
    // the panel at its old height, with a hand-sized blank under the box.
    // Measured offscreen against the real window, his own prefs: box 392 -> 242,
    // panel 435 -> 435. The Column's own `implicitHeight` is the honest number —
    // it is the sum of the children it actually LAYS OUT, so it excludes the
    // hidden ones by construction and tracks both directions.
    implicitHeight: header.height + (collapsed ? 0 : inner.implicitHeight + 14)
    height: implicitHeight
    color: Theme.bgAlt
    border.color: Theme.border
    border.width: 1
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
            id: titleText
            anchors.verticalCenter: parent.verticalCenter
            x: panel.collapsible ? 20 : 8
            text: panel.title
            color: root.fgAccent
        }
        // A BADGE IS NEVER WIDER THAN WHAT IS LEFT. The model panel's badge is a
        // filename, which in a 300px column ran off the edge and out of the
        // panel entirely. Elided in the middle, because the tail of a model name
        // (the quant, the variant) is the half worth keeping.
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.left: titleText.right
            anchors.leftMargin: 10
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideMiddle
            text: panel.badge
            color: Theme.textDim
        }
        MouseArea {
            anchors.fill: parent
            enabled: panel.collapsible
            hoverEnabled: panel.collapsible
            cursorShape: panel.collapsible ? Qt.PointingHandCursor : Qt.ArrowCursor
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

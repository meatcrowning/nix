import QtQuick

// One labelled control row.  Everything in the left pane is built from these so
// the columns line up without each panel re-deciding its own metrics.
Item {
    id: row
    property string label: ""
    property string hint: ""
    property int labelWidth: 96
    default property alias content: holder.data

    width: parent ? parent.width : 240
    height: Math.max(22, holder.childrenRect.height)

    PixelText {
        id: lbl
        text: row.label
        color: Theme.textDim
        width: row.labelWidth
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
    }

    Item {
        id: holder
        anchors.left: lbl.right
        anchors.leftMargin: 6
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: childrenRect.height
    }

    ToolTipArea { text: row.hint; anchors.fill: lbl; enabled: row.hint !== "" }
}

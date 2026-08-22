import QtQuick
import QtQuick.Controls

// Field, in a Plasma session: the same labelled row, with the label drawn as a
// styled Label (system font, the scheme's text colour) and the hint as the
// style's own ToolTip rather than our flyout chip. Layout metrics are shared
// with ../Field.qml on purpose — a KDE form still lines its labels up.
Item {
    id: row
    property string face: "plasma"
    property string label: ""
    property string hint: ""
    property int labelWidth: 96
    default property alias content: holder.data

    width: parent ? parent.width : 240
    height: Math.max(24, holder.childrenRect.height)

    Label {
        id: lbl
        text: row.label
        width: row.labelWidth
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter

        ToolTip.visible: row.hint !== "" && lblHover.hovered
        ToolTip.text: row.hint
        ToolTip.delay: 600
        HoverHandler { id: lblHover }
    }

    Item {
        id: holder
        anchors.left: lbl.right
        anchors.leftMargin: 6
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: childrenRect.height
    }
}

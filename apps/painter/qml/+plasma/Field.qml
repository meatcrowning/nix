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

    // Same pin protocol as ../Field.qml — see the comment there.
    // THE PANEL THIS ROW IS IN, found by walking up rather than by the id
    // `panel` alone: `ParamsPanel.qml` had no such id and every row in the
    // sampling section was quietly unpinnable for it. The id is still the fast
    // path; this is the one that cannot be forgotten.
    function pinHost() {
        if (typeof panel !== "undefined" && panel && panel.pinMenu) return panel
        var p = row.parent
        for (var i = 0; i < 8 && p; i++) {
            if (p.pinMenu !== undefined) return p
            p = p.parent
        }
        return null
    }

    property string pinLabel: row.label
    // The row's value, found by descending into whatever control it holds — a
    // Field's content is usually a Row with a Spin (and a readout) inside it,
    // not the Spin itself, so the first child is rarely the answer.
    function pinValueOf(it, depth) {
        if (!it || depth > 3) return ""
        if (it.value !== undefined) return "" + it.value
        if (it.checked !== undefined) return it.checked ? "on" : "off"
        for (var i = 0; i < it.children.length; i++) {
            var v = row.pinValueOf(it.children[i], depth + 1)
            if (v !== "") return v
        }
        return ""
    }
    readonly property string pinValue:
        row.pinValueOf(holder.children.length > 0 ? holder.children[0] : null, 0)

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

    MouseArea {
        anchors.fill: lbl
        acceptedButtons: Qt.RightButton
        // A MENU, not a silent toggle. Right-clicking a label used to pin it
        // outright, which is an action with no name, no undo you could see and
        // nothing anywhere saying it existed — docs/DESIGN.md §10. The menu is
        // how you find out the row can be pinned at all.
        onClicked: function (m) {
            var host = row.pinHost()
            if (!host) return
            var pt = mapToItem(null, m.x, m.y)
            host.pinMenu(row, pt.x, pt.y)
        }
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

import QtQuick

// One labelled control row.  Everything in the left pane is built from these so
// the columns line up without each panel re-deciding its own metrics.
Item {
    id: row
    property string label: ""
    property string hint: ""
    property int labelWidth: 96
    default property alias content: holder.data

    // PINNING (docs/painter-kde-layout.md phase 7). Right-click a row's label to
    // pin it: the value then keeps showing in the panel's header while the
    // panel is COLLAPSED, so a folded panel can still say the one number you
    // care about. `pinLabel` is the row's identity in the panel's saved pin
    // list; `pinValue` is read off whatever control the row holds, so a row
    // does not have to be told how to summarise itself.
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

    // Right button only, so the tooltip's hover and any left-click inside the
    // control are untouched. `panel` is the enclosing Panel's id, which QML
    // resolves up the creation-context chain — the same way every row in here
    // already reaches `root`.
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
}

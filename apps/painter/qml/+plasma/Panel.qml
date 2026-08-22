import QtQuick
import QtQuick.Controls

// Panel, in a Plasma session: a real GroupBox — the frame KDE's own
// configuration pages are built from, drawn by the style (under Oxygen: the
// rounded, softly-shadowed group frame, over the window gradient rather than
// over a flat fill).
//
// Collapsing is not a GroupBox feature and is painter's own, so it stays: the
// title row carries a flat expander button with the style's arrow icons, and
// the content's height goes to zero. Same API as ../Panel.qml — title,
// persistKey, collapsed, collapsible, badge, default content — so no call site
// changes.
GroupBox {
    id: panel
    property string face: "plasma"
    // `title` is GroupBox's own and is FINAL — declaring it again is a load
    // error, and it means the same thing here anyway, so callers' `title:` goes
    // straight through.
    property string persistKey: ""
    property bool collapsed: false
    Component.onCompleted: if (persistKey) collapsed = Prefs.get(persistKey) === true
    onCollapsedChanged: if (persistKey) Prefs.set(persistKey, collapsed)
    property bool collapsible: true
    property string badge: ""
    default property alias content: inner.data

    width: parent ? parent.width : 320
    clip: true

    // THE HEADER'S implicitWidth IS THE ROW'S, never the panel's. A GroupBox
    // derives its own implicitWidth from its label, these panels sit in a
    // Column whose implicitWidth is its widest child, and the panel's width
    // follows that Column — so a label that measured itself from `panel.width`
    // closed the loop and Qt said so, ten times at load. The badge still spans
    // the header: it takes panel.width for its own WIDTH, which nothing
    // measures back.
    label: Item {
        implicitHeight: Math.max(row.implicitHeight, 24)
        implicitWidth: row.implicitWidth
        Row {
            id: row
            spacing: 4
            anchors.verticalCenter: parent.verticalCenter
            ToolButton {
                visible: panel.collapsible
                icon.name: panel.collapsed ? "arrow-right" : "arrow-down"
                onClicked: panel.collapsed = !panel.collapsed
                // Sized down from the style's default: a 30px tool button makes
                // every FOLDED panel a 52px band with nothing in it.
                padding: 0
                implicitWidth: 18
                implicitHeight: 18
                icon.width: 14
                icon.height: 14
                anchors.verticalCenter: parent.verticalCenter
            }
            Label {
                text: panel.title
                anchors.verticalCenter: parent.verticalCenter
                font.bold: true
            }
        }
        // The badge is the panel's one-line summary (the model filename, the
        // resolution). Elided in the MIDDLE like ours: the tail of a model name
        // is the half worth keeping.
        Label {
            anchors.left: row.right
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: panel.badge
            elide: Text.ElideMiddle
            opacity: 0.7
            width: Math.max(0, panel.width - row.implicitWidth - panel.leftPadding
                               - panel.rightPadding - 12)
            horizontalAlignment: Text.AlignRight
        }
    }

    // A whole-panel click still folds it, as ours does.
    TapHandler {
        enabled: panel.collapsible && panel.collapsed
        onTapped: panel.collapsed = false
    }

    // A COLUMN, exactly as ../Panel.qml's inner is — every caller stacks bare
    // Fields inside a panel and relies on it. A plain Item here lays them all
    // at y=0: the resolution panel's two rows drew on top of each other.
    // Its own implicitHeight is also the honest one when a child is hidden
    // (a Column excludes what it does not lay out, childrenRect does not), which
    // is the sizing trap ../Panel.qml records at length.
    // ...AND `contentHeight` IS WHAT COLLAPSES IT, not the content item's
    // implicit height. A GroupBox is a Pane, and a Pane whose content item has
    // implicitHeight 0 does NOT read that as "no content" — it falls back to
    // measuring the item's children, which are still there, merely invisible.
    // So a collapsed panel kept a 52px empty box under its header. Stating the
    // content height leaves nothing to fall back to.
    contentHeight: panel.collapsed ? 0 : inner.implicitHeight

    contentItem: Item {
        implicitHeight: panel.collapsed ? 0 : inner.implicitHeight
        implicitWidth: inner.implicitWidth

        Column {
            id: inner
            width: parent.width
            spacing: 5
            visible: !panel.collapsed
        }
    }
    // COLLAPSED GIVES BACK THE PADDING BELOW, AND ONLY THAT. The style's
    // topPadding is not decoration: it is the room the LABEL sits in. Zeroing
    // it too made a collapsed panel `implicitHeight` 0 — no content, no
    // padding, and therefore no header either — so the panel vanished and
    // there was no longer anything to click to get it back. That cost the
    // Plasma face its model selector and its sampling panel, both of which
    // start collapsed. Only the bottom padding is the panel's to give back.
    Binding {
        target: panel; property: "bottomPadding"; value: 0
        when: panel.collapsed; restoreMode: Binding.RestoreBindingOrValue
    }
}

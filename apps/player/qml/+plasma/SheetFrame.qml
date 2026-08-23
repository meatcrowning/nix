import QtQuick
import QtQuick.Controls

// SheetFrame, in a Plasma session: the KStyle's own `Pane` — its background
// brush, its frame, its relief — rather than a `Theme.bg` rectangle wearing a
// border we derive from the colour scheme ourselves.
//
// `Pane` and not `Frame`: a sheet has to OCCLUDE the list behind it, and Pane
// is the QQC2 control whose whole job is an opaque styled surface. Its padding
// is zeroed because the sheet's own 12px margins are inside the content, where
// both faces already put them — the Item below is exactly the wrapper's
// rectangle in both, so nothing inside a sheet knows which face it is in.
Item {
    id: root
    property string face: "plasma"
    default property alias content: inner.data

    Pane {
        anchors.fill: parent
        padding: 0
    }

    Item { id: inner; anchors.fill: parent }
}

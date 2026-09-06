import QtQuick
import QtQuick.Controls

// The attachment chip in a Plasma session: a real Button carrying the file's
// name and the style's own "remove" icon, drawn by the KStyle through
// qqc2-desktop-style rather than imitated (apps/AGENTS.md → kdeshell).
//
// Same API as ../Chip.qml — `label`, `removed()` — so the call site is
// untouched; the file selector picks between the two.
Button {
    id: root
    property string face: "plasma"   // how a harness proves the swap happened
    property string label: ""
    signal removed()

    text: root.label
    icon.name: "edit-delete-remove"
    icon.color: palette.buttonText
    // A chip is not a command button: it is the file, with a way to take it
    // back. Flat is the KStyle's word for that.
    flat: true
    onClicked: root.removed()
}

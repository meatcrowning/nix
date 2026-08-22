import QtQuick
import QtQuick.Controls

// TextButton, in a Plasma session: a real Button, painted by the KDE style
// (qqc2-desktop-style renders it THROUGH the live QStyle, so under Oxygen this
// is Oxygen's own button — its bevel, its hover glow, its focus ring).
//
// Same API as ../TextButton.qml, so no call site changes. Two differences that
// are deliberate rather than accidental:
//
//   * THE BRACKETS COME OFF. Callers write painter's "[ start ]" idiom, which
//     is this desktop's way of saying "this text is clickable" where there is
//     no button frame. A KDE button HAS a frame, and the brackets inside one
//     read as punctuation somebody forgot to delete.
//   * `lit` becomes `checked`, which is what a KDE toggle button is: the style
//     draws it sunken, in the scheme's own colours. `tone` has no equivalent
//     and is ignored — a KDE button does not colour its own label.
Item {
    id: root
    property string face: "plasma"
    property string label: ""
    property color tone: "transparent"
    property bool lit: false
    property bool winActive: true
    property bool flipY: false
    signal clicked()

    implicitWidth: btn.implicitWidth
    implicitHeight: btn.implicitHeight
    width: implicitWidth
    height: implicitHeight

    Button {
        id: btn
        anchors.fill: parent
        text: String(root.label).replace(/^\s*\[\s*/, "").replace(/\s*\]\s*$/, "")
        enabled: root.enabled
        checkable: root.lit
        checked: root.lit
        onClicked: root.clicked()
        // The mirrored-glyph trick is a pixel-font problem (docs/DESIGN.md §2.4)
        // and does not exist here: the system font's "^" and "v" are drawn by
        // the same rasteriser at the same height. Kept as a property so the API
        // matches; applied as a rotation only if a caller sets it.
        transform: Scale {
            yScale: root.flipY ? -1 : 1
            origin.x: btn.width / 2
            origin.y: Math.round(btn.height / 2)
        }
    }
}

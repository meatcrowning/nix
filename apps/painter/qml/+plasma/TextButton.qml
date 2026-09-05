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
    // The compact capsule a panel header uses instead of the words. A KDE
    // button keeps its frame here — only the label is replaced by the icon,
    // so it still reads as a button in this session.
    property bool pillIcon: false
    signal clicked()

    // SIZED LIKE PAINTER'S OWN ROWS, not like a dialog button. A KDE button's
    // implicit size carries the style's minimum (measured 100x40 under
    // qqc2-desktop-style), which in a 24px panel header does not fit at all and
    // in a prompt pill leaves a finger of empty space after every label. The
    // frame is still the style's; only the box it is asked to fill is ours.
    implicitWidth: root.pillIcon ? 22 : Math.max(22, Math.ceil(tm.width) + 14)
    implicitHeight: Theme.lineHeight + 5

    TextMetrics {
        id: tm
        font: btn.font
        text: btn.text
    }
    width: implicitWidth
    height: implicitHeight

    Button {
        id: btn
        visible: !root.pillIcon
        anchors.fill: parent
        padding: 1
        leftPadding: 6
        rightPadding: 6
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

    Button {
        id: pill
        visible: root.pillIcon
        anchors.fill: parent
        padding: 1
        enabled: root.enabled
        checkable: root.lit
        checked: root.lit
        onClicked: root.clicked()
        contentItem: Item {
            implicitWidth: 14
            implicitHeight: 8
            Rectangle {
                anchors.centerIn: parent
                width: 12
                height: 6
                radius: 3
                color: pill.checked ? pill.palette.highlight : "transparent"
                border.width: 1
                border.color: pill.enabled ? pill.palette.buttonText
                                           : pill.palette.mid
            }
        }
    }
}

import QtQuick

// The context-window meter: a track with a proportional fill that warns as it
// approaches full (docs/DESIGN.md §9 meter, §4 corners, §6 motion).
//
// A component rather than two Rectangles in Root.qml so the stats row reads as
// one line of parts. It has NO Plasma twin on purpose — see the call site in
// Root.qml: the style's own ProgressBar paints nothing inside our QQuickWidget,
// and this is a readout in the content, not a widget. API: `frac` (0..1).
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property real frac: 0

    implicitWidth: 88
    implicitHeight: 6
    radius: Theme.rounding
    color: Theme.bgAlt
    border.width: Theme.ctrlBorder
    border.color: Theme.border

    Rectangle {
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom
                  margins: 1 }
        width: Math.max(0, (root.width - 2) * root.frac)
        radius: Theme.rounding
        color: root.frac > 0.9 ? Theme.crit
               : root.frac > 0.75 ? Theme.warn : Theme.accent
        Behavior on width {
            NumberAnimation { duration: motion.ms(motion.slideMs)
                              easing.type: motion.slideEasing }
        }
    }
}

import QtQuick

// The flickable scroller, in a Plasma session wearing OXYGEN.
//
// NOTHING HERE IS KINETIC, and the name is kept only so no call site changes.
// The type keeps its sibling's whole API — model/delegate/header/section,
// `positionViewAtIndex`, `ScrollBar.vertical`, and the four `wheel*` aliases —
// and its two structural decisions, which are the RIGHT desktop behaviour under
// this roof rather than a workaround for the other one:
//
//   • `interactive: false`. Under Hyprland that is there to stop Qt's own flick
//     fighting the compositor's decay curve (measured +43% overshoot on a 240px
//     coast — see `../WheelScroll.qml`). Under KDE there is no compositor
//     momentum to fight; press-and-drag inside a view SELECTS, and a list that
//     threw itself when you dragged a row would be the surprise. Same setting,
//     and for once the honest reason.
//   • `StopAtBounds`. No rubber-band overshoot: Oxygen's views end where their
//     content ends.
//
// So the scroll is the scrollbar and the wheel, and both are the style's: the
// bar is `+oxygen/VScroll.qml` (a real `ScrollBar` painted by Oxygen's own
// QStyle, at its own `ScrollBarWidth` with its own asymmetric add/sub-line
// chevrons) and the wheel is `+oxygen/WheelScroll.qml`, which moves three lines
// of the SESSION font per detent and adds no momentum of its own. Both resolve
// through the selector, so this file names them exactly as its sibling does.
Flickable {
    id: view

    property string face: "oxygen"

    interactive: false                          // scrollbar + wheel only
    boundsBehavior: Flickable.StopAtBounds

    property alias wheelLines: wheel.lines      // rows per classic wheel detent
    property alias wheelStep: wheel.step        // px per row
    property alias wheelGain: wheel.gain
    property alias wheelEnabled: wheel.enabled  // false = let the wheel bubble out
    signal wheelScrolled()                      // after contentY actually moved

    // NO anchors, and the reparent runs from Component.onCompleted — the
    // sibling's constraint, unchanged and for its own reason: a plain Flickable moves declared child Items into its contentItem
    // AFTER a binding on `parent` is applied, so `parent: view` alone can lose
    // the race ("Cannot anchor to an item that isn't a parent or sibling") and
    // leave the overlay scrolling away with the content. Explicit geometry
    // bindings survive the reparent; anchors would not.
    WheelScroll {
        id: wheel
        // BEHIND the content (`z: -1`), so whatever is IN the view sees the
        // wheel first and only an unaccepted notch falls through to here. The
        // reparent makes this a SIBLING of the view's contentItem, appended
        // after it, which at the default z would shadow every inner wheel
        // handler — measured, an inner MouseArea went from 5/5 events to 0/5.
        z: -1
        x: 0
        y: 0
        width: view.width
        height: view.height
        view: view
        onScrolled: view.wheelScrolled()
        Component.onCompleted: parent = view
    }
}

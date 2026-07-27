import QtQuick

// A ListView that honours the compositor's kinetic momentum BY CONSTRUCTION.
// Use this instead of a bare `ListView` in every app under apps/ — see
// WheelScroll.qml for why (Qt's own flick fights the compositor's decay curve;
// measured +43% overshoot on a 240px coast).
//
// It is a plain ListView with Qt flicking off and one WheelScroll overlay
// wired to itself, so everything else — model, delegate, header, section,
// positionViewAtIndex, ScrollBar.vertical — behaves exactly as before.
ListView {
    id: view

    interactive: false                          // scrollbar + wheel only
    boundsBehavior: Flickable.StopAtBounds

    property alias wheelLines: wheel.lines      // rows per classic wheel detent
    property alias wheelStep: wheel.step        // px per row
    property alias wheelGain: wheel.gain         // only surfer sets this
    property alias wheelEnabled: wheel.enabled   // false = let the wheel bubble out
    signal wheelScrolled()                      // after contentY actually moved

    // NO anchors, and the reparent runs from Component.onCompleted: a view's
    // default property moves declared child Items into its contentItem AFTER a
    // binding on `parent` is applied, so `parent: view` alone can lose the race
    // ("Cannot anchor to an item that isn't a parent or sibling") and leave the
    // overlay scrolling away with the content. Explicit geometry bindings
    // survive the reparent; anchors would not.
    WheelScroll {
        id: wheel
        x: 0
        y: 0
        width: view.width
        height: view.height
        view: view
        onScrolled: view.wheelScrolled()
        Component.onCompleted: parent = view
    }
}

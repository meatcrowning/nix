import QtQuick

// Plain-Flickable half of the set (scrolling a Column, a TextEdit, a long
// PixelText) — see KineticListView.qml and WheelScroll.qml.
Flickable {
    id: view

    interactive: false                          // scrollbar + wheel only
    boundsBehavior: Flickable.StopAtBounds

    property alias wheelLines: wheel.lines
    property alias wheelStep: wheel.step
    property alias wheelGain: wheel.gain
    property alias wheelEnabled: wheel.enabled   // false = let the wheel bubble out
    signal wheelScrolled()

    // NO anchors, and the reparent runs from Component.onCompleted: a plain
    // Flickable moves declared child Items into its contentItem AFTER the
    // binding on `parent` is applied, so `parent: view` alone loses the race
    // ("Cannot anchor to an item that isn't a parent or sibling") and the
    // overlay ends up scrolling away with the content. Explicit geometry
    // bindings survive the reparent; anchors would not.
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

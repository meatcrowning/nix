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
        // BEHIND the content, not on top of it. The reparent below makes this a
        // SIBLING of the view's `contentItem`, appended after it — so at the
        // default z it is the topmost item over the whole viewport and it sees
        // every wheel FIRST. That silently shadowed every inner wheel handler
        // the moment these types replaced the bare Flickables: measured
        // offscreen, an inner MouseArea nested in the content went from 5/5
        // wheel events to 0/5. painter's left column is the case that matters —
        // its Spin steppers, the model/LoRA lists, an open Picker dropdown and
        // both PromptBox editors all live inside one KineticFlickable, and all
        // of them stopped responding to the wheel while the column could
        // scroll. `z: -1` restores the ordinary rule: whatever is in the
        // content gets the wheel, and anything that declines it (a delegate
        // with no `onWheel`, or a nested WheelScroll with nothing left to
        // scroll — it leaves those unaccepted on purpose) falls through to
        // here. Verified both ways offscreen: inner present -> 5/5 inner,
        // 0 here; inner absent -> 5/5 here, and a plain delegate MouseArea
        // still scrolls the list.
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

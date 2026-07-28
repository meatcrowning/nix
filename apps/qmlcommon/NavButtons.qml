// NavButtons — the mouse's back/forward side buttons, in one place.
//
// DESKTOP-GLOBAL rule (docs/DESIGN.md §11): *"back and forward mouse buttons should
// function in every program. takes the user back and foreward"* — so this is
// not a per-app feature to be re-implemented six times. Drop one of these in as
// a child of a window's root item and wire `onBack` / `onForward`:
//
//     NavButtons {
//         onBack:    win.pane.goBack()
//         onForward: win.pane.goForward()
//     }
//
// Only Qt.BackButton / Qt.ForwardButton (evdev BTN_SIDE 275 / BTN_EXTRA 276,
// which the Logitech ERGO M575 does emit) are accepted, so every other press,
// every wheel notch and every hover still falls through to whatever is really
// under the cursor — including MouseAreas that use `preventStealing`. That is
// why this can sit at a very high z without breaking anything below it.
//
// Placement: it must be a sibling of the content it covers, not a wrapper. The
// high z is what makes it work from anywhere in the window, which is the point
// — the buttons mean the same thing wherever the pointer happens to be.
import QtQuick

MouseArea {
    id: nav

    anchors.fill: parent
    z: 9000
    acceptedButtons: Qt.BackButton | Qt.ForwardButton

    signal back()
    signal forward()

    onClicked: function (mouse) {
        if (mouse.button === Qt.BackButton)
            nav.back();
        else
            nav.forward();
    }
}

// NavButtons — the mouse's back/forward side buttons, panel-side.
//
// DESKTOP-GLOBAL rule (docs/DESIGN.md §11): *"back and forward mouse buttons should
// function in every program. takes the user back and foreward"*. The panel is
// the fourth codebase on this desktop and cannot import `apps/qmlcommon/` — its
// QML is Quickshell's and is deployed to `~/.config/quickshell` — so this is a
// deliberate parallel copy of `apps/qmlcommon/NavButtons.qml`, exactly like
// `PixelText.qml` and `Kinetic.qml`. Change one, change the other.
//
// Only Qt.BackButton / Qt.ForwardButton (evdev BTN_SIDE 275 / BTN_EXTRA 276)
// are accepted, so every other press, every wheel notch and every hover falls
// through to whatever is really under the cursor. That is what lets it sit at a
// very high z without breaking anything below it.
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

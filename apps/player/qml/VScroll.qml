import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// Slim vertical scrollbar, copied from filer's VScroll so all the siblings
// scroll the same way: only visible when the view overflows (size < 1) — the
// handle stays put at rest, brightening on hover/drag; accent while pressed.
ScrollBar {
    id: vb
    // Hover feedback, not a slide: 120ms is the desktop's scrollbar/hover fade
    // and stays. What was missing is the CURVE — both Behaviors declared no
    // easing at all, i.e. Linear, against a house style that is OutCubic in 25
    // of 30 declarations. Going through motion.ms() is also what makes the
    // panel's reduceMotion / animSpeed settings reach these.
    Motion { id: motion }
    policy: ScrollBar.AsNeeded
    width: 9
    contentItem: Rectangle {
        implicitWidth: 9
        color: vb.pressed ? Theme.accent : Theme.textDim
        opacity: vb.size < 1 ? (vb.active ? 0.9 : 0.5) : 0
        Behavior on opacity { NumberAnimation { duration: motion.ms(120); easing.type: motion.slideEasing } }
    }
    background: Rectangle {
        color: Theme.bgAlt
        opacity: vb.size < 1 && vb.active ? 0.4 : 0
        Behavior on opacity { NumberAnimation { duration: motion.ms(120); easing.type: motion.slideEasing } }
    }
}

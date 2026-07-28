import QtQuick

// USE THIS in the `onWheel` of every DISCRETE control in apps/ — anything whose
// wheel handler STEPS a value rather than scrolling content (painter's numeric
// Spin boxes). Content scrollers take WheelScroll.qml instead; the two are
// different jobs and docs/DESIGN.md §9.2 keeps them apart on purpose: "Discrete
// steppers stay notch-based ... a coast that walks brightness to 0 is a bug."
//
//     MouseArea {
//         WheelNotch { id: notch }
//         onWheel: function (w) { var n = notch.steps(w); if (n) doThing(n); }
//     }
//
// This is the apps-side twin of home/prog/quickshell-files/WheelNotch.qml —
// same algorithm, same constants, two roofs (that tree's QML is Quickshell's,
// this is plain Qt), exactly like WheelScroll.qml is the twin of Kinetic.qml.
// Retune one and retune the other.
//
// THE UNIT. Both branches of Qt's wheel event reduce to the same scale, so
// there is no detent discriminator to get wrong: a real wheel click is
// angleDelta 120 with pixelDelta 0, and QtWayland sets angleDelta = 12 x the
// surface-pixel delta for high-resolution sources (apps/pylib/kinetic.py's
// DETENT and ANGLE_PER_PIXEL — the Python half of the same seam). So accumulate
// angle units, preferring pixelDelta * 12 when it is non-zero (it is the
// unrounded truth; angleDelta is what got rounded), and emit one step per
// detent. One physical wheel click is exactly one step; ~10px of finger travel
// is also one step, and everything smaller is CARRIED, never dropped and never
// rounded up to a full step.
QtObject {
    id: root

    // Wire-level constants, fixed by the Wayland/Qt seam, not tunables.
    readonly property int detent: 120        // one classic mouse-wheel notch
    readonly property int anglePerPixel: 12  // QtWayland: angleDelta = 12 x surface px

    // angleDelta units per emitted step. Raise it to make a control coarser.
    property real perNotch: root.detent
    // Hard ceiling on steps returned from ONE event, so no burst — synthetic,
    // replayed or a compositor-synthesized momentum coast — can run a value
    // across its whole range in a single frame. The remainder is discarded.
    property int maxSteps: 3

    property real accum: 0

    // Whole notches completed by this event, signed. 0 most of the time on a
    // touchpad: that is the point — the sub-notch remainder is carried.
    function steps(wheel) {
        var pd = wheel.pixelDelta ? wheel.pixelDelta.y : 0;
        var units = pd !== 0 ? pd * root.anglePerPixel
                             : (wheel.angleDelta ? wheel.angleDelta.y : 0);
        if (units === 0)
            return 0;                       // zero-delta events are no-ops
        // Reversing direction starts a fresh notch rather than first paying
        // back what the other direction had banked.
        if (units * root.accum < 0)
            root.accum = 0;
        root.accum += units;
        var n = Math.trunc(root.accum / root.perNotch);
        if (n === 0)
            return 0;
        root.accum -= n * root.perNotch;
        return Math.max(-root.maxSteps, Math.min(root.maxSteps, n));
    }
}

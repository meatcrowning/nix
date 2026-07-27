import QtQuick

// USE THIS in the `onWheel` of every DISCRETE control in the panel — anything
// whose wheel handler steps a value (volume, brightness) or spawns a process,
// rather than scrolling content. Declare one inside the MouseArea and ask it
// how many whole notches an event completed:
//
//     MouseArea {
//         WheelNotch { id: notch }
//         onWheel: (wheel) => { var n = notch.steps(wheel); if (n) doThing(n); }
//     }
//
// WHY A SIGN TEST IS NOT ENOUGH. `if (wheel.angleDelta.y > 0) stepUp()` treats
// every event as one full step, and on a touchpad that stream is ~125 Hz of
// events whose individual deltas are a fraction of a pixel — measured in the
// player, 226 of 413 events in one gesture carried pixelDelta 0. A two-finger
// nudge over the bar's "vol" therefore fired dozens of 5 % steps and spawned a
// wpctl per event. It is also the exact shape that a compositor-synthesized
// momentum coast would turn into a burst of forty steps, which is why hyprvtb
// refuses to coast over layer surfaces at all (Kinetic.qml explains).
//
// THE UNIT. Both branches of Qt's wheel event reduce to the same scale, so
// there is no detent discriminator to get wrong here: a real wheel click is
// angleDelta 120 with pixelDelta 0, and QtWayland sets angleDelta = 12 * the
// surface-pixel delta for high-resolution sources. So accumulate angle units,
// preferring pixelDelta*12 when it is non-zero (it is the unrounded truth;
// angleDelta is what got rounded), and emit a step per Kinetic.detent. One
// physical wheel click is exactly one step, unchanged from before; 10 px of
// finger travel is also one step.
QtObject {
    id: root

    // angleDelta units per emitted step. Raise it to make a control coarser.
    property real perNotch: Kinetic.detent
    // Hard ceiling on steps returned from ONE event, so no burst — synthetic,
    // replayed or pathological — can turn into an unbounded fan of subprocess
    // spawns. The remainder is discarded, not carried.
    property int maxSteps: 3

    property real accum: 0

    // Whole notches completed by this event, signed. 0 most of the time on a
    // touchpad: that is the point — the sub-notch remainder is carried.
    function steps(wheel) {
        var pd = wheel.pixelDelta ? wheel.pixelDelta.y : 0;
        var units = pd !== 0 ? pd * 12
                             : (wheel.angleDelta ? wheel.angleDelta.y : 0);
        if (units === 0)
            return 0;
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

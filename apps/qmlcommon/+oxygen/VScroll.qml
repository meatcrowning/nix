import QtQuick
import QtQuick.Controls

// THE scrollbar, in a Plasma session wearing OXYGEN: the style's own bar, with
// Oxygen's own metrics read off `oxygenrc` rather than assumed.
//
// This is the `+plasma` face's approach and nothing is re-litigated here — that
// file already argues the case (`../+plasma/VScroll.qml`): Oxygen draws a
// recessed rounded groove, a gradient slider with a fine outline, and chevron
// steppers whose count comes out of `oxygenrc` (`ScrollBarSubLineButtons` 1
// above the groove, `ScrollBarAddLineButtons` 2 below it), and a hand-drawn bar
// can only ever chase those numbers while `QtQuick.Controls` under
// `org.kde.desktop` gets them for free by handing the painting to `QStyle`.
//
// What this twin adds is that the numbers are READ, not guessed, in the two
// places QML has to name one anyway:
//   • the pre-measurement fallback for the gutter is Oxygen's own
//     `ScrollBarWidth` (`DeskStyle.styleScrollWidth`, parsed from `oxygenrc` by
//     pylib/oxygenstyle.py; the kcfg default is 15) rather than a literal;
//   • the bar carries `face`, which is the only proof the selector took at all
//     (an unowned QQmlFileSelector is collected silently).
//
// The API is the unselected sibling's, so no call site changes: `barW`,
// `hideWhenFull`, `scrollable`, `stepPx`. The aero-only properties (`barStyle`,
// the three-tone bevel ladder, the `color face`) mean nothing here and are
// absent; nothing outside that sibling ever read them. NOTE the name clash that
// implies: `../VScroll.qml` has a `readonly property color face` of its own,
// so anything walking the tree for a face must test for a STRING (the oracle
// selftest's `ORACLE_FACES` dump does).
ScrollBar {
    id: vb

    property string face: "oxygen"

    // Hidden while there is nothing to scroll, exactly as both siblings do. The
    // gutter is reserved from `barW` regardless, so the bar toggles and the
    // content never reflows.
    property bool hideWhenFull: true
    readonly property bool scrollable: vb.size < 0.999
    visible: !vb.hideWhenFull || vb.scrollable

    // The style's real extent: `implicitWidth` is what qqc2-desktop-style asks
    // the live QStyle for, so it moves with Oxygen's own KCM slider. The
    // fallback is reached only before the style item has measured itself, and
    // it is Oxygen's configured `ScrollBarWidth` — guarded, because a harness
    // stubs DeskStyle and an older pylib does not publish the key at all.
    readonly property int oxygenBarW: {
        const w = (typeof DeskStyle !== "undefined" && DeskStyle)
                ? Number(DeskStyle.styleScrollWidth) : NaN;
        return (isFinite(w) && w > 0) ? Math.round(w) : 15;   // oxygen.kcfg default
    }
    readonly property int barW:
        vb.implicitWidth > 0 ? Math.round(vb.implicitWidth) : vb.oxygenBarW

    // AlwaysOn plus our own `visible` above, for the sibling's reason: QQC2's
    // AsNeeded fades the bar in and out on a timer of its own, and Oxygen's
    // scrollbar does not fade — it is either there or the view does not scroll.
    policy: ScrollBar.AlwaysOn

    // One stepper click is one meaningful unit, derived from the flickable's
    // own contentHeight rather than left at ScrollBar's 10% — `parent` is the
    // Flickable, since ScrollBarAttached reparents the bar onto the scroller.
    property int stepPx: 48
    stepSize: {
        const f = vb.parent;
        const ch = (f && f.contentHeight !== undefined) ? f.contentHeight : 0;
        return ch > 0 ? Math.min(0.5, vb.stepPx / ch) : 0.1;
    }

    // Keeps a huge model's slider from collapsing to a sliver you cannot grab.
    // ScrollBar's own property, so the DRAG range stays correct.
    minimumSize: height > 0 ? Math.min(1, 24 / height) : 0
}

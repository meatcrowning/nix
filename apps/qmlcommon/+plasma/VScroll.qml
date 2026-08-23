import QtQuick
import QtQuick.Controls

// THE scrollbar, in a Plasma window that has a real QStyle behind it: the
// STYLE'S OWN BAR, not an imitation of one.
//
// `../VScroll.qml` — the sibling this file is selected in place of — draws
// every pixel itself, and its Plasma branch approximated a BREEZE bar: a
// rounded pill in a transparent track, no groove and no steppers. Under
// Oxygen, which is what this desktop's Plasma session actually wears, that is
// visibly the wrong control. Oxygen draws a recessed rounded groove, a gradient
// slider with a fine outline, and chevron steppers whose count comes out of
// `oxygenrc` (`ScrollBarSubLineButtons` 1 above the groove,
// `ScrollBarAddLineButtons` 2 below it). A hand-drawn bar can only ever chase
// those numbers; `QtQuick.Controls` under `org.kde.desktop` hands the painting
// to `QStyle` and gets them for free — the same route `+plasma/PromptBox.qml`'s
// Frame/TextArea and `+plasma/Chip.qml`'s Button already take.
//
// SELECTED ONLY WHERE IT CAN WORK. `+plasma` files are resolved for an engine
// whose app turned the selector on (`pylib/kdeshell.select_plasma_files`),
// which is exactly the set of apps built on `kdeshell` — the ones with a
// `QApplication`, a live `QStyle` and `QT_QUICK_CONTROLS_STYLE=org.kde.desktop`.
// Every other app in a Plasma session has none of those, so it goes on using
// the sibling's own Plasma branch: that branch stays where it is rather than
// being deleted.
//
// The API is the sibling's, so no call site changes: `barW` (reserve the gutter
// from it — here it is the style's real extent, Oxygen's `ScrollBarWidth` plus
// its own margins, so the gutter cannot be a pixel off the session's other
// scrollbars), `hideWhenFull`, `scrollable`, `stepPx`. The aero-only properties
// (`barStyle`, the three-tone bevel ladder) mean nothing here and are absent;
// nothing outside the sibling ever read them.
ScrollBar {
    id: vb

    // Hidden while there is nothing to scroll, exactly as the sibling does. The
    // gutter is reserved from `barW` regardless, so the bar toggles and the
    // content never reflows.
    property bool hideWhenFull: true
    readonly property bool scrollable: vb.size < 0.999
    visible: !vb.hideWhenFull || vb.scrollable

    // The style's extent: `implicitWidth` is what qqc2-desktop-style asks the
    // live QStyle for, so it moves with Oxygen's own KCM slider. The literal is
    // reached only before the style item has measured itself.
    readonly property int barW:
        vb.implicitWidth > 0 ? Math.round(vb.implicitWidth) : 17

    // AlwaysOn plus our own `visible` above, for the sibling's reason: QQC2's
    // AsNeeded fades the bar in and out on a timer of its own, and no scrollbar
    // on this desktop fades (docs/DESIGN.md §6.2.1).
    policy: ScrollBar.AlwaysOn

    // One stepper click is one meaningful unit (§9.2), derived from the
    // flickable's own contentHeight rather than left at ScrollBar's 10% —
    // `parent` is the Flickable, since ScrollBarAttached reparents the bar
    // onto the scroller.
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

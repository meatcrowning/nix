import QtQuick
import QtQuick.Controls.Basic

// THE scrollbar. `docs/DESIGN.md` §9.2 states it as one idiom for the whole desktop —
// [his] *"there should be a scrollbar wherever appropriate! please"* — and since
// 2026-07-28 it is a PIXEL-ERA scrollbar in three selectable variants, because
// the one it replaced was not:
//
//   [his] "i actually hate the scrollbar used everywhere. it should be styled
//          like the font. not like it is now as some sort of modern web-first one"
//   [his] "i want the option to do this one, the flat pixel block. and beveled
//          no arrows because they all look tight. put it in the settings to
//          change, make the default the win 3.1"
//
//     KineticListView { ScrollBar.vertical: VScroll {} }
//
// Call sites do not choose. `barStyle` comes off the panel's own settings.json
// through the `DeskStyle` context property (pylib/deskstyle.py) — the same
// mechanism that already carries fontFamily/fontSize/reduceMotion/animSpeed to
// every app, so one control in Settings > Appearance moves all seven at once and
// there is no second cross-app settings channel to keep in sync. Guarded with a
// `typeof` exactly like `Motion.qml`'s, so an offscreen harness that never
// installs DeskStyle still renders (as the default, win31) instead of throwing.
//
// SHOWN WHEN THERE IS SOMETHING TO SCROLL, and no fade. [his, 2026-08-22]
// *"scrollbar should only appear when needed, not all the time"* — so the bar
// is absent while the content fits and returns the instant it overflows. It
// never fades either way: full opacity, no `Behavior on opacity` anywhere (the
// 120 ms fade that used to be here is gone from §6.2.1's non-participants table
// with it), and the GUTTER is reserved from `barW` whether or not the bar is in
// it, so a view that starts to overflow does not reflow its content. That
// reflow was the whole argument for the old always-on rule; reserving the
// gutter answers it without a bar standing there saying nothing.
//
// THE PIXELS ARE THE POINT (§2.2, §4). Every edge is a 1px Rectangle on an
// integer coordinate and every arrow is drawn as GEOMETRY, never as text: More
// Perfect DOS VGA has no `↑`/`▲` at all (§2.3), and a PixelText containing a
// missing glyph loses ~5px of ascent to the fallback font and clips the line it
// is in. Nothing here is rounded, gradient-filled or antialiased.
//
// The thumb is PIXEL-SNAPPED against the fractional offset ScrollBar computes
// for it (`resizeContent()` puts it at `availableHeight * position`, which is
// almost never an integer). Without the snap the 1px bevels land on half pixels
// and shimmer as you drag — the exact mush a pixel font exists to avoid.
//
// No new colours: the bevel is a three-tone ladder taken straight out of the
// wallpaper palette (bg < bgAlt < border < dim), so it recolours with everything
// else and adds nothing to §3 to keep in sync.
//
// UNDER PLASMA the aero look is deliberately dropped for a Breeze-shaped bar
// (docs/DESIGN.md §9.2 / §3's Plasma rule): a rounded pill thumb over a
// transparent track, no bevels and no steppers, in the KDE colour scheme's own
// tones (Theme.* already resolve to kdeglobals here via kdetheme.py). The three
// aero variants and the `barStyle` setting are ignored in that session — an app
// still drawing a win31 stepper inside a Breeze window is the one control that
// reads as "not themed". Detected with `DeskStyle.plasma`, the same switch that
// moves the palette; guarded with `typeof` so a harness with no DeskStyle keeps
// the Hyprland look. Its WIDTH, though, is the live style's own number
// (`DeskStyle.styleScrollWidth`, Oxygen's `ScrollBarWidth`) rather than a
// literal — see `barW`.
//
// AND IN A KDESHELL APP IT IS NOT THIS FILE AT ALL: `+plasma/VScroll.qml` is
// selected in its place (painter, player, chatter — the apps with a
// `QApplication`, a live `QStyle` and `QT_QUICK_CONTROLS_STYLE=org.kde.desktop`),
// and hands the painting to the style itself, so Oxygen's groove, gradient
// slider and chevron steppers are the real ones rather than an approximation of
// Breeze's. The pill below is what every OTHER app in a Plasma session gets —
// none of them has a QStyle to ask, which is why it stays.
ScrollBar {
    id: vb

    // ---- which scrollbar -------------------------------------------------
    // win31   chunky, arrow steppers at both ends, hard 1px bevel  (DEFAULT)
    // beveled the 95 look minus the steppers: raised thumb, sunken track
    // flat    square, hard-edged, no bevel, no arrows, solid Theme colours
    readonly property string barStyle: {
        if (typeof DeskStyle === "undefined" || !DeskStyle) return "win31";
        const s = DeskStyle.scrollbarStyle;
        return (s === "flat" || s === "beveled" || s === "win31") ? s : "win31";
    }
    readonly property bool isWin31: barStyle === "win31"
    readonly property bool isFlat: barStyle === "flat"

    // In a Plasma session the whole aero vocabulary above is set aside for a
    // Breeze-shaped bar (see the header). This is the master switch for that.
    readonly property bool isPlasma:
        (typeof DeskStyle !== "undefined" && DeskStyle && DeskStyle.plasma) || false

    // ---- hide when there is nothing to scroll ---------------------------
    // DEFAULT ON since 2026-08-22 (his call above; it was opt-in and off, and
    // board was the one caller that had opted in). The bar vanishes entirely
    // while the content fits and returns the instant it overflows. `size` is
    // the visible fraction of the content: 1.0 means it all fits.
    //
    // A call site that reserves the gutter must go on reserving it from `barW`
    // REGARDLESS (never conditionally) — that is what makes this free: a hidden
    // bar leaves the layout exactly where a shown one would, so the bar
    // toggles and the content never moves. Set `hideWhenFull: false` for a view
    // that genuinely wants the old always-drawn bar; nothing does today.
    property bool hideWhenFull: true
    readonly property bool scrollable: vb.size < 0.999
    visible: !vb.hideWhenFull || vb.scrollable

    // Read this at a call site that has to reserve a gutter by hand, rather
    // than writing the old 9 (or a 12 derived from it) out again.
    //
    // In a Plasma session the width is the STYLE's own, not a number of ours:
    // `DeskStyle.styleScrollWidth` is Oxygen's `ScrollBarWidth` (15 by default,
    // and a KCM slider he can move), 0 when no style is saying — under Breeze,
    // or outside Plasma. A gutter one pixel off the session's real scrollbars
    // is the tell that this bar is hand-drawn.
    readonly property int styleW:
        (typeof DeskStyle !== "undefined" && DeskStyle && DeskStyle.styleScrollWidth > 0)
            ? DeskStyle.styleScrollWidth : 0
    readonly property int barW: isPlasma ? (styleW > 0 ? styleW : 14)
                              : (isWin31 ? 16 : (barStyle === "beveled" ? 14 : 11))
    readonly property int btn: isWin31 ? barW : 0        // stepper button size

    // The ladder, darkest to lightest. `face` has to be brighter than `trackC`
    // or a raised thumb reads as a hole.
    readonly property color dark: Theme.bg
    readonly property color trackC: Theme.bgAlt
    readonly property color face: Theme.border
    readonly property color light: Theme.dim

    // How far one arrow click moves the view. A FRACTION is what ScrollBar
    // steps in, so it is derived from the flickable's own contentHeight —
    // otherwise "one step" is 10% of the content and means a different distance
    // in every view (§9.2: one notch is one meaningful unit). `parent` is the
    // Flickable: ScrollBarAttached reparents the bar onto the scroller.
    property int stepPx: 48
    stepSize: {
        const f = vb.parent;
        const ch = (f && f.contentHeight !== undefined) ? f.contentHeight : 0;
        return ch > 0 ? Math.min(0.5, vb.stepPx / ch) : 0.1;
    }

    // Honesty (§10): an arrow that cannot move the view is drawn dead, and the
    // handlers refuse. `size >= 1` is "nothing to scroll", which now hides the
    // whole bar — but an arrow can still go dead with the bar up (you are at
    // one end of a scrollable view), so this stays exactly as it was.
    readonly property bool canUp: vb.size < 1 && vb.position > 0.0005
    readonly property bool canDown: vb.size < 1 && (vb.position + vb.size) < 0.9995

    // AlwaysOn plus our own `visible` above, deliberately: `AsNeeded` is
    // QQC2's own answer and it is the wrong one here — it FADES the bar in and
    // out on a timer of its own (and, attached to a Flickable, shows it on any
    // content change), which is the 120 ms fade §6.2.1 retired coming back in
    // through the style. Ours is a hard toggle on "is there anything to
    // scroll", with the gutter reserved either way.
    policy: ScrollBar.AlwaysOn
    hoverEnabled: true
    width: vb.barW
    implicitWidth: vb.barW

    // Keeps a huge model's thumb from collapsing to a sliver you cannot grab.
    // ScrollBar's own property, so the DRAG range stays correct — a floor
    // applied to the visual only would make the handle lie about where it is.
    minimumSize: height > 0 ? Math.min(1, 24 / height) : 0

    // Confines the thumb between the steppers (ScrollBar lays contentItem out
    // inside the padding), and insets it from the track's own bevel.
    padding: 0
    // Plasma insets the pill from every edge (a Breeze thumb floats in the
    // groove with a margin); the aero variants keep their own paddings.
    topPadding: vb.isPlasma ? 3 : (vb.isWin31 ? vb.btn : (vb.isFlat ? 0 : 1))
    bottomPadding: vb.topPadding
    // win31's thumb is FULL width, flush with the stepper buttons above and
    // below it, which is what makes the trough read as a channel those three
    // parts slide in. `beveled` has no buttons to line up with, so its thumb is
    // inset by the track's own bevel instead.
    leftPadding: vb.isPlasma ? 3 : (vb.barStyle === "beveled" ? 1 : 0)
    rightPadding: vb.leftPadding

    // ---- pieces ----------------------------------------------------------

    // A 1px hard bevel. Light on the top/left and dark on the bottom/right for
    // a raised face; swapped for a recessed one. No radius, no gradient.
    component Bevel: Item {
        id: bv
        property color faceColor: vb.face
        property bool sunken: false
        property bool bevelled: !vb.isFlat
        Rectangle { anchors.fill: parent; color: bv.faceColor }
        Rectangle { visible: bv.bevelled; x: 0; y: 0; width: bv.width; height: 1
                    color: bv.sunken ? vb.dark : vb.light }
        Rectangle { visible: bv.bevelled; x: 0; y: 0; width: 1; height: bv.height
                    color: bv.sunken ? vb.dark : vb.light }
        Rectangle { visible: bv.bevelled; x: 0; y: bv.height - 1; width: bv.width; height: 1
                    color: bv.sunken ? vb.light : vb.dark }
        Rectangle { visible: bv.bevelled; x: bv.width - 1; y: 0; width: 1; height: bv.height
                    color: bv.sunken ? vb.light : vb.dark }
    }

    // A 9x5 pixel triangle, built out of five 1px rows. Geometry, not a glyph.
    component Arrow: Item {
        id: ar
        property bool down: false
        property color ink: Theme.textDim
        Repeater {
            model: 5
            Rectangle {
                width: 2 * (ar.down ? (4 - index) : index) + 1
                height: 1
                color: ar.ink
                x: Math.floor((ar.width - width) / 2)
                y: Math.floor((ar.height - 5) / 2) + index
            }
        }
    }

    // A stepper button. Presses IN (the bevel inverts) and auto-repeats, like
    // every scrollbar arrow made before the web.
    component Stepper: Item {
        id: st
        property bool pointsDown: false     // which way the triangle faces
        property bool held: false           // pressed right now
        property bool live: true            // could this click move the view?
        signal step()
        Bevel { anchors.fill: parent; sunken: st.held }
        Arrow {
            anchors.fill: parent
            down: st.pointsDown
            // Dead arrow, dead colour (§10): `live` is false when the view is
            // already at that end or has nothing to scroll at all.
            ink: !st.live ? Theme.dim
               : (st.held ? Theme.accent : (st.hovered ? Theme.text : Theme.textDim))
            // The bevel takes a pixel off each side, so the triangle sits one
            // pixel down and right inside a pressed button — the whole face
            // moves, which is the point of the invert.
            x: st.held ? 1 : 0
            y: st.held ? 1 : 0
        }
        property bool hovered: ma.containsMouse
        MouseArea {
            id: ma
            hoverEnabled: true
            anchors.fill: parent
            enabled: st.live
            cursorShape: st.live ? Qt.PointingHandCursor : Qt.ArrowCursor
            onPressed: { st.held = true; st.step(); repeat.interval = 300; repeat.restart(); }
            onReleased: { st.held = false; repeat.stop(); }
            onCanceled: { st.held = false; repeat.stop(); }
        }
        Timer {
            id: repeat
            repeat: true
            onTriggered: { interval = 60; if (st.live) st.step(); else stop(); }
        }
    }

    // ---- the thumb -------------------------------------------------------

    contentItem: Item {
        id: slot
        implicitWidth: vb.barW
        implicitHeight: vb.barW

        Bevel {
            visible: !vb.isPlasma
            // Snap onto the pixel grid: ScrollBar puts `slot` at a fractional y,
            // and a 1px bevel on a half pixel is a blurred one.
            x: Math.round(slot.x) - slot.x
            y: Math.round(slot.y) - slot.y
            width: Math.round(slot.width)
            height: Math.round(slot.height)
            faceColor: vb.pressed ? Theme.accent
                     : (vb.isFlat ? (vb.hovered ? Theme.text : Theme.textDim) : vb.face)
            // A dragged thumb does not press IN — it moves. Only the steppers
            // invert, which is how these scrollbars have always read.
            sunken: false
        }

        // The Breeze pill. Rounded and ANTIALIASED, unlike everything else in
        // this file — it is a KDE control now, not a pixel-era one, so it snaps
        // to nothing and its ends are fully round (radius = half its width). The
        // handle carries the whole bar (the track is transparent), so it brightens
        // on hover — dim -> text — and goes accent while dragged, the KDE idiom.
        Rectangle {
            visible: vb.isPlasma
            anchors.fill: parent
            radius: Math.min(width, height) / 2
            antialiasing: true
            color: vb.pressed ? Theme.accent
                 : (vb.hovered ? Theme.text : Theme.dim)
        }
    }

    // ---- the track, and the steppers that live at its ends ----------------

    background: Item {
        implicitWidth: vb.barW

        // Recessed for the two bevelled variants; a plain solid block for flat.
        // A Plasma bar has no track at all — the transparent groove is the Breeze
        // look, and the always-on pill is the only thing that needs to be drawn.
        Bevel {
            visible: !vb.isPlasma
            anchors.fill: parent
            faceColor: vb.trackC
            sunken: true
        }

        Stepper {
            id: up
            visible: vb.isWin31
            width: vb.btn; height: vb.btn
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            live: vb.canUp
            pointsDown: false
            onStep: vb.decrease()
        }
        Stepper {
            id: dn
            visible: vb.isWin31
            width: vb.btn; height: vb.btn
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            live: vb.canDown
            pointsDown: true
            onStep: vb.increase()
        }
    }
}

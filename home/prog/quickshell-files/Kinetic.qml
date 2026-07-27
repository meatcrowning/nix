pragma Singleton
import Quickshell
import QtQuick

// THE SINGLE SOURCE OF TRUTH for how anything in this panel scrolls.
// Nothing here may be duplicated as a literal in another file: change a number
// here and every scroll area in the panel changes with it. The scroll areas
// themselves get it for free by being a KineticFlickable / KineticListView /
// KineticGridView instead of the bare Qt type — see AGENTS.md, "Scrolling".
//
// WHY THERE IS ANYTHING TO CONFIGURE AT ALL, given that momentum on this
// desktop is synthesized by the COMPOSITOR (hyprvtb's vtbKinetic, >=2.78) and
// therefore reaches every toolkit as ordinary high-resolution axis events:
// hyprvtb refuses to coast over a LAYER SURFACE, wholesale and on purpose
// (vtbKinetic.cpp, the "layer-focus" start gate — the bar's brightness/volume
// steppers act per event, so a one-second coast would be forty wpctl spawns).
// Almost this whole panel IS layer surfaces: the bar, every SlidePopup, the
// launcher, the wallpaper picker, the cheatsheet. Only Settings and the file
// browser are Quickshell FloatingWindows, i.e. real toplevels, and only they
// receive compositor momentum today.
//
// So the panel is the one part of this desktop that has to supply its own
// deceleration, and the job of these numbers is to make it FEEL like the rest.
Singleton {
    // MIRRORS `plugin:hyprvtb:kinetic_friction` in home/prog/hypr-files/
    // hyprland.lua (BOTH copies — it is a seed-once file). The compositor's
    // model is exponential decay, v(t) = v0*e^(-friction*t), so a coast covers
    // exactly v0/friction pixels. Units: s^-1. 2.6 floaty, 3.6 mac-anchored,
    // 5.2 snappy. If that key ever changes, change this line and nothing else.
    readonly property real friction: 3.6

    // Qt's Flickable does NOT decay exponentially — `flickDeceleration` is a
    // linear px/s^2, giving a coast of v0^2/(2a). The two models can only be
    // made to agree at one velocity, so we anchor at a representative panel
    // flick and accept the mismatch either side of it:
    //
    //     v0/friction = v0^2/(2a)   =>   a = v0*friction/2
    //     a = 1200 * 3.6 / 2 = 2160 px/s^2
    //
    // Qt's default 1500 is the same as anchoring at v0 = 2*1500/3.6 = 833 px/s,
    // i.e. every flick brisker than a slow drag overshoots what the compositor
    // would have done. Faster than 1200 px/s we now undershoot slightly, which
    // is the safer side of the error for a small panel.
    readonly property real refVelocity: 1200          // px/s, a brisk panel flick
    readonly property real flickDeceleration: refVelocity * friction / 2

    // Left at Qt's default 2500 px/s deliberately: at friction 3.6 that is a
    // 694 px coast, already more than the height of most surfaces here.
    readonly property real maximumFlickVelocity: 2500

    // One mouse-wheel detent, in Qt angleDelta units. QtWayland reports a
    // touchpad as angleDelta = 12 * surface-pixel-delta, so 120 units is either
    // one physical wheel click or 10 px of finger travel. Used by WheelNotch to
    // give DISCRETE controls (volume, brightness) a notch even when the stream
    // feeding them is continuous.
    readonly property real detent: 120
}

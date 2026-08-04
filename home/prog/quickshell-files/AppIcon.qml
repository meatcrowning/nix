import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets

// ONE program icon, drawn the way this desktop draws program icons: our own
// app seals as a flat fill of the live focus colour, every other icon tinted
// to it.
//
// The bespoke seals (home/prog/app-icons/*.svg, plus goetia's) are
// `currentColor` sigils: the sigil IS the theme's foreground (docs/DESIGN.md
// §3.1, body text = the accent), which is why hyprvtb's titlebar resolves it
// through a librsvg stylesheet and goetia's window icon substitutes the token
// textually before rendering. Qt's SVG renderer has no such hook — it resolves
// currentColor to the file's baked root `color` (#cc4400) — so on the panel a
// seal had two failure modes, and both are the ICON's ink deciding the colour
// instead of the theme:
//
//   drawn straight (the notification card)  pure red, on every wallpaper
//   through MultiEffect.colorization        the accent scaled by the source's
//                                           own luminance, i.e. a dull fraction
//                                           of the focus colour (the runner)
//
// So a seal is drawn as a MASK — a flat rectangle of `color`, cut to the
// sigil's alpha — which is exactly the colour hyprvtb paints it in the
// titlebar of the same program. A full-colour theme icon still goes through
// colorization when `tint` is set: its light/dark detail IS the drawing, and
// flattening it would leave a silhouette.
Item {
    id: root

    // Desktop-entry Icon= name. Consumers that already hold a resolved URL
    // (the notification card's app_icon, a tray item's pixmap) set `source`
    // instead and leave this empty.
    property string iconName: ""
    property string source: iconName === ""
        ? "" : Quickshell.iconPath(iconName, "application-x-executable")
    // The colour a seal is painted in, and the tint a foreign icon takes.
    property color color: Theme.accent
    // Foreign icons only. A seal is always painted `color` — it has no colours
    // of its own to keep, only the baked fallback.
    property bool tint: true
    property real dim: 1

    // Both spellings, because a caller may hand us either half: the icon name
    // for the theme lookup, or an already-resolved path/URL whose basename is
    // still the icon name (image://icon/player, …/apps/player.svg).
    readonly property bool seal: AppSeals.has(root.iconName) || AppSeals.has(root.source)

    IconImage {
        id: img
        anchors.fill: parent
        source: root.source
        opacity: root.dim
        // The invisible SOURCE the effects below read; drawn straight only for
        // a foreign icon nobody asked to tint.
        visible: !root.tint && !root.seal
    }

    // The ink for a seal. Never drawn itself — it is what the mask cuts.
    Rectangle {
        id: ink
        anchors.fill: img
        color: root.color
        visible: false
        // The layer IS the texture the mask reads, so it exists only for a
        // seal — a taskbar full of foreign icons allocates no FBOs for it.
        layer.enabled: root.seal
    }

    MultiEffect {
        anchors.fill: img
        source: ink
        maskEnabled: true
        maskSource: img
        visible: root.seal && root.source !== ""
        opacity: root.dim
    }

    MultiEffect {
        anchors.fill: img
        source: img
        visible: root.tint && !root.seal && root.source !== ""
        colorization: 1.0
        colorizationColor: root.color
        opacity: root.dim
    }
}

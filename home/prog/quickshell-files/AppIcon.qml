import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets

// ONE program icon, drawn the way this desktop draws program icons: tinted to
// the live focus colour, and — for our own app seals — tinted whether or not
// the surface tints anything else.
//
// The seals (home/prog/app-icons/*.svg, plus goetia's) are `currentColor`
// sigils: the sigil IS the theme's foreground (docs/DESIGN.md §3.1), so
// whatever draws one has to supply the colour. hyprvtb does it with a librsvg
// stylesheet and goetia's window icon by substituting the token before
// rendering; Qt's SVG renderer has no such hook and resolves currentColor to
// the file's baked root `color`, so on the panel the colour comes from the
// tint — and the tint is only exact because that fallback is WHITE.
//
// Measured on the sandbox output (tint #6dbdf2, one seal, four render paths):
//
//   raw, #cc4400 fallback                    #cc4400   red on every wallpaper
//   colorization over the #cc4400 fallback   #2b4b60   36% of the tint — the
//                                                      dullness he reported
//   MultiEffect mask (flat fill, cut to the
//     sigil's alpha by maskSource)           nothing   an invisible source item
//                                                      has no layer to sample
//   colorization over a WHITE fallback       #6dbdf2   exact
//
// The image themes now replace Oxygen's blue material colour with the live
// palette hue. Keep the source luminance here too: it is the glassy highlight
// and shadow work that makes an Oxygen icon an icon rather than a flat mask.
Item {
    id: root

    // Desktop-entry Icon= name. Consumers that already hold a resolved URL
    // (the notification card's app_icon, a tray item's pixmap) set `source`
    // instead and leave this empty.
    property string iconName: ""
    property string source: iconName === ""
        ? "" : Quickshell.iconPath(iconName, "application-x-executable")
    property color color: Theme.accent
    // Foreign icons carry Oxygen's own highlights and coloured details. A seal
    // is tinted either way: drawn raw it is a white line drawing, which states
    // the theme's colour nowhere.
    property bool tint: false
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
        // Normally the invisible SOURCE the effect below reads; drawn straight
        // only for a foreign icon nobody asked to tint.
        visible: !root.tint && !root.seal
    }

    MultiEffect {
        anchors.fill: img
        source: img
        visible: (root.tint || root.seal) && root.source !== ""
        colorization: 1.0
        colorizationColor: root.color
        opacity: root.dim
    }
}

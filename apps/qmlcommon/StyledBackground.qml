import QtQuick

// The KDE style's own window background, drawn INSIDE the app's QML.
//
// In a Plasma session an app of ours is a real QMainWindow hosting its QML in a
// QQuickWidget (apps/pylib/kdeshell.py). What makes a KDE window read as one
// object is the style's window background — under Oxygen a vertical gradient
// plus a radial splash, running unbroken from the titlebar down through the
// menubar and toolbar and behind the content.
//
// THE OBVIOUS WAY TO GET IT — a transparent QQuickWidget, letting the parent
// show through — DOES NOT WORK, and its failure is invisible to every offscreen
// harness (`QWidget.grab()` re-renders through a fresh backing store; the bug is
// in the live one). On his session it produced a genuine hole in the window:
// the region was never repainted, so it was absent from screenshots entirely
// and windows dragged over it left trails *inside* it. Twice — once with
// `WA_TranslucentBackground`, once with the transparent clearColor alone.
//
// So the view is opaque and this draws the background instead: an image the
// STYLE renders (a proxy top-level QWidget with WA_StyledBackground, rendered
// into a QImage and cropped to the view's rectangle in the window), served by
// the `kdebg` image provider. Pixel-exact against a real window's own painted
// background, so it still lines up seamlessly with the chrome above it, and it
// is still Oxygen's code drawing Oxygen's gradient.
//
// Put it at the BACK of the app's root item and let the panes over it stay
// transparent (`Theme.windowFill`):
//
//     StyledBackground { anchors.fill: parent; z: -1 }
//
// In the Hyprland session `KdeBackground` does not exist, the item is invisible
// and paints nothing, so a single Root.qml serves both faces.
Image {
    id: bg

    readonly property bool available: typeof KdeBackground !== "undefined" && KdeBackground

    // `cache: false` because the URL is the only thing that changes when the
    // window resizes — a cached image keyed on it would be right, but the
    // provider is cheap and a stale entry per size is not worth the memory.
    cache: false
    asynchronous: false
    visible: available
    source: available ? KdeBackground.source : ""
    fillMode: Image.Pad
    horizontalAlignment: Image.AlignLeft
    verticalAlignment: Image.AlignTop
    z: -1
}

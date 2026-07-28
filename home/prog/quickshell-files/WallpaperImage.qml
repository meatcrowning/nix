import QtQuick

// One frame of the wallpaper cross-fade (see WallpaperLayer.qml).
//
// PreserveAspectCrop is what centres the art: it scales the image to COVER this
// item and crops the overflow about the centre — so the middle of the picture
// lands on the middle of the item, which is the visible (non-panel) desktop.
// Resizing the item re-crops without re-decoding, which is what makes dragging
// the panel edge cheap.
Image {
    id: root

    // "tile" (a small repeating texture) or "scale" (a photo). Kept as a
    // property rather than read from Wall directly so the two cross-fade frames
    // can hold different values mid-swap.
    property string mode: "scale"
    property bool showing: true

    // Size to decode the image at, passed in from the window (the monitor's
    // resolution) rather than read off a `Screen` attached property, which does
    // not resolve reliably inside a layer surface.
    property int decodeW: 1920
    property int decodeH: 1080

    signal ready()

    fillMode: mode === "tile" ? Image.Tile : Image.PreserveAspectCrop
    asynchronous: true                 // never block the panel on a big decode
    cache: false                       // one big image; the cache would just
                                       // hold a second copy of it in memory
    smooth: true

    // Decode once, at roughly screen size, and NEVER key this off the item's
    // width: the width changes on every frame of a panel drag, and a sourceSize
    // bound to it would re-decode a multi-megapixel image per frame. 0 means
    // "the image's natural size", which is what tiling needs — a tile scaled to
    // the screen would no longer tile.
    sourceSize.width: mode === "tile" ? 0 : decodeW
    sourceSize.height: mode === "tile" ? 0 : decodeH

    // Load THIS image synchronously, blocking until it has decoded, then go back
    // to asynchronous for every later swap. `asynchronous` is read when the
    // source is assigned, so restoring it on the next line only affects the next
    // load — the assignment above has already finished decoding by then.
    //
    // Only the first paint of a tree uses this (WallpaperLayer._apply): a
    // cross-fade must NOT block, both because the outgoing frame is still on
    // screen and because the picker previews a new wallpaper on every arrow key.
    function loadNow(u: string, m: string): void {
        mode = m;
        asynchronous = false;
        source = u;
        asynchronous = true;
    }

    opacity: showing ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: ViewMode.ms(260); easing.type: Easing.InOutQuad } }

    onStatusChanged: if (status === Image.Ready) root.ready()
}

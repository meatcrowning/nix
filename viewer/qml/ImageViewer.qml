import QtQuick

// The gwenview-style image surface of `viewer` (its own window/process — filer
// shells out to `viewer <path>` instead of opening this inline). Two wins over
// feh: it uses Qt's image stack (far more formats than feh's Imlib2, and a
// graceful error card instead of a console warning on a broken/undecodable
// file), and the hyprvtb titlebar drives it (prev/next/zoom/close — wired in
// Main.qml). Main.qml swaps `source` to flip through the folder's images.
//
// Scaling: the image is fit to the window by default (zoom 1.0 = fit); the wheel
// zooms IN from there (fit is the floor), and dragging pans once zoomed. Flip /
// close come from OUTSIDE — the titlebar buttons and the key handler below call
// next()/prev()/closeRequested(); Main.qml swaps `source` to the new image.
Rectangle {
    id: viewer

    property url source: ""
    property string name: ""       // basename, for the "can't display" card
    property bool winActive: true

    signal next()
    signal prev()
    signal closeRequested()

    color: Theme.bg
    focus: visible

    readonly property real maxZoom: 8

    // status of whichever delegate (Image / AnimatedImage) is currently loaded,
    // for the loading/error card below; Image.Loading until the Loader has an item.
    readonly property int imgStatus: imgLoader.item ? imgLoader.item.status : Image.Loading

    // Static path: EXIF auto-rotation (so portrait photos match filer's upright
    // thumbnails) + a capped decode so a 50-megapixel file doesn't blow up memory.
    Component {
        id: staticComp
        Image {
            anchors.fill: parent
            fillMode: Image.PreserveAspectFit
            source: viewer.source
            autoTransform: true
            sourceSize.width: 3840
            sourceSize.height: 3840
            asynchronous: true
            cache: false          // one big image at a time — don't hoard
            smooth: true
            mipmap: true
        }
    }

    Component {
        id: animatedComp
        AnimatedImage {
            anchors.fill: parent
            fillMode: Image.PreserveAspectFit
            source: viewer.source
            asynchronous: true
            cache: false
            smooth: true
            mipmap: true
            playing: true
        }
    }

    // reset to fit whenever the shown image changes
    onSourceChanged: fit()
    onVisibleChanged: if (visible) forceActiveFocus()

    function fit() { flick.zoom = 1; flick.contentX = 0; flick.contentY = 0; }
    function zoomBy(f) { zoomAround(f, flick.width / 2, flick.height / 2); }
    // Zoom by factor f, keeping the point at viewport coords (fx,fy) pinned —
    // so wheel-zoom homes on the cursor and button-zoom on the centre.
    function zoomAround(f, fx, fy) {
        const old = flick.zoom;
        const nz = Math.max(1, Math.min(viewer.maxZoom, old * f));
        if (nz === old) return;
        const cx = (flick.contentX + fx) / content.width;
        const cy = (flick.contentY + fy) / content.height;
        flick.zoom = nz;   // content.width/height re-evaluate synchronously
        flick.contentX = Math.max(0, Math.min(cx * content.width - fx, content.width - flick.width));
        flick.contentY = Math.max(0, Math.min(cy * content.height - fy, content.height - flick.height));
    }

    Flickable {
        id: flick
        anchors.fill: parent
        clip: true
        contentWidth: content.width
        contentHeight: content.height
        boundsBehavior: Flickable.StopAtBounds

        // 1.0 = fit-to-window; the content box grows past the viewport as it
        // climbs, and the image (PreserveAspectFit inside that box) grows with
        // it, so panning falls out of the Flickable for free.
        property real zoom: 1.0

        Item {
            id: content
            width:  Math.max(flick.width,  flick.width  * flick.zoom)
            height: Math.max(flick.height, flick.height * flick.zoom)

            // AnimatedImage for formats that can animate (GIF/WebP/APNG/MNG) so
            // they play instead of freezing on frame 1; a plain Image — EXIF
            // auto-rotated and decode-capped — for everything else.
            Loader {
                id: imgLoader
                anchors.centerIn: parent
                width:  flick.width  * flick.zoom
                height: flick.height * flick.zoom
                sourceComponent: {
                    const s = viewer.source.toString().toLowerCase();
                    return (s.endsWith(".gif") || s.endsWith(".webp")
                         || s.endsWith(".apng") || s.endsWith(".mng"))
                        ? animatedComp : staticComp;
                }
            }
        }

        WheelHandler {
            target: null
            acceptedModifiers: Qt.NoModifier
            onWheel: (e) => viewer.zoomAround(e.angleDelta.y > 0 ? 1.2 : 1 / 1.2, e.x, e.y)
        }
    }

    // loading / error state, centred over the (empty) canvas
    PixelText {
        anchors.centerIn: parent
        horizontalAlignment: Text.AlignHCenter
        visible: viewer.imgStatus !== Image.Ready
        text: viewer.imgStatus === Image.Error ? ("can't display\n" + viewer.name)
            : viewer.imgStatus === Image.Loading ? "loading…" : ""
        color: viewer.winActive ? Theme.textDim : Theme.inactive
    }

    Keys.onPressed: (e) => {
        switch (e.key) {
        case Qt.Key_Left:                      viewer.prev(); e.accepted = true; break;
        case Qt.Key_Right: case Qt.Key_Space:  viewer.next(); e.accepted = true; break;
        case Qt.Key_Escape:                    viewer.closeRequested(); e.accepted = true; break;
        case Qt.Key_Plus: case Qt.Key_Equal:   viewer.zoomBy(1.25); e.accepted = true; break;
        case Qt.Key_Minus:                     viewer.zoomBy(0.8);  e.accepted = true; break;
        case Qt.Key_0:                         viewer.fit();        e.accepted = true; break;
        }
    }
}

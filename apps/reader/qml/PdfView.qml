import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// reader's SECOND document mode: the continuous page view a PDF is read in.
//
// It sits where the markdown mode's `KineticListView` of `Block`s sits, inside
// the same `DocPane`, and answers the same three questions that pane asks of a
// document — where am I (`topIndex`, a PAGE here rather than a block), take me
// there (`jumpIndex`), and how wide is the content. Everything outside this file
// — history, the outline pane, the footer, Ctrl+F, the persisted position — is
// shared with the markdown mode and knows nothing about pages.
//
// Pages come from `pdfdoc.py` through an image provider, one URL per
// (document, generation, page), and the page cache is `pdfdoc.py`'s own LRU —
// Qt's pixmap store drops anything unreferenced past a hardcoded 2 MB and one
// page is ~5 MB, so it never was one. The URL carries the generation so a file
// that changed on disk actually re-rasterizes (docs/DESIGN.md §6.1), and the
// SIZE handed to `sourceSize` is part of that cache's key — which is why the
// zoom below settles before it re-rasterizes.
//
// Ctrl+wheel zooms about the pointer and the middle button drags the page
// about; both live in the one `MouseArea` at the bottom of this file.
Item {
    id: pdfv

    property var doc: ({})
    property string docKey: "left"
    property bool winActive: true
    property real cellW: 8
    // Search: the pages holding the query, and which of them is current. The
    // same two properties `DocPane` keeps for markdown blocks.
    property var matches: []
    property int matchAt: -1

    readonly property int pageCount: doc.pageCount || 0
    readonly property var pages: doc.pages || []
    readonly property int gen: doc.gen || 0

    property int topIndex: 0                 // the page the viewport is inside
    signal pageChanged(int page)

    // ---- zoom ---------------------------------------------------------------
    // Three ways to say the same number, because a page view is read at a
    // width and studied at a scale. `fit` is the MODE and survives a window
    // resize; a step in or out drops out of it, which is the only honest
    // reading of "fit" (§10.1 — one control, one effect).
    property string fit: "width"             // width | page | none
    property real zoom: 1.0
    readonly property real minZoom: 0.15
    readonly property real maxZoom: 8.0
    // The house content inset (§4.1) on both sides, plus the scrollbar's own
    // width — never a literal, it is a setting and ranges 11-16px (§9.2).
    readonly property real inset: 10
    readonly property real availW: Math.max(1, width - inset * 2 - vscroll.barW)
    readonly property real availH: Math.max(1, height - inset * 2)
    // The widest page decides fit-width, so a document with one landscape plate
    // in it does not scroll sideways on that one page.
    readonly property real maxPtW: {
        var w = 1;
        for (var i = 0; i < pages.length; i++) w = Math.max(w, pages[i].w);
        return w;
    }
    readonly property real curPtW: pages.length && topIndex < pages.length
                                   ? pages[topIndex].w : 612
    readonly property real curPtH: pages.length && topIndex < pages.length
                                   ? pages[topIndex].h : 792

    readonly property real pageScale: {
        if (fit === "width") return clampZoom(availW / maxPtW);
        if (fit === "page")  return clampZoom(Math.min(availW / curPtW, availH / curPtH));
        return zoom;
    }
    function clampZoom(z) { return Math.max(minZoom, Math.min(maxZoom, z)); }
    // A wheel zoom SETTLES onto a 0.25% grid — where it comes to rest, never
    // while the gesture is running. `pdfdoc.py`'s raster cache keys on the
    // exact pixel size, so an ungridded scale mints a fresh 5 MB raster per
    // visible page every time a gesture stops anywhere near a zoom that has
    // already been drawn; gridding the LIVE scale instead would make a slow
    // trackpad zoom advance in ~1px hops, which is docs/DESIGN.md §6's "never
    // quantize a live drag" almost word for word. The correction at the end is
    // under 0.125% and lands in the same frame as the re-raster.
    // The `+`/`−` cells do not go through it: their 1.25^n ladder is already a
    // handful of values, and gridding it would stop `zoomOut` being the exact
    // inverse of `zoomIn`. `fit` is never gridded either — fit-width has to be
    // exactly the width.
    function quantZoom(z) { return Math.round(z * 400) / 400; }

    // ---- rasterizing LAGS the zoom, on purpose ------------------------------
    // The scale the visible pages are actually rasterized AT. The geometry
    // follows the wheel immediately (pxW/pxH below), but `sourceSize` — which
    // is the raster cache's key — is held at the last SETTLED scale until the
    // gesture stops, and Qt scales the pixmap it already has in between, which
    // is what every other page viewer does mid-gesture.
    //
    // Measured by Naberius on `top` 2026-07-31: one fit-width page raster is
    // 2-50 ms of PDFium (median ~3 ms text, ~45 ms image-heavy scans) and
    // `QPdfDocument.render` does NOT release the GIL, so Python on the GUI
    // thread runs at 15% of its rate while a page rasterizes. Writing
    // `sourceSize` per wheel notch is ~5 MB and one of those jobs per visible
    // page per notch — ten notches over three pages is ~30 rasters, up to 1.5 s
    // of GIL-held work, and it evicts the whole 96 MB budget on the way.
    property real rasterScale: 1
    // True while the pixmap on screen is being SCALED rather than redrawn — the
    // one window in which `smooth` has to be on, or the intermediate frames are
    // nearest-neighbour mush.
    readonly property bool scaling: Math.abs(rasterScale - pageScale) > 0.0005
    Timer {
        id: settle
        interval: 140                    // long enough to span a wheel gesture
        onTriggered: {
            // The grid is applied HERE, to where the gesture came to rest, so
            // the same visual zoom reached twice reuses one raster.
            if (pdfv.fit === "none")
                pdfv.zoom = pdfv.clampZoom(pdfv.quantZoom(pdfv.zoom));
            pdfv.rasterScale = pdfv.pageScale;
        }
    }
    // A new document (or a reload) rasterizes at once: there is no pixmap to
    // scale in the meantime, so lagging would only draw the wrong size.
    onDocChanged: { settle.stop(); pdfv.rasterScale = pdfv.pageScale; pdfv.panX = 0; }
    Component.onCompleted: pdfv.rasterScale = pdfv.pageScale
    onPageScaleChanged: {
        settle.restart();
        pdfv.panX = clampPanX(pdfv.panX);
    }
    onWidthChanged: pdfv.panX = clampPanX(pdfv.panX)

    // ---- panning -------------------------------------------------------------
    // How far the sheet is dragged off centre, in px. A page narrower than the
    // pane is CENTRED and cannot be dragged (panXMax is 0) — it is only a zoom
    // past fit-width that puts anything out of reach sideways, and before this
    // existed those edges could not be reached at all.
    property real panX: 0
    readonly property real panXMax: panLimit(pageScale)
    function panLimit(s) { return Math.max(0, (maxPtW * s - view.width) / 2); }
    // Clamped against a scale that is passed in, never against `panXMax` — a
    // handler for `pageScaleChanged` can run BEFORE the bindings that depend on
    // the same property have been invalidated, and reading the cached limit
    // there left the sheet parked off-centre after a zoom back to fit-width
    // (measured offscreen; it is the whole reason this takes an argument).
    function clampPanX(x, s) {
        var m = panLimit(s === undefined ? pageScale : s);
        return Math.max(-m, Math.min(m, x));
    }

    // Zooming keeps the page you are looking at, not the pixel offset you had:
    // a step in at page 40 of 400 must not land you at page 3. The page is
    // re-pinned after the relayout, which is the same two-pass trick
    // `DocPane.jumpIndex` needs for a block whose height is not known yet.
    function rezoom(z, mode) {
        var at = pdfv.topIndex;
        pdfv.zoom = clampZoom(z);
        pdfv.fit = mode;
        Qt.callLater(function () { pdfv.jumpIndex(at); });
    }
    function zoomIn()    { rezoom(pageScale * 1.25, "none"); }
    function zoomOut()   { rezoom(pageScale / 1.25, "none"); }
    function fitWidth()  { rezoom(pageScale, "width"); }
    function fitPage()   { rezoom(pageScale, "page"); }

    // A delegate's height at a given scale — what the delegate below computes,
    // for the one case where the item does not exist to be asked.
    function pageHeightAt(i, s) {
        var h = (i >= 0 && i < pages.length) ? pages[i].h : 792;
        return Math.max(1, Math.round(h * s)) + 2;
    }

    // Ctrl+wheel. A CONTINUOUS zoom by factor `f` that keeps the point at
    // viewport coords (mx,my) under the cursor — the whole reason it is not
    // `zoomIn()` on a timer: stepping between fixed levels and re-pinning the
    // page top throws away the paragraph the user was pointing at.
    //
    // The page under the cursor is pinned by FRACTION of that page rather than
    // by pixel offset, so a zoom at page 40 of 400 stays at page 40 (§10.1, the
    // same reasoning `rezoom` re-pins for).
    //
    // It goes back through `positionViewAtIndex` rather than computing an
    // absolute `contentY`, because a ListView RECOMPUTES `originY` when its
    // delegates resize under it — measured here at -7303 after ten notches —
    // and an absolute offset taken against the old origin walks off the page it
    // was pinning (page 0 -> page 4 over one gesture, offscreen).
    function zoomAt(f, mx, my) {
        var s0 = pageScale;
        var s1 = clampZoom(s0 * f);
        if (s1 === s0 || pageCount <= 0) return;

        var cy = view.contentY + my;                 // content coords under the cursor
        var i = view.indexAt(4, cy);
        if (i < 0) i = pdfv.topIndex;
        i = Math.max(0, Math.min(pageCount - 1, i));
        // How far down THAT page the cursor is, read off the live delegate —
        // no reproducing the view's layout, which is the other way to get this
        // wrong.
        var it = view.itemAtIndex(i);
        var h0 = it ? it.height : pageHeightAt(i, s0);
        var frac = Math.max(0, Math.min(1, (cy - (it ? it.y : cy)) / h0));

        var g = s1 / s0;
        pdfv.zoom = s1;
        pdfv.fit = "none";                           // a free zoom is not a fit

        // Horizontal: the same pin, and it reduces to this whatever the page
        // width is (the sheet is centred, so only the offset from the viewport
        // centre matters).
        pdfv.panX = clampPanX(pdfv.panX * g + (mx - view.width / 2) * (g - 1), s1);

        // Relayout at the new scale, then step down into the page by the same
        // fraction, so the point under the cursor is the point still there.
        view.positionViewAtIndex(i, ListView.Beginning);
        var it1 = view.itemAtIndex(i);
        var h1 = it1 ? it1.height : pageHeightAt(i, s1);
        var minY = view.originY;
        var span = Math.max(0, view.contentHeight - view.height);
        view.contentY = Math.max(minY, Math.min(minY + span,
                                                view.contentY + frac * h1 - my));
    }

    // ---- moving about --------------------------------------------------------
    function jumpIndex(i) {
        var n = Math.max(0, Math.min(pageCount - 1, i || 0));
        view.positionViewAtIndex(n, ListView.Beginning);
        pdfv.topIndex = n;
        Qt.callLater(function () {
            view.positionViewAtIndex(n, ListView.Beginning);
            pdfv.topIndex = n;
        });
    }
    function pageDown() { view.contentY = Math.min(view.contentY + pdfv.availH * 0.92,
                                                   Math.max(0, view.contentHeight - view.height)); }
    function pageUp()   { view.contentY = Math.max(view.contentY - pdfv.availH * 0.92, 0); }
    function toStart()  { jumpIndex(0); }
    function toEnd()    { jumpIndex(pageCount - 1); }

    KineticListView {
        id: view
        anchors.fill: parent
        anchors.margins: pdfv.inset
        clip: true
        model: pdfv.pageCount
        spacing: Theme.fontSize          // the blank line between pages (§4.1)
        // A page is a big delegate; two screens either side is what keeps a
        // fast scroll from showing the placeholder, without holding a whole
        // book of rasters.
        cacheBuffer: Math.round(pdfv.height * 2)
        ScrollBar.vertical: VScroll { id: vscroll }

        onContentYChanged: {
            var i = view.indexAt(4, view.contentY + 4);
            if (i >= 0 && i !== pdfv.topIndex) {
                pdfv.topIndex = i;
                pdfv.pageChanged(i);
            }
        }

        delegate: Item {
            id: pageItem
            required property int index
            readonly property real ptW: pdfv.pages.length > index ? pdfv.pages[index].w : 612
            readonly property real ptH: pdfv.pages.length > index ? pdfv.pages[index].h : 792
            // Never zero: reader feeds the vtb socket, and hyprvtb's renderRect
            // aborts the compositor on a zero-size box (docs/DESIGN.md §12).
            readonly property int pxW: Math.max(1, Math.round(ptW * pdfv.pageScale))
            readonly property int pxH: Math.max(1, Math.round(ptH * pdfv.pageScale))
            // What is ASKED of PDFium — the settled scale, not the live one.
            // These are the raster cache's key (pdfdoc.py); `pxW`/`pxH` above
            // are only where it is drawn.
            readonly property int rxW: Math.max(1, Math.round(ptW * pdfv.rasterScale))
            readonly property int rxH: Math.max(1, Math.round(ptH * pdfv.rasterScale))

            width: view.width
            height: pxH + 2

            readonly property bool isMatch: pdfv.matchAt >= 0
                                            && pdfv.matches[pdfv.matchAt] === index

            // The sheet: the 1px `Theme.border` hairline every inset surface on
            // this desktop takes, no radius and no shadow (§4). The page the
            // find is ON takes `accent` instead — the only mark this mode can
            // make honestly, since the hit's geometry inside the page is not
            // asked for (see pdfdoc.py).
            Rectangle {
                // Centred, less however far the sheet has been dragged
                // sideways (`panX`, 0 unless the zoom is past fit-width).
                x: Math.round((view.width - pageItem.pxW) / 2 - pdfv.panX) - 1
                width: pageItem.pxW + 2
                height: pageItem.pxH + 2
                color: Theme.bgAlt
                border.width: 1
                border.color: pageItem.isMatch
                              ? (pdfv.winActive ? Theme.accent : Theme.inactive)
                              : Theme.border

                Image {
                    x: 1
                    y: 1
                    width: pageItem.pxW
                    height: pageItem.pxH
                    // Asynchronous, so a 300ms rasterization of a dense page
                    // never stalls the scroll — the sheet underneath is what is
                    // drawn until the page arrives, so nothing flashes and the
                    // geometry never moves (§6.1).
                    asynchronous: true
                    cache: true
                    // A rasterized page is normally already at the size it is
                    // drawn at, and filtering it then costs quality for
                    // nothing — but that stops being true the moment a zoom is
                    // in flight and the pixmap is being scaled to a size it was
                    // not drawn for.
                    smooth: pdfv.scaling
                    sourceSize.width: pageItem.rxW
                    sourceSize.height: pageItem.rxH
                    source: "image://pdfpage/" + pdfv.docKey + "/" + pdfv.gen
                            + "/" + pageItem.index
                }
            }

            // The page number, in the margin beside the sheet — a position
            // readout that does not sit on top of the document. Dropped when
            // the sheet leaves no room for it rather than overlapping (§5.4).
            PixelText {
                anchors.right: parent.right
                anchors.top: parent.top
                color: pdfv.winActive ? Theme.textDim : Theme.inactive
                // The margin it sits in is the one the PAN left, not the
                // symmetric one: dragging the sheet right must not slide the
                // number under it (§5.4 — dropped, never overlapped).
                visible: (view.width - pageItem.pxW) / 2 + pdfv.panX > width + 8
                text: String(pageItem.index + 1)
            }
        }
    }

    // ---- the pointer, over the page view -------------------------------------
    // Declared AFTER the view so it sits on top of it and sees the wheel first
    // — the view's own `WheelScroll` is at `z: -1` inside it and takes whatever
    // this one declines, which is how a nested wheel handler works everywhere
    // in apps/ (apps/AGENTS.md, "Scrolling"). Keep the view the FIRST child:
    // tools/pdf-profile.py drives `v.children[0]`.
    //
    // It accepts ONLY the middle button, so a left press still reaches the
    // pane's focus/context MouseArea underneath, a right click still opens the
    // menu, and the side buttons still walk document history (§11.1). Nothing
    // in this window is a text field, so no primary-selection paste is being
    // taken away from anything.
    MouseArea {
        id: grab
        anchors.fill: view
        acceptedButtons: Qt.MiddleButton
        cursorShape: grab.panning ? Qt.ClosedHandCursor : Qt.ArrowCursor
        preventStealing: true

        property bool panning: false
        property real fromX: 0
        property real fromY: 0
        property real atPan: 0
        property real atY: 0

        onPressed: function (m) {
            grab.panning = true;
            grab.fromX = m.x; grab.fromY = m.y;
            grab.atPan = pdfv.panX; grab.atY = view.contentY;
        }
        onReleased: grab.panning = false
        onCanceled: grab.panning = false
        // 1:1 with the pointer, from where the press was — never accumulated
        // per event, so a drag that runs into the end of the document and back
        // out again returns to exactly where the finger says it should.
        onPositionChanged: function (m) {
            if (!grab.panning) return;
            var minY = view.originY;
            var span = Math.max(0, view.contentHeight - view.height);
            view.contentY = Math.max(minY, Math.min(minY + span,
                                                    grab.atY - (m.y - grab.fromY)));
            pdfv.panX = pdfv.clampPanX(grab.atPan - (m.x - grab.fromX));
        }

        // Ctrl+wheel zooms; every other wheel is left UNACCEPTED and falls
        // through to the view's WheelScroll, so plain scrolling is untouched
        // (docs/DESIGN.md §11 — "Ctrl+scroll / Ctrl +/- zoom" is a platform
        // convention that works everywhere, unprompted).
        //
        // By the DISTANCE scrolled, not once per event, and the discriminator
        // is viewer's verbatim (viewer/qml/ImageViewer.qml): a trackpad fires a
        // burst of small pixelDelta events per flick, and a factor per EVENT
        // would slam the range shut in a dozen of them. exp(ln(1.25)/120 · d)
        // makes one classic detent exactly x1.25 — one press of the `+` cell —
        // and anything smaller a proportional fraction of it.
        onWheel: function (w) {
            if (!(w.modifiers & Qt.ControlModifier)) { w.accepted = false; return; }
            var ad = w.angleDelta.y;
            var d = w.pixelDelta.y !== 0 ? w.pixelDelta.y * 3
                  : Math.abs(ad) >= 120  ? ad          // a real wheel detent
                  :                        ad / 4;     // touchpad sub-pixel
            if (d !== 0) pdfv.zoomAt(Math.exp(Math.log(1.25) / 120 * d), w.x, w.y);
            w.accepted = true;
        }
    }
}

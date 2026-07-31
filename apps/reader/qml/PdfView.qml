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
// (document, generation, page), so Qt's own pixmap cache is the page cache:
// scrolling back up a document redraws nothing. The URL carries the generation
// so a file that changed on disk actually re-rasterizes (docs/DESIGN.md §6.1).
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
                x: Math.round((view.width - pageItem.pxW) / 2) - 1
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
                    smooth: false           // a rasterized page is already at
                                            // the size it is drawn at
                    sourceSize.width: pageItem.pxW
                    sourceSize.height: pageItem.pxH
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
                visible: (view.width - pageItem.pxW) / 2 > width + 8
                text: String(pageItem.index + 1)
            }
        }
    }
}

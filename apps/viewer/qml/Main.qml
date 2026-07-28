import QtQuick
import QtQuick.Window

// viewer's window: a GRID of image panes with their controls in the hyprvtb
// titlebar. The flip-through set + start index come from main.py (startImages /
// startIndex — the opened file's sibling images, in filer's order if it passed
// `--order`); each pane holds its own position in that one shared list, so ‹ / ›
// move the FOCUSED pane and leave the others where they are. Being a real
// Wayland Window, the hyprvtb plugin gives it the same vertical titlebar / drag
// / resize / minimize as filer and surfer; `Titlebar` (context property) bridges
// its button column.
//
// ---- split view ----
// `sp` adds a pane, `xp` closes the focused one, up to `maxPanes` (9). The panes
// tile a rows x cols grid — cols = ceil(sqrt(n)), rows = ceil(n/cols) — so 2
// panes are side by side (surfer's split, which this is modelled on), 4 are a
// 2x2, and a short last row has its final pane span the leftover columns rather
// than leaving a hole. `colW`/`rowW` are the divider positions as WEIGHTS, so a
// resized window keeps the proportions; they are persisted per grid shape
// (Prefs.saveWeights, on release of the drag — never per motion event).
//
// `focusPane` is which pane the CHROME acts on: every titlebar button, the
// footer, the scrub bar and every key read it, which is why they needed no
// per-pane variants. Unlike surfer, no pane ever takes Qt's active focus — the
// keys live on `stage`, the one item that holds the window's focus — so the
// panes cannot fight over it and there is nothing to retarget. A pane is focused
// by clicking it, by zooming over it, by dropping on it, or with Tab / Ctrl+1..9.
Window {
    id: win

    property var images: startImages    // [{ name, path }] — shared by all panes
    readonly property int paneMax: maxPanes

    // Focus-aware foreground, in lock-step with the titlebar (see filer).
    readonly property bool act: win.active

    // ---- panes ----
    // One row per pane; `idx` is its position in `images`. Bumped `paneRev`
    // re-evaluates anything reading paneRep.itemAt() (a Repeater's items are not
    // a bindable property — surfer's tabRev does the same job).
    ListModel { id: panes }
    property int focusPane: 0
    property int paneRev: 0
    // the model's count as a plain property: a ListModel id is not reachable
    // from outside the file, and tools/split-test.py asserts on this
    readonly property int paneCount: panes.count

    readonly property Item current: (paneRev >= 0 && paneRep.count > focusPane && focusPane >= 0
                                     && paneRep.itemAt(focusPane))
                                    ? paneRep.itemAt(focusPane).view : null

    function paneIdx(p) {
        return (p >= 0 && p < panes.count) ? panes.get(p).idx : -1;
    }
    function setPaneIdx(p, i) {
        if (p < 0 || p >= panes.count || !images.length) return;
        panes.setProperty(p, "idx", ((i % images.length) + images.length) % images.length);
    }
    function addPane() {
        if (panes.count >= paneMax || !images.length) return;
        // start the new pane on the image after the last one already shown, so
        // splitting twice walks forward through the folder instead of showing
        // the same picture three times
        var last = -1;
        for (var i = 0; i < panes.count; i++) last = Math.max(last, panes.get(i).idx);
        panes.append({ idx: (last + 1) % images.length });
        paneRev += 1;
        focusPane = panes.count - 1;
    }
    function closePane(p) {
        if (panes.count <= 1 || p < 0 || p >= panes.count) return;
        panes.remove(p);
        paneRev += 1;
        focusPane = Math.max(0, Math.min(focusPane, panes.count - 1));
    }
    function focusNextPane(step) {
        if (panes.count < 2) return;
        focusPane = (focusPane + step + panes.count) % panes.count;
    }

    // A drop (or `--split`): show `entries` starting in pane `p`. Paths viewer
    // has not seen are APPENDED to the shared list rather than replacing it, so
    // ‹ / › can still walk back to whatever was open before — and so a file
    // dropped twice keeps one slot. Extra files in one drop open extra panes
    // (that IS "open a bunch of images at once"), never overwriting panes the
    // user has already arranged.
    function openInPane(p, entries) {
        if (!entries || !entries.length) return;
        var imgs = images.slice();
        var at = [];
        for (var i = 0; i < entries.length; i++) {
            var hit = -1;
            for (var k = 0; k < imgs.length; k++)
                if (imgs[k].path === entries[i].path) { hit = k; break; }
            if (hit < 0) { imgs.push({ name: entries[i].name, path: entries[i].path }); hit = imgs.length - 1; }
            at.push(hit);
        }
        images = imgs;
        if (panes.count === 0) panes.append({ idx: at[0] });
        else setPaneIdx(p, at[0]);
        for (var j = 1; j < at.length && panes.count < paneMax; j++) {
            panes.append({ idx: at[j] });
            paneRev += 1;
        }
        focusPane = Math.max(0, Math.min(p, panes.count - 1));
    }

    // ---- grid geometry ----
    readonly property int cols: Math.max(1, Math.ceil(Math.sqrt(Math.max(1, panes.count))))
    // Math.max(1, cols) is not belt-and-braces: `cols` reads as its int default
    // 0 for the first evaluation of this binding, and 1/0 is an Infinity that
    // converts to 0 rows — a "1x0" grid shape, which then misses the saved
    // divider weights.
    readonly property int rows: Math.max(1, Math.ceil(Math.max(1, panes.count) / Math.max(1, cols)))
    readonly property string shapeKey: cols + "x" + rows
    readonly property int divW: 4
    readonly property int minPane: 48
    property var colW: [1]
    property var rowW: [1]

    readonly property real gridW: Math.max(1, width - (cols - 1) * divW)
    readonly property real gridH: Math.max(1, height - (rows - 1) * divW)

    function evenW(n) {
        var a = [];
        for (var i = 0; i < n; i++) a.push(1 / n);
        return a;
    }
    // Clamp + renormalise whatever came out of prefs: a hand-edited or
    // stale-shaped file must not be able to give a pane zero (or negative) width.
    function normW(a, n) {
        if (!a || a.length !== n) return evenW(n);
        var out = [], sum = 0, i;
        for (i = 0; i < n; i++) { var v = Math.max(0.02, Number(a[i]) || 0); out.push(v); sum += v; }
        for (i = 0; i < n; i++) out[i] = out[i] / sum;
        return out;
    }
    // the grid shape changed (a pane was added or closed): pick up this shape's
    // saved dividers, or split evenly.
    //
    // Hung off `shapeKey`, NOT off cols/rows: those two settle one at a time, so
    // a handler on either runs while the other is still the old value and reads
    // a shape that never exists (1 pane -> 2 fired for "1x2" and "2x2", never
    // for "2x1") — which silently meant a saved divider was never restored.
    // shapeKey passes through the same intermediates, but it is the LAST
    // evaluation that wins, and that one is the real shape.
    function reshape() {
        var s = Prefs.loadWeights(shapeKey) || {};
        colW = normW(s.col, cols);
        rowW = normW(s.row, rows);
    }
    onShapeKeyChanged: reshape()

    function colX(i) {
        var s = 0;
        for (var k = 0; k < i && k < colW.length; k++) s += colW[k];
        return s * gridW + i * divW;
    }
    function colWidth(i) { return (colW[i] || 0) * gridW; }
    function rowY(i) {
        var s = 0;
        for (var k = 0; k < i && k < rowW.length; k++) s += rowW[k];
        return s * gridH + i * divW;
    }
    function rowHeight(i) { return (rowW[i] || 0) * gridH; }

    // how many panes are in row r, and how many columns pane p spans (the last
    // pane of a short last row takes the leftover columns, so 3 panes are a full
    // row of one under a full row of two, with no empty cell)
    function rowCount(r) { return Math.max(0, Math.min(cols, panes.count - r * cols)); }
    function paneRow(p) { return Math.floor(p / cols); }
    function paneCol(p) { return p - paneRow(p) * cols; }
    function paneSpan(p) {
        var r = paneRow(p), c = paneCol(p);
        return (r === rows - 1 && c === rowCount(r) - 1) ? cols - c : 1;
    }
    function paneX(p) { return colX(paneCol(p)); }
    function paneW(p) {
        var c = paneCol(p), last = c + paneSpan(p) - 1;
        return colX(last) + colWidth(last) - colX(c);
    }
    function paneY(p) { return rowY(paneRow(p)); }
    function paneH(p) { return rowHeight(paneRow(p)); }

    // Every divider to draw: one between each pair of panes that share a row,
    // plus one full-width between each pair of rows. Per row rather than one
    // full-height line per column, because a spanning pane in a short last row
    // must not have a divider drawn across it.
    readonly property var dividers: {
        var out = [], r, c;
        for (r = 0; r < rows; r++)
            for (c = 0; c + 1 < rowCount(r); c++)
                out.push({ vert: true, row: r, at: c });
        for (r = 0; r + 1 < rows; r++)
            out.push({ vert: false, row: r, at: r });
        return out;
    }
    // Drag the boundary between columns i and i+1 to window x `px`. The pair's
    // COMBINED weight is fixed, so only those two panes resize; minPane keeps
    // either from being dragged shut.
    function dragCol(i, px) {
        if (i < 0 || i + 1 >= colW.length) return;
        var pair = colW[i] + colW[i + 1];
        var span = pair * gridW;
        var left = Math.max(minPane, Math.min(span - minPane, px - colX(i)));
        if (span <= 2 * minPane) return;
        var a = colW.slice();
        a[i] = left / gridW;
        a[i + 1] = pair - a[i];
        colW = a;
    }
    function dragRow(i, py) {
        if (i < 0 || i + 1 >= rowW.length) return;
        var pair = rowW[i] + rowW[i + 1];
        var span = pair * gridH;
        if (span <= 2 * minPane) return;
        var top = Math.max(minPane, Math.min(span - minPane, py - rowY(i)));
        var a = rowW.slice();
        a[i] = top / gridH;
        a[i + 1] = pair - a[i];
        rowW = a;
    }

    readonly property bool has: images.length > 0 && current !== null
    readonly property string curName: {
        var i = paneIdx(focusPane);
        return (i >= 0 && i < images.length) ? images[i].name : "";
    }

    title: curName !== "" ? curName : "viewer"
    width: 900
    height: 620
    minimumWidth: 320
    minimumHeight: 240
    visible: true
    color: Theme.bg

    onClosing: Qt.quit()

    function next() { if (images.length) setPaneIdx(focusPane, paneIdx(focusPane) + 1); }
    function prev() { if (images.length) setPaneIdx(focusPane, paneIdx(focusPane) - 1); }

    // ---- hyprvtb titlebar buttons: the viewer controls ----
    // state: 0 normal, 2 disabled (flip greys out on a single item, `xp` on a
    // single pane). They all act on the FOCUSED pane. A video swaps the zoom/fit
    // controls for play/pause (‹ / › stay as skip prev/next); the scrub bar
    // (below) replaces them for scrubbing.
    readonly property var tbButtons: {
        const multi = images.length > 1 ? 0 : 2;
        const one = panes.count > 1 ? 0 : 2;
        const full = panes.count < paneMax ? 0 : 2;
        const split = [
            { id: "addpane",   label: "sp", state: full, tip: "split: add a pane" },
            { id: "closepane", label: "xp", state: one,  tip: "close this pane" },
        ];
        if (current && current.isVideo) {
            return [
                { id: "playpause", label: current.videoPlaying ? "‖" : "▶", state: 0,
                  tip: current.videoPlaying ? "pause" : "play" },
                { id: "prev",  label: "‹", state: multi, tip: "previous" },
                { id: "next",  label: "›", state: multi, tip: "next" },
            ].concat(split, [{ id: "close", label: "×", state: 0, tip: "close" }]);
        }
        return [
            { id: "prev",    label: "‹",   state: multi, tip: "previous image" },
            { id: "next",    label: "›",   state: multi, tip: "next image" },
            { id: "zoomout", label: "−",   state: 0,     tip: "zoom out" },
            { id: "zoomin",  label: "+",   state: 0,     tip: "zoom in" },
            { id: "fit",     label: "fit", state: 0,     tip: "fit to pane" },
        ].concat(split, [{ id: "close", label: "×", state: 0, tip: "close" }]);
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    // footer readout at the bottom of the inner column: which pane (only once
    // there is more than one), then position + name within it. (The live
    // playback time isn't put here — a fast-changing footer would re-raster the
    // stacked text every tick; the scrub bar shows position instead.)
    readonly property string footerStr: {
        var i = paneIdx(focusPane);
        if (i < 0 || i >= images.length) return "";
        var pfx = panes.count > 1 ? ("p" + (focusPane + 1) + "/" + panes.count + "  ") : "";
        return pfx + (i + 1) + "/" + images.length + "  " + images[i].name;
    }
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    // Push the scrub bar: shown at the focused pane's position for a video,
    // hidden for an image. Driven by a timer while playing (position moves) and
    // immediately on any switch into/out of video.
    function pushPlaybar() {
        if (current && current.isVideo && current.videoDuration > 0)
            Titlebar.setPlaybar(true, current.videoPosition / current.videoDuration);
        else
            Titlebar.setPlaybar(false, 0);
    }
    Timer {
        interval: 250; repeat: true
        running: win.current !== null && win.current.isVideo
        onTriggered: win.pushPlaybar()
    }
    onCurrentChanged: win.pushPlaybar()

    Component.onCompleted: {
        var start = Math.max(0, Math.min(startIndex, Math.max(0, images.length - 1)));
        panes.append({ idx: images.length ? start : 0 });
        for (var i = 1; i < startPanes; i++) addPane();
        focusPane = 0;
        paneRev += 1;
        reshape();
        Titlebar.setButtons(tbButtons);
        Titlebar.setFooter(footerStr);
        win.pushPlaybar();
    }

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "prev":      win.prev();                    break;
            case "next":      win.next();                    break;
            case "playpause": if (win.current) win.current.togglePlay();   break;
            case "zoomout":   if (win.current) win.current.zoomBy(0.8);    break;
            case "zoomin":    if (win.current) win.current.zoomBy(1.25);   break;
            case "fit":       if (win.current) win.current.fit();          break;
            case "addpane":   win.addPane();                 break;
            case "closepane": win.closePane(win.focusPane);  break;
            case "close":     Qt.quit();                     break;
            }
        }
        // scrub bar dragged/scrolled in the titlebar → seek the focused pane
        function onSeek(frac) { if (win.current) win.current.seekFraction(frac); }
    }

    // The one item that holds the window's focus, so the keys have exactly one
    // owner however many panes there are.
    Item {
        id: stage
        anchors.fill: parent
        focus: true

        // Zoom: +/- and 0 (fit), with or without Ctrl — Ctrl+= and Ctrl+- are
        // what every other app on this desktop uses, and the bare keys are what
        // an image viewer has always used, so both work. Ctrl+wheel zooms too:
        // ImageViewer's WheelHandler takes EVERY modifier (see its comment).
        Keys.onPressed: (e) => {
            const ctrl = (e.modifiers & Qt.ControlModifier) !== 0;
            switch (e.key) {
            case Qt.Key_Left:                      win.prev(); e.accepted = true; break;
            case Qt.Key_Right:                     win.next(); e.accepted = true; break;
            // Space plays/pauses a video, else advances to the next image
            case Qt.Key_Space:
                if (win.current && win.current.isVideo) win.current.togglePlay();
                else win.next();
                e.accepted = true; break;
            case Qt.Key_Escape:                    Qt.quit();  e.accepted = true; break;
            case Qt.Key_Plus: case Qt.Key_Equal:
                if (win.current) win.current.zoomBy(1.25); e.accepted = true; break;
            case Qt.Key_Minus:
                if (win.current) win.current.zoomBy(0.8);  e.accepted = true; break;
            case Qt.Key_0:
                if (win.current) win.current.fit(); e.accepted = true; break;
            // ---- panes ----
            case Qt.Key_Backslash:                 win.addPane();               e.accepted = true; break;
            case Qt.Key_W:
                if (ctrl) {
                    if (panes.count > 1) win.closePane(win.focusPane);
                    else Qt.quit();
                    e.accepted = true;
                }
                break;
            case Qt.Key_Tab:                       win.focusNextPane(1);        e.accepted = true; break;
            case Qt.Key_Backtab:                   win.focusNextPane(-1);       e.accepted = true; break;
            default:
                // Ctrl+1..9 points the chrome at that pane
                if (ctrl && e.key >= Qt.Key_1 && e.key <= Qt.Key_9) {
                    var p = e.key - Qt.Key_1;
                    if (p < panes.count) win.focusPane = p;
                    e.accepted = true;
                }
                break;
            }
        }

        // ---- the panes ----
        Repeater {
            id: paneRep
            model: panes
            delegate: Item {
                id: pane
                required property int index
                required property int idx
                readonly property alias view: iv
                readonly property bool focused: win.focusPane === index

                x: win.paneX(index)
                y: win.paneY(index)
                width: win.paneW(index)
                height: win.paneH(index)
                clip: true

                ImageViewer {
                    id: iv
                    anchors.fill: parent
                    winActive: win.active
                    paneFocused: pane.focused
                    source: (pane.idx >= 0 && pane.idx < win.images.length)
                            ? ("file://" + encodeURI(win.images[pane.idx].path)) : ""
                    name: (pane.idx >= 0 && pane.idx < win.images.length)
                          ? win.images[pane.idx].name : ""
                    onFocusRequested: win.focusPane = pane.index
                }

                // Clicking a pane points the chrome at it. DragThreshold so the
                // Flickable underneath keeps drag-panning a zoomed image: the
                // tap is cancelled the moment the press turns into a drag.
                TapHandler {
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    gesturePolicy: TapHandler.DragThreshold
                    onTapped: win.focusPane = pane.index
                }

                // ---- drop target ----
                // Every pane receives its own drops, so dragging images out of
                // filer (or any source offering local file URLs) into a
                // particular pane is what puts them there. Files.mediaEntries
                // decodes the uri-list with QUrl — never encodeURI/decodeURI in
                // QML, which leaves `#` and `?` mangled (filer/AGENTS.md).
                // A DropArea has no pointer input of its own, so it shadows
                // neither the tap above nor the Flickable below.
                DropArea {
                    id: dz
                    anchors.fill: parent
                    property bool takes: false
                    onEntered: (d) => {
                        dz.takes = Files.mediaEntries(d.urls).length > 0;
                        if (!dz.takes) d.accepted = false;
                    }
                    onExited: dz.takes = false
                    onDropped: (d) => {
                        var got = Files.mediaEntries(d.urls);
                        dz.takes = false;
                        // nothing viewer can decode: decline, so the source
                        // shows a refused drop instead of a silent no-op
                        if (!got.length) { d.accepted = false; return; }
                        d.acceptProposedAction();
                        win.openInPane(pane.index, got);
                    }
                }

                // drop feedback: the pane that would receive it
                Rectangle {
                    anchors.fill: parent
                    visible: dz.containsDrag && dz.takes
                    color: "transparent"
                    border.width: 2
                    border.color: Theme.accent
                    z: 20
                }
            }
        }

        // Which pane the chrome is pointed at — a 1px accent frame, drawn over
        // the image and grabbing no input (surfer's split marks its focused pane
        // the same way). Only meaningful once there are two.
        Rectangle {
            visible: panes.count > 1
            z: 9
            x: win.paneX(win.focusPane)
            y: win.paneY(win.focusPane)
            width: win.paneW(win.focusPane)
            height: win.paneH(win.focusPane)
            color: "transparent"
            border.width: 1
            border.color: win.act ? Theme.accent : Theme.dim
        }

        // The dividers: drag one to trade space between the two panes it
        // separates. Persisted per grid shape on RELEASE, not per motion event.
        Repeater {
            model: win.dividers
            delegate: Rectangle {
                id: div
                required property var modelData
                readonly property bool vert: modelData.vert

                z: 10
                x: vert ? (win.colX(modelData.at) + win.colWidth(modelData.at))
                        : 0
                y: vert ? win.rowY(modelData.row)
                        : (win.rowY(modelData.at) + win.rowHeight(modelData.at))
                width:  vert ? win.divW : stage.width
                height: vert ? win.rowHeight(modelData.row) : win.divW
                color: dragArea.pressed || dragArea.containsMouse ? Theme.accent : Theme.border

                MouseArea {
                    id: dragArea
                    anchors.fill: parent
                    anchors.leftMargin:   div.vert ? -3 : 0
                    anchors.rightMargin:  div.vert ? -3 : 0
                    anchors.topMargin:    div.vert ? 0 : -3
                    anchors.bottomMargin: div.vert ? 0 : -3
                    hoverEnabled: true
                    cursorShape: div.vert ? Qt.SplitHCursor : Qt.SplitVCursor
                    onPositionChanged: (m) => {
                        if (!pressed) return;
                        var p = mapToItem(stage, m.x, m.y);
                        if (div.vert) win.dragCol(div.modelData.at, p.x);
                        else          win.dragRow(div.modelData.at, p.y);
                    }
                    onReleased: Prefs.saveWeights(win.shapeKey, win.colW, win.rowW)
                }
            }
        }
    }
}

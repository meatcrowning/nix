import QtQuick
import QtQuick.Window
import QtWebEngine
import "../../qmlcommon"

// surfer — minimal wal-themed browser. The content engine is QtWebEngine
// (open Chromium); ALL of the browser chrome lives in the hyprvtb titlebar:
//   • outer column: the stacked title doubles as an editable ADDRESS BAR
//     (click it, the compositor grabs the keyboard, type, Enter to go).
//   • inner column: back / fwd / reload / copy-url, a separator, then one
//     button per TAB (2-letter label from the page title, drag to reorder,
//     click the active one to close), and a new-tab button at the bottom.
// The window itself is pure page — no in-window toolbar or tab strip.
Window {
    id: win

    width: 1100
    height: 720
    minimumWidth: 480
    minimumHeight: 320
    visible: true
    color: Theme.bg

    // The window title IS the address bar: the plugin renders it as the stacked
    // outer-column text and seeds its editor from it. Keep it the live URL.
    title: current ? current.url.toString() : "surfer"

    readonly property string homeUrl: "https://start.duckduckgo.com/"

    // Page zoom, shared by every tab and persisted — the level + persistence
    // live in the Zoom bridge (main.py). Ctrl+wheel reaches it two ways (see the
    // WheelHandler below + each view's onZoomFactorChanged): a QML handler for
    // Qt builds where the view ignores Ctrl+wheel, and the view's own zoomFactor
    // for builds where Chromium zooms natively and eats the wheel first.

    // ---- webpage tooltips (title=, etc.) rendered in-window: they slide out to
    // the LEFT of the cursor and slide back in on hide — like the hyprvtb
    // titlebar tooltips. Position comes from the point Chromium reports on the
    // request (request.x/y, view-relative == window-relative since the view
    // fills the window); a HoverHandler over the WebEngineView surface doesn't
    // get fed live hover positions, so the request point is the reliable source.
    property string tipText: ""
    property bool tipShown: false
    property real tipX: 0
    property real tipY: 0
    // `view` is the pane the page lives in: request.x/y are VIEW-relative, and a
    // view only spans the whole window when the split is off — so the pane's own
    // x/y is what turns them back into window coordinates.
    function showTooltip(view, request) {
        request.accepted = true;   // suppress the native tooltip; draw our own
        if (request.type === TooltipRequest.Show && request.text.length > 0) {
            tipText = request.text;
            tipX = request.x + (view ? view.x : 0);
            tipY = request.y + (view ? view.y : 0);
            tipShown = true;
        } else {
            tipShown = false;      // keep tipText so it stays legible while retracting
        }
    }

    onClosing: { win.saveSession(); Qt.quit(); }

    // ---- tabs ----
    // Each row is { tid, seed, cold }: tid is a stable id (survives reorder/remove
    // so titlebar button ids and the active-tab pointer stay valid); seed is only
    // the initial url — live navigation state stays inside each WebEngineView.
    //
    // `cold` marks a restored tab that has not been navigated yet. Its view is
    // real (so tab order, ids, drag-reorder and the titlebar buttons all behave
    // normally) but carries no url, which means no renderer process, no network
    // and no paint for it. Restoring a session used to load every tab at once:
    // two tabs kept Chromium busy for ~7s after the window had already appeared,
    // for pages nobody was looking at. A cold tab warms on first activation and
    // is an ordinary tab from then on. Every append must set this role — the
    // first one defines it for the model.
    ListModel { id: tabs }
    property int nextTid: 1
    property int currentTab: 0
    property int tabRev: 0   // bumped on any add/remove/move so tbButtons re-evaluates

    // ---- split view ----
    // Two tabs in one window, divided by a draggable splitter — kitty's model,
    // and kitty's two buttons: `|` splits RIGHT (a vertical divider, panes side
    // by side) and `_` splits DOWN (a horizontal one, panes stacked).
    // `splitVertical` is which, and it is the ONLY thing that differs between
    // them: pane A (always `currentTab`) takes the LEADING slice of the active
    // axis, pane B (`splitTab`, while `splitOn`) the trailing one.
    // `focusPane` is which of the two the CHROME acts on — the address bar,
    // back/fwd/reload, dark mode and the dialogs all follow it, so every
    // pane-agnostic thing below keeps working by reading `current`, which now
    // means "the focused pane's view" rather than "the current tab's view".
    // The panes hold two DIFFERENT tabs by construction: one WebEngineView can
    // only be in one place, so showInPane() swaps rather than duplicates.
    property bool splitOn: false
    property bool splitVertical: true   // true = `|` side by side, false = `_` stacked
    property int splitTab: -1     // tab index in pane B, -1 = none
    property int focusPane: 0     // 0 = A (left/top), 1 = B (right/bottom)
    // ONE ratio, reused on whichever axis is active, so re-orienting keeps the
    // proportion the divider was left at.
    property real splitRatio: 0.5
    readonly property int splitterW: 4
    // Geometry along the ACTIVE axis: width when vertical, height when stacked.
    // Everything here is clamped away from zero on purpose — a zero-size rect
    // handed to the compositor aborts the session (see apps/AGENTS.md), and a
    // window narrower/shorter than two minimum panes is otherwise exactly how
    // you get one.
    readonly property int splitAxisLen: splitVertical ? width : height
    readonly property int splitAvail: Math.max(2, splitAxisLen - splitterW)
    readonly property int minPaneLen: Math.max(1, Math.min(120, Math.floor(splitAvail / 2)))
    readonly property int paneALen: splitOn
        ? Math.max(minPaneLen, Math.min(splitAvail - minPaneLen,
                                        Math.round(splitAvail * splitRatio)))
        : splitAxisLen
    readonly property int paneBOff: paneALen + splitterW          // B's x (or y)
    readonly property int paneBLen: Math.max(1, splitAxisLen - paneBOff)

    // …resolved to real rects, so nothing below has to know about the axis.
    readonly property int paneAX: 0
    readonly property int paneAY: 0
    readonly property int paneAW: splitOn && splitVertical ? paneALen : Math.max(1, width)
    readonly property int paneAH: splitOn && !splitVertical ? paneALen : Math.max(1, height)
    readonly property int paneBX: splitVertical ? paneBOff : 0
    readonly property int paneBY: splitVertical ? 0 : paneBOff
    readonly property int paneBW: splitVertical ? paneBLen : Math.max(1, width)
    readonly property int paneBH: splitVertical ? Math.max(1, height) : paneBLen

    readonly property int focusTab: (splitOn && focusPane === 1) ? splitTab : currentTab
    readonly property Item current: (focusTab >= 0 && viewRep.count > focusTab)
                                    ? viewRep.itemAt(focusTab) : null
    // Typing goes to the pane the chrome is pointed at, and clicking into a
    // pane points the chrome at it (the delegate's onActiveFocusChanged).
    //
    // `retargeting` is what keeps those two from fighting. Swapping a pane's tab
    // hides one view and shows another, and Qt hands the active focus of the
    // view it just hid to whatever else will take it — the OTHER pane. That
    // reads exactly like a click over there, and the chrome followed it: with
    // the left pane focused, clicking any off-screen tab put it in the left pane
    // and then jumped the focus to the right one (caught headlessly, not
    // guessed). So focus we move ourselves is flagged and ignored on the way
    // back in, and it is applied via callLater so the visibility bindings have
    // settled before we pick the view to focus.
    property bool retargeting: false
    onFocusTabChanged: focusCurrentPane()
    function focusCurrentPane() {
        retargeting = true;
        Qt.callLater(applyPaneFocus);
    }
    function applyPaneFocus() {
        if (current) current.forceActiveFocus();
        retargeting = false;
    }

    function setSplitRatio(r) {
        splitRatio = Math.max(0.08, Math.min(0.92, r));
    }
    // Put tab `i` in pane `pane` (0 left, 1 right). If the other pane already
    // holds it the two panes swap, which is the only way to keep them distinct.
    function showInPane(pane, i) {
        if (i < 0 || i >= tabs.count) return;
        if (pane === 1 && !splitOn) pane = 0;
        if (pane === 1) {
            if (i === currentTab && splitTab >= 0) currentTab = splitTab;
            splitTab = i;
        } else {
            if (splitOn && i === splitTab) splitTab = currentTab;
            currentTab = i;
        }
        tabRev += 1;
    }
    // The orientation is a preference, not session state: it persists in
    // prefs.json next to splitRatio, so the split comes back the way it was
    // left. Written only when it actually changes.
    function setSplitVertical(v) {
        if (splitVertical === v) return;
        splitVertical = v;
        Prefs.saveSplitVertical(v);
    }
    // Both split buttons land here — `|` with true, `_` with false. Each stays a
    // TOGGLE, the way the single "sp" button was, and the pair adds re-orienting:
    //   split off              -> open in that orientation
    //   split on, same button  -> close the split
    //   split on, other button -> re-orient in place, keeping both panes
    // Opening takes the tab to the right of the current one (or the one to its
    // left), and makes a home tab when this is the only tab there is — a split
    // with nothing in the second pane is not a split.
    function toggleSplit(vertical) {
        if (vertical === undefined) vertical = splitVertical;
        if (splitOn && splitVertical === vertical) {
            splitOn = false;
            splitTab = -1;
            focusPane = 0;
        } else if (splitOn) {
            setSplitVertical(vertical);
        } else {
            var other = currentTab + 1 < tabs.count ? currentTab + 1
                      : (currentTab - 1 >= 0 ? currentTab - 1 : -1);
            if (other < 0) {
                tabs.append({ tid: nextTid, seed: homeUrl, cold: false });
                nextTid += 1;
                other = tabs.count - 1;
            }
            // orientation first, so the panes are never laid out for one frame
            // along the axis we are about to leave
            setSplitVertical(vertical);
            splitTab = other;
            splitOn = true;
            focusPane = 1;
        }
        tabRev += 1;
    }

    // WAKE nudge: after the window is un-hidden (roll-up restore) QtWebEngine
    // presents black until it redraws; hide+show the live view to force a frame.
    property bool nudging: false
    Timer { id: nudgeTimer; interval: 32; onTriggered: win.nudging = false }
    function nudgeCurrent() { win.nudging = true; nudgeTimer.restart(); }

    property int dlSeq: 0   // per-download key for download toasts

    // opens in the FOCUSED pane (the left one whenever the split is off)
    function newTab(url) {
        tabs.append({ tid: nextTid, seed: url, cold: false });
        nextTid += 1;
        if (splitOn && focusPane === 1) splitTab = tabs.count - 1;
        else currentTab = tabs.count - 1;
        tabRev += 1;
    }
    // like newTab but leaves focus on the current tab (middle-click a link)
    function newTabBg(url) {
        tabs.append({ tid: nextTid, seed: (url && url !== "") ? url : homeUrl, cold: false });
        nextTid += 1;
        tabRev += 1;
    }
    // Navigate a restored tab for the first time. Clearing `cold` is what the
    // delegate watches; it then sets its own url from the seed.
    function warmTab(i) {
        if (i < 0 || i >= tabs.count) return;
        if (!tabs.get(i).cold) return;
        tabs.setProperty(i, "cold", false);
        tabRev += 1;
    }
    // 2-letter label for a tab with no title yet (cold, or still loading):
    // the start of its host, which is far more use than a placeholder dot.
    function seedLabel(u) {
        var h = ("" + (u || "")).replace(/^[a-z-]+:\/\//, "").replace(/^www\./, "");
        h = h.replace(/[\/?#].*$/, "");
        return h.length > 0 ? h.substring(0, 2) : "·";
    }
    function tabIndexByTid(tid) {
        for (var i = 0; i < tabs.count; i++)
            if (tabs.get(i).tid === tid) return i;
        return -1;
    }
    // where an index lands once row `removed` is gone; -1 = it WAS that row
    function shiftIndex(idx, removed) {
        if (idx < 0) return -1;
        if (idx > removed) return idx - 1;
        if (idx === removed) return -1;
        return idx;
    }
    function closeTab(i) {
        if (i < 0 || i >= tabs.count) return;
        if (tabs.count <= 1) { Qt.quit(); return; }
        var wasCur = currentTab, wasSplit = splitTab;
        tabs.remove(i);
        currentTab = shiftIndex(wasCur, i);
        if (currentTab < 0) currentTab = Math.min(i, tabs.count - 1);
        if (splitOn) {
            splitTab = shiftIndex(wasSplit, i);
            // the right pane's tab was the one closed (or the shift collided
            // with the left pane): give it any other tab, and if there is no
            // other tab left there is nothing to split — fold back to one pane.
            if (splitTab < 0 || splitTab === currentTab) {
                splitTab = -1;
                for (var k = 0; k < tabs.count; k++)
                    if (k !== currentTab) { splitTab = k; break; }
                if (splitTab < 0) { splitOn = false; focusPane = 0; }
            }
        }
        tabRev += 1;
    }
    function moveTab(fromIdx, toIdx) {
        if (fromIdx < 0 || toIdx < 0 || fromIdx >= tabs.count || toIdx >= tabs.count || fromIdx === toIdx)
            return;
        var curTid = tabs.get(currentTab).tid;
        // the panes are addressed by INDEX but reordering only moves rows, so
        // the right pane has to be re-found by tid exactly like the left one
        var splTid = (splitOn && splitTab >= 0) ? tabs.get(splitTab).tid : -1;
        tabs.move(fromIdx, toIdx, 1);
        currentTab = tabIndexByTid(curTid);
        if (splTid >= 0) splitTab = tabIndexByTid(splTid);
        tabRev += 1;
    }

    // ---- memory saver: discard background tabs after idle ----
    // QtWebEngine keeps a full renderer process (V8 heap + GPU/canvas buffers
    // included) alive for every tab that has ever loaded, visible or not — an
    // offscreen measurement found a background tab pins ~120 MB each (6 loaded
    // tabs -> ~1.2 GB of tree RSS, and hiding them changed nothing by itself).
    // The lever that actually reclaims that memory is QtWebEngine's page
    // lifecycle: `Discarded` tears the hidden page's renderer down and frees it.
    // The cost is that the tab RELOADS when you come back to it, so the discard
    // is deliberately conservative — a tab is only ever reclaimed when it is
    // BOTH off-screen long enough AND beyond the kept-warm count. Two guards
    // keep recently used tabs instant:
    //   * `discardKeepCount` — the most recently used hidden tabs are never
    //     discarded at all, whatever their age (raise it to keep more warm
    //     tabs resident; each one pins ~120 MB while it lives);
    //   * `discardAfter` — only a hidden tab beyond that count is reclaimed,
    //     and only once it has been off-screen this long, so it is an abandoned
    //     tab that gives its memory back, never a just-visited one.
    // The on-screen pane is never discarded. Re-selecting a discarded tab sets
    // it back to Active (see onPaneChanged below), which is what reloads it.
    property int discardAfter: 30 * 60 * 1000   // ms a hidden tab may be off-screen before discard
    property int discardKeepCount: 4            // most-recent hidden tabs always kept warm
    Timer {
        id: discardTimer
        interval: 30 * 1000
        repeat: true
        running: true
        onTriggered: win.discardIdleTabs()
    }
    function discardIdleTabs() {
        if (viewRep.count === 0) return
        // collect the hidden tabs that still hold a renderer
        var candidates = []
        for (var i = 0; i < viewRep.count; i++) {
            var v = viewRep.itemAt(i)
            if (!v) continue
            if (v.pane >= 0) continue                                  // on-screen: keep warm
            if (v.cold) continue                                       // cold: holds no renderer
            if (v.lifecycleState === WebEngineView.LifecycleState.Discarded) continue
            candidates.push(v)
        }
        // never discard the most recently used hidden tabs, whatever their age
        if (candidates.length <= win.discardKeepCount) return
        candidates.sort(function (a, b) { return b.lastSeen - a.lastSeen })
        for (var j = win.discardKeepCount; j < candidates.length; j++) {
            var c = candidates[j]
            if (Date.now() - c.lastSeen < win.discardAfter) continue   // recently used: keep instant
            c.lifecycleState = WebEngineView.LifecycleState.Discarded
        }
    }

    // spinner: tell the titlebar plugin whether the current tab is loading, so
    // it animates a | \ - / spinner above the address bar (see hyprvtb).
    readonly property bool currentLoading: current ? current.loading : false
    onCurrentLoadingChanged: Titlebar.setLoading(currentLoading)

    // 2-letter tab label from the page title (what the titlebar used to show).
    // Strip a leading notification counter — "(3) ", "[3] ", bullet markers —
    // so a site that blinks its title for unread counts doesn't flip the label
    // back and forth.
    function tabLabel(v, seed) {
        var t = (v && v.title) ? v.title.trim() : "";
        t = t.replace(/^\s*[\(\[]\s*\d+\s*[\)\]]\s*/, "");
        t = t.replace(/^\s*[•·*•●✱]\s*/, "").trim();
        if (t.length === 0) return seedLabel(seed);
        return t.substring(0, 2);
    }


    // ---- page theming: the desktop's ONE scrollbar, on the page too ----
    // docs/DESIGN.md §9.2 / apps/qmlcommon/VScroll.qml is the one scrollbar
    // idiom for the whole desktop (win31/beveled/flat, picked in Settings >
    // Appearance) and a page's own Chromium scrollbar is the one control that
    // idiom did not reach — it is styled here, via ::-webkit-scrollbar*,
    // to the same widths, the same bg/bgAlt/border/dim/accent ladder, the
    // same hard 1px bevels (no radius, no gradient) and, for win31, the same
    // stepper arrows (drawn as a solid pixel-triangle SVG rather than a glyph,
    // for the same reason VScroll draws them as geometry: the desktop font has
    // no arrow glyphs at all — §2.3). Injected via runJavaScript on load
    // (WebEngineScript isn't a creatable QML element in this Qt build).
    //
    // What CSS cannot reach that VScroll does: a scrollbar-button's arrow ink
    // cannot tell "nothing left to scroll" (§10's dead-arrow rule) since that
    // needs the flickable's own position, which is not exposed to CSS at all —
    // so a win31 stepper here never dims. Everything else (idle/hover/active
    // ink and bevel direction, per §9.2) is reachable and done.
    function cssColor(c) {
        return "rgb(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + ","
             + Math.round(c.b * 255) + ")";
    }
    // A 9x5 (or 5x9) solid pixel-triangle, matching VScroll's Arrow component's
    // outline. shape-rendering:crispEdges keeps it hard-edged rather than
    // antialiased at this tiny size.
    function triangleUri(inkCss, dir) {
        var svg;
        if (dir === "up")
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="9" height="5" viewBox="0 0 9 5" shape-rendering="crispEdges"><polygon points="4,0 8,4 0,4" fill="' + inkCss + '"/></svg>';
        else if (dir === "down")
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="9" height="5" viewBox="0 0 9 5" shape-rendering="crispEdges"><polygon points="0,0 8,0 4,4" fill="' + inkCss + '"/></svg>';
        else if (dir === "left")
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="5" height="9" viewBox="0 0 5 9" shape-rendering="crispEdges"><polygon points="0,4 4,0 4,8" fill="' + inkCss + '"/></svg>';
        else
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="5" height="9" viewBox="0 0 5 9" shape-rendering="crispEdges"><polygon points="4,4 0,0 0,8" fill="' + inkCss + '"/></svg>';
        return "data:image/svg+xml;charset=utf8," + encodeURIComponent(svg);
    }
    function scrollbarJs() {
        var style = (typeof DeskStyle !== "undefined" && DeskStyle
                     && ["win31", "beveled", "flat"].indexOf(DeskStyle.scrollbarStyle) !== -1)
                   ? DeskStyle.scrollbarStyle : "win31";
        var isWin31 = style === "win31", isFlat = style === "flat";
        // barW is the desktop VScroll width in DEVICE-independent px (§9.2).
        // A ::-webkit-scrollbar width is in CSS px, which Chromium multiplies
        // by the page zoom — so at a zoom of 0.83 a 16px bar renders ~13px on
        // screen and reads SKINNIER than the Qt-chrome VScroll, which does not
        // zoom. Divide by the zoom so the on-screen width stays barW regardless
        // (physical = barW/z * z = barW). screenDPR cancels and is not involved.
        var z = (typeof Zoom !== "undefined" && Zoom && Zoom.level > 0) ? Zoom.level : 1;
        var barW0 = isWin31 ? 16 : (style === "beveled" ? 14 : 11);
        var barW = Math.round(barW0 / z * 100) / 100;

        // the same three-tone ladder VScroll reads off the wallpaper palette
        var dark = cssColor(Theme.bg), trackC = cssColor(Theme.bgAlt),
            face = cssColor(Theme.border), light = cssColor(Theme.dim),
            accent = cssColor(Theme.accent),
            inkDim = cssColor(Theme.textDim), inkHover = cssColor(Theme.text);

        var css = "::-webkit-scrollbar{width:" + barW + "px;height:" + barW + "px;}"
                + "::-webkit-scrollbar-corner{background:" + trackC + ";}";

        if (isFlat) {
            // square, hard-edged, no bevel, no arrows, solid textDim on bgAlt
            css += "::-webkit-scrollbar-track{background:" + trackC + ";border:none;}"
                 + "::-webkit-scrollbar-thumb{background:" + inkDim + ";border:none;}"
                 + "::-webkit-scrollbar-thumb:hover{background:" + inkHover + ";}"
                 + "::-webkit-scrollbar-thumb:active{background:" + accent + ";}"
                 + "::-webkit-scrollbar-button{display:none;}";
        } else {
            // win31 / beveled: recessed track, raised thumb — the same 1px
            // hard bevel Bevel{} draws (light top/left, dark bottom/right for
            // a raised face; swapped for the sunken track)
            css += "::-webkit-scrollbar-track{background:" + trackC + ";"
                 + "border-top:1px solid " + dark + ";border-left:1px solid " + dark + ";"
                 + "border-bottom:1px solid " + light + ";border-right:1px solid " + light + ";}"
                 + "::-webkit-scrollbar-thumb{background:" + face + ";"
                 + "border-top:1px solid " + light + ";border-left:1px solid " + light + ";"
                 + "border-bottom:1px solid " + dark + ";border-right:1px solid " + dark + ";}"
                 + "::-webkit-scrollbar-thumb:active{background:" + accent + ";}";

            if (isWin31) {
                var up = triangleUri(inkDim, "up"), upH = triangleUri(inkHover, "up"), upA = triangleUri(accent, "up");
                var dn = triangleUri(inkDim, "down"), dnH = triangleUri(inkHover, "down"), dnA = triangleUri(accent, "down");
                var lf = triangleUri(inkDim, "left"), lfH = triangleUri(inkHover, "left"), lfA = triangleUri(accent, "left");
                var rt = triangleUri(inkDim, "right"), rtH = triangleUri(inkHover, "right"), rtA = triangleUri(accent, "right");
                var raised = "border-top:1px solid " + light + ";border-left:1px solid " + light + ";"
                           + "border-bottom:1px solid " + dark + ";border-right:1px solid " + dark + ";";
                var sunken = "border-top:1px solid " + dark + ";border-left:1px solid " + dark + ";"
                           + "border-bottom:1px solid " + light + ";border-right:1px solid " + light + ";";
                var btnBase = "display:block;width:" + barW + "px;height:" + barW + "px;"
                            + "background-color:" + face + ";background-repeat:no-repeat;background-position:center;" + raised;
                css += "::-webkit-scrollbar-button:vertical:start:decrement{" + btnBase + "background-image:url(" + up + ");}"
                     + "::-webkit-scrollbar-button:vertical:end:increment{" + btnBase + "background-image:url(" + dn + ");}"
                     + "::-webkit-scrollbar-button:horizontal:start:decrement{" + btnBase + "background-image:url(" + lf + ");}"
                     + "::-webkit-scrollbar-button:horizontal:end:increment{" + btnBase + "background-image:url(" + rt + ");}"
                     + "::-webkit-scrollbar-button:vertical:start:increment,::-webkit-scrollbar-button:vertical:end:decrement,"
                     + "::-webkit-scrollbar-button:horizontal:start:increment,::-webkit-scrollbar-button:horizontal:end:decrement{display:none;}"
                     + "::-webkit-scrollbar-button:hover{background-color:" + face + ";}"
                     + "::-webkit-scrollbar-button:vertical:start:decrement:hover{background-image:url(" + upH + ");}"
                     + "::-webkit-scrollbar-button:vertical:end:increment:hover{background-image:url(" + dnH + ");}"
                     + "::-webkit-scrollbar-button:horizontal:start:decrement:hover{background-image:url(" + lfH + ");}"
                     + "::-webkit-scrollbar-button:horizontal:end:increment:hover{background-image:url(" + rtH + ");}"
                     // pressed: the bevel inverts and the arrow inks accent, like Stepper{}
                     + "::-webkit-scrollbar-button:vertical:start:decrement:active{" + sunken + "background-image:url(" + upA + ");}"
                     + "::-webkit-scrollbar-button:vertical:end:increment:active{" + sunken + "background-image:url(" + dnA + ");}"
                     + "::-webkit-scrollbar-button:horizontal:start:decrement:active{" + sunken + "background-image:url(" + lfA + ");}"
                     + "::-webkit-scrollbar-button:horizontal:end:increment:active{" + sunken + "background-image:url(" + rtA + ");}";
            } else {
                css += "::-webkit-scrollbar-button{display:none;}";
            }
        }

        return "(function(){var id='__surfer_scrollbar__';var css=" + JSON.stringify(css) + ";"
             + "var s=document.getElementById(id);"
             + "if(!s){s=document.createElement('style');s.id=id;(document.head||document.documentElement).appendChild(s);}"
             + "s.textContent=css;})();";
    }
    function reinjectScrollbar() {
        for (var i = 0; i < viewRep.count; i++) {
            var v = viewRep.itemAt(i);
            if (v) v.runJavaScript(win.scrollbarJs());
        }
    }
    // scrollbarJs() is re-run on each page load (see onLoadingChanged) so new
    // loads pick up the current palette/style; reinjectScrollbar() live-updates
    // already-open pages when the wallpaper palette OR the scrollbarStyle
    // setting changes.
    Connections {
        target: WalPalette
        function onChanged() { win.reinjectScrollbar(); }
    }
    Connections {
        target: (typeof DeskStyle !== "undefined") ? DeskStyle : null
        function onChanged() { win.reinjectScrollbar(); }
    }
    // The bar width is zoom-compensated (scrollbarJs), so a zoom change has to
    // re-inject or the page bar keeps the previous zoom's width until reload.
    Connections {
        target: (typeof Zoom !== "undefined") ? Zoom : null
        function onLevelChanged() { win.reinjectScrollbar(); }
    }

    // ---- dark mode (DarkMode bridge) ----
    // The config panel slides out from the left edge; the "dm" titlebar button
    // toggles it. The page style is applied by the profile's document-creation
    // courier (PAGE_STYLE_RUNTIME_JS — see Main.qml's profile block), so it
    // lands before the first frame; this function only LIVE-refreshes
    // already-painted pages when a setting changes, by asking each open page's
    // courier to re-fetch Python's current CSS. dmRev bumps on `changed` so the
    // QML bindings below (this-site state, slider values) re-evaluate.
    property bool dmPanelOpen: false
    property int dmRev: 0
    readonly property string dmCurUrl: win.current ? win.current.url.toString() : ""
    readonly property string dmHost: {
        void win.dmRev;
        return win.dmCurUrl.replace(/^[a-z]+:\/\//, "").replace(/\/.*$/, "");
    }
    readonly property bool dmSiteOn: { void win.dmRev; return DarkMode.isSiteEnabled(win.dmCurUrl); }
    readonly property bool dmFontOn: { void win.dmRev; return DarkMode.isSystemFontSite(win.dmCurUrl); }
    function reinjectDark() {
        for (var i = 0; i < viewRep.count; i++) {
            var v = viewRep.itemAt(i);
            if (v) v.runJavaScript("window.__surferPageStyleRefresh()");
        }
    }
    Connections {
        target: DarkMode
        function onChanged() { win.dmRev += 1; win.reinjectDark(); }
    }

    // A page asked the browser to open a URL in a new foreground tab (currently
    // only the image-click handler — see imageClickJs / CmdHandler in main.py).
    Connections {
        target: PageCmd
        function onOpenTab(url) { if (url && url !== "") win.newTab(url); }
    }

    // Build the right-click menu item list from the snapshot the webview handed
    // us (see onContextMenuRequested) and pop the reusable ContextMenu. Image /
    // clipboard bits go through the view's own web actions; navigation + search
    // reuse our tab helpers. `c.pos` is already in WINDOW coordinates — the
    // caller adds the view's own x/y, which is zero only when the split is off.
    function showContextMenu(view, c) {
        var items = [];
        function sep() { if (items.length) items.push({ separator: true }); }

        // Spelling suggestions for a misspelled word under the cursor in an
        // editable field (Chromium fills request.spellCheckerSuggestions). Each
        // suggestion rewrites the word in place via replaceMisspelledWord; if the
        // checker has no guesses we still show a greyed marker so the feature is
        // visibly present. Capped so a long list can't dominate the menu.
        if (c.editable && c.misspelled !== "") {
            if (c.suggestions && c.suggestions.length > 0) {
                var n = Math.min(c.suggestions.length, 6);
                for (var si = 0; si < n; si++)
                    items.push({ label: c.suggestions[si],
                                 trigger: (function(w){ return function(){ view.replaceMisspelledWord(w); }; })(c.suggestions[si]) });
            } else {
                items.push({ label: "No spelling suggestions", enabled: false });
            }
            items.push({ separator: true });
        }

        if (c.link !== "") {
            items.push({ label: "Open link in new tab",        trigger: function(){ win.newTab(c.link); } });
            items.push({ label: "Open link in background tab",  trigger: function(){ win.newTabBg(c.link); } });
            items.push({ label: "Copy link address",           trigger: function(){ Clip.copy(c.link); } });
            items.push({ label: "Save link as…",               trigger: function(){ view.triggerWebAction(WebEngineView.DownloadLinkToDisk); } });
        }
        if (c.isImage && c.media !== "") {
            sep();
            items.push({ label: "Open image in new tab",  trigger: function(){ win.newTab(c.media); } });
            items.push({ label: "Save image…",            trigger: function(){ view.triggerWebAction(WebEngineView.DownloadImageToDisk); } });
            items.push({ label: "Copy image",             trigger: function(){ view.triggerWebAction(WebEngineView.CopyImageToClipboard); } });
            items.push({ label: "Copy image address",     trigger: function(){ Clip.copy(c.media); } });
        }
        if (c.selection !== "") {
            sep();
            items.push({ label: "Copy", trigger: function(){ view.triggerWebAction(WebEngineView.Copy); } });
            var q = c.selection.length > 24 ? c.selection.substring(0, 24) + "…" : c.selection;
            items.push({ label: "Search for \"" + q + "\"",
                         trigger: function(){ win.newTab("https://duckduckgo.com/?q=" + encodeURIComponent(c.selection)); } });
        }
        if (c.editable) {
            sep();
            items.push({ label: "Undo", trigger: function(){ view.triggerWebAction(WebEngineView.Undo); } });
            items.push({ label: "Redo", trigger: function(){ view.triggerWebAction(WebEngineView.Redo); } });
            items.push({ separator: true });
            items.push({ label: "Cut",   enabled: c.selection !== "", trigger: function(){ view.triggerWebAction(WebEngineView.Cut); } });
            items.push({ label: "Copy",  enabled: c.selection !== "", trigger: function(){ view.triggerWebAction(WebEngineView.Copy); } });
            items.push({ label: "Paste",                               trigger: function(){ view.triggerWebAction(WebEngineView.Paste); } });
            items.push({ label: "Paste as plain text",                 trigger: function(){ view.triggerWebAction(WebEngineView.PasteAndMatchStyle); } });
            items.push({ label: "Select all",                          trigger: function(){ view.triggerWebAction(WebEngineView.SelectAll); } });
        }
        sep();
        items.push({ label: "Back",    enabled: view.canGoBack,    trigger: function(){ view.goBack(); } });
        items.push({ label: "Forward", enabled: view.canGoForward, trigger: function(){ view.goForward(); } });
        items.push({ label: "Reload",                              trigger: function(){ view.reload(); } });
        items.push({ separator: true });
        items.push({ label: "Save page as…",    trigger: function(){ view.triggerWebAction(WebEngineView.SavePage); } });
        items.push({ label: "View page source", trigger: function(){ win.newTab("view-source:" + view.url); } });
        items.push({ separator: true });
        items.push({ label: "Copy page address", trigger: function(){ Clip.copy("" + view.url); } });
        if (!c.editable)
            items.push({ label: "Select all", trigger: function(){ view.triggerWebAction(WebEngineView.SelectAll); } });

        ctxMenu.open(c.pos.x, c.pos.y, items);
    }

    // Address text -> url: explicit schemes pass through, host-ish strings get
    // https://, anything else becomes a DuckDuckGo search.
    function normalize(t) {
        t = t.trim();
        if (t === "") return "";
        if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(t)) return t;
        if (t.indexOf("localhost") === 0) return "http://" + t;
        if (!/\s/.test(t) && t.indexOf(".") !== -1) return "https://" + t;
        return "https://duckduckgo.com/?q=" + encodeURIComponent(t);
    }

    function saveSession() {
        var urls = [];
        for (var i = 0; i < tabs.count; i++) {
            var v = viewRep.count > i ? viewRep.itemAt(i) : null;
            // A cold tab has a real view with an EMPTY url, so the live value
            // has to be tested as a string and the seed used when it is blank —
            // otherwise a session saved before you ever visited that tab would
            // write the home page over the url you actually had open.
            var live = (v && v.url) ? ("" + v.url) : "";
            var u = live !== "" ? live : ("" + (tabs.get(i).seed || ""));
            urls.push(u !== "" ? u : win.homeUrl);
        }
        Session.save(urls, currentTab, splitOn ? splitTab : -1);
    }

    // ---- site permission prompts (notifications, camera, mic, geolocation…) ----
    // QtWebEngine raises onPermissionRequested for any feature in the "ask"
    // state; we surface a small allow/block bar over the top of the page.
    // grant()/deny() persist per-origin in the profile (non-off-the-record), so
    // each site is only asked once. Requests queue so two of them don't fight
    // over the single bar. Perm.what() (main.py) gives the human wording.
    property var permQueue: []
    property var permCurrent: null
    property string permMsg: ""
    function askPermission(perm) {
        permQueue.push(perm);
        if (!permCurrent) nextPermission();
    }
    function nextPermission() {
        if (permQueue.length === 0) { permCurrent = null; permMsg = ""; return; }
        permCurrent = permQueue.shift();
        var host = ("" + permCurrent.origin).replace(/^[a-z]+:\/\//, "").replace(/\/.*$/, "");
        permMsg = (host || "this site") + " wants to " + Perm.what(permCurrent.permissionType);
    }
    function grantPermission() { if (permCurrent) permCurrent.grant(); nextPermission(); }
    function denyPermission()  { if (permCurrent) permCurrent.deny();  nextPermission(); }

    // How many dialogs/pickers a tab is sitting on. A deferred request keeps the
    // page blocked with nothing on screen, so the tab's tooltip has to say so —
    // it's the only clue that the tab is waiting on YOU. Guarded because
    // tbButtons evaluates once before the overlays below have been created.
    readonly property int dlgRev: (jsDialog ? jsDialog.rev : 0) + (filePicker ? filePicker.rev : 0)
    function waitingFor(view) {
        if (!view || !jsDialog || !filePicker) return 0;
        return jsDialog.countFor(view) + filePicker.countFor(view);
    }

    // ---- hyprvtb titlebar buttons (the browser's real chrome) ----
    readonly property var tbButtons: {
        void tabRev;                    // structural-change dependency
        void dlgRev;                    // …and on a tab gaining/losing a dialog
        var arr = [
            { id: "back",    label: "<",  state: current && current.canGoBack ? 0 : 2,    tip: "back" },
            { id: "fwd",     label: ">",  state: current && current.canGoForward ? 0 : 2, tip: "forward" },
            { id: "reload",  label: current && current.loading ? "x" : "r", state: 0,
              tip: current && current.loading ? "stop loading" : "reload" },
            { id: "copyurl", label: "cu", state: current ? 0 : 2,           tip: "copy url" },
            // dark mode: opens the slide-out config panel (on/off, per-site
            // whitelist, brightness/contrast). Lit (state 1) only while its
            // panel is open — like a pressed menu button — not for the whole
            // time dark mode is enabled.
            { id: "darkmode", label: "dm", state: dmPanelOpen ? 1 : 0,  tip: "dark mode" },
            // split view, kitty's pair: `|` = split right (side by side), `_` =
            // split down (stacked). Note `_` and not `-`: a bare "-" is the
            // SPACER token in the vtb button protocol. Whichever orientation is
            // live is lit, and the tip says what a click will do from here —
            // close it (the lit one) or re-orient into it (the other).
            { id: "vsplit", label: "|", state: splitOn && splitVertical ? 1 : 0,
              tip: (splitOn && splitVertical) ? "close split" : "split right" },
            { id: "hsplit", label: "_", state: splitOn && !splitVertical ? 1 : 0,
              tip: (splitOn && !splitVertical) ? "close split" : "split down" },
            "-",
        ];
        for (var i = 0; i < tabs.count; i++) {
            var v = viewRep.count > i ? viewRep.itemAt(i) : null;
            var sd = tabs.get(i).seed;
            // a cold tab has no title yet — name it by the url it will open
            var ttl = v && v.title ? v.title : (sd ? "" + sd : "tab");
            var asks = waitingFor(v) > 0 ? "asks · " : "";
            // A tab on screen is lit. Which pane it is in, and what a click will
            // do (close it if its pane already has the chrome's attention, focus
            // that pane otherwise), is in the tooltip — the titlebar has no
            // third lit state to say it with.
            var shown = (i === currentTab) || (splitOn && i === splitTab);
            var where = "";
            if (splitOn && shown)
                where = (i === focusTab ? "close · " : "focus · ")
                      + (i === currentTab ? (splitVertical ? "left · " : "top · ")
                                          : (splitVertical ? "right · " : "bottom · "));
            else if (shown)
                where = "close · ";
            arr.push({ id: "tab:" + tabs.get(i).tid, label: tabLabel(v, sd),
                       state: shown ? 1 : 0,
                       tip: asks + where + ttl, drag: true });
        }
        arr.push({ id: "newtab", label: "+t", state: 0, tip: "new tab" });
        // settings pins to the bottom of the inner column (hyprvtb bottom-anchor)
        arr.push({ id: "settings", label: "st", state: 0, tip: "userscripts folder / settings", bottom: true });
        return arr;
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    Connections {
        target: Titlebar
        function onClicked(id) {
            if (id === "back")    { if (win.current) win.current.goBack(); return; }
            if (id === "fwd")     { if (win.current) win.current.goForward(); return; }
            if (id === "reload") {
                if (!win.current) return;
                if (win.current.loading) win.current.stop(); else win.current.reload();
                return;
            }
            if (id === "copyurl") { if (win.current) Clip.copy(win.current.url.toString()); return; }
            if (id === "darkmode") { win.dmPanelOpen = !win.dmPanelOpen; return; }
            if (id === "newtab")  { win.newTab(win.homeUrl); return; }
            if (id === "vsplit")  { win.toggleSplit(true); return; }
            if (id === "hsplit")  { win.toggleSplit(false); return; }
            if (id === "settings") { UserScripts.openFolder(); return; }
            if (id.indexOf("tab:") === 0) {
                var idx = win.tabIndexByTid(parseInt(id.substring(4)));
                if (idx < 0) return;
                // re-click the focused pane's tab = close it (unsplit muscle
                // memory); click the OTHER pane's tab = move the chrome there
                // rather than swapping two tabs that are both already visible;
                // anything else = show it in the focused pane.
                if (idx === win.focusTab) win.closeTab(idx);
                else if (win.splitOn && idx === win.currentTab) win.focusPane = 0;
                else if (win.splitOn && idx === win.splitTab) win.focusPane = 1;
                else win.showInPane(win.focusPane, idx);
                return;
            }
        }
        // drag-reorder: move the src tab to the dst tab's slot
        function onReordered(srcId, dstId) {
            if (srcId.indexOf("tab:") !== 0 || dstId.indexOf("tab:") !== 0) return;
            win.moveTab(win.tabIndexByTid(parseInt(srcId.substring(4))),
                        win.tabIndexByTid(parseInt(dstId.substring(4))));
        }
        // the in-bar address editor was submitted
        function onAddrSubmitted(text) {
            var u = win.normalize(text);
            if (u !== "" && win.current) win.current.url = u;
        }
        // un-hidden: force the live view to repaint out of its black state
        function onWake() { win.nudgeCurrent(); }
    }

    // A later `surfer <url>` launch (a link clicked in another app — surfer is
    // the system default browser) handed its URL to THIS process over the
    // single-instance socket and exited, instead of starting a second owner of
    // the persistent WebEngineProfile below. Open it the same way the address
    // bar and startUrl do: normalize() -> newTab().
    Connections {
        target: Instance
        function onOpenUrl(u) {
            win.newTab(("" + u).trim() !== "" ? win.normalize("" + u) : win.homeUrl);
            // Wayland gives a client no way to raise or focus ITSELF — that
            // needs an xdg-activation token from the launching app — so these
            // are very likely no-ops under Hyprland. They are free and correct
            // wherever they do work, so they stay. Do NOT reach for `hyprctl
            // dispatch` instead: under this Lua config it evaluates its
            // argument as Lua and `hl.dsp.focuswindow` is nil, so it would act
            // on the USER'S active window.
            win.raise();
            win.requestActivate();
        }
    }

    Component.onCompleted: {
        Titlebar.setTitleEdit(true);
        Titlebar.setLoading(currentLoading);
        splitRatio = Prefs.loadSplitRatio();
        // both read with a default, so a prefs.json written before either
        // existed simply comes back at 0.5 and side-by-side
        splitVertical = Prefs.loadSplitVertical();
        if (startUrl !== "") {
            newTab(normalize(startUrl));
        } else {
            var s = Session.load();
            if (s.tabs && s.tabs.length > 0) {
                // Append directly rather than through newTab(): newTab moves
                // currentTab to each tab as it is added, and a tab that is
                // momentarily current would warm itself. Only the tab you were
                // last on is born hot; the rest load when you first go to them.
                //
                // currentTab is set BEFORE the loop, and that ordering is the
                // whole trick. A delegate's `activeTab` binding starts at the
                // default false and evaluating it to true counts as a CHANGE, so
                // the handler fires during construction — with currentTab still
                // 0, tab 0 warmed itself every time and quietly loaded a page
                // nobody asked for (caught by pointing a restored session at a
                // local server and watching which paths were requested). Set it
                // first and every delegate but `cur` evaluates false, which
                // matches the default and emits nothing.
                var cur = Math.min(Math.max(0, s.current), s.tabs.length - 1);
                currentTab = cur;
                // …and the same ordering rule covers the right pane: its tab is
                // on screen from the first frame, so it must be known BEFORE the
                // delegates exist or it would warm itself from the wrong index.
                var spl = ("split" in s) ? s.split : -1;
                if (spl >= 0 && spl < s.tabs.length && spl !== cur) {
                    splitTab = spl;
                    splitOn = true;
                }
                for (var i = 0; i < s.tabs.length; i++) {
                    tabs.append({ tid: nextTid, seed: s.tabs[i],
                                  cold: i !== cur && i !== splitTab });
                    nextTid += 1;
                }
                tabRev += 1;
            } else {
                newTab(homeUrl);
            }
        }
        Titlebar.setButtons(tbButtons);
        // …and claim the focus for the left pane, so a restored split doesn't
        // start with the chrome pointed at whichever view Qt focused first.
        focusCurrentPane();
    }

    // Persistent profile (cookies/cache/localStorage on disk — GM_setValue is
    // localStorage-backed, so it must persist). Downloads land in ~/Downloads.
    WebEngineProfile {
        id: sharedProfile
        objectName: "sharedProfile"   // Python installs the gmxhr scheme handler on this
        storageName: "surfer"
        offTheRecord: false
        // Cosmetic ad-blocking, PROFILE-WIDE and at document-creation: one
        // static courier script (COSMETIC_RUNTIME_JS) that pulls this page's
        // hide rules from Python over surfercos:// and keeps re-applying them
        // through a MutationObserver + pushState/replaceState/popstate hooks.
        // It replaces the old per-view load-finished injection, which flashed
        // the ads first and never re-ran on an SPA route change.
        //
        // Assigned from QML and not from _wire_profile because PySide6 6.11
        // does not bind QQuickWebEngineScriptCollection — `profile.userScripts`
        // is unreachable from Python, while QML reaches it and takes the same
        // Python-made QWebEngineScript list each view takes for userscripts.
        // Cosmetic ad-blocking + the dark-mode/system-font courier ride the
        // same collection.
        Component.onCompleted: userScripts.collection =
            CosmeticInject.scripts.concat(PageStyle.scripts)
        // Spell-checking (red squiggle + right-click suggestions in
        // showContextMenu) is enabled IMPERATIVELY in main.py's _wire_profile,
        // NOT declaratively here: setting spellCheckEnabled/spellCheckLanguages
        // as QML properties on a QQuickWebEngineProfile at construction time is
        // silently dropped (the spellcheck adapter isn't ready yet) — the words
        // never get marked. Calling the setters once the tree is built makes it
        // stick. The language tag it passes is the BASENAME of an installed
        // .bdic, not a locale, and differs per host — main.py's
        // _spell_language() resolves it (en-US.bdic built by surfer.nix on top,
        // Fedora's en_US.bdic on book). tools/spell-test.py is the check.
        // downloads land in ~/Downloads; slow or large ones get a live progress
        // toast (updated in place), every one gets a completion/failure toast —
        // see the Downloads bridge in main.py.
        onDownloadRequested: (download) => {
            download.downloadDirectory = downloadDir;
            // BEFORE accept(): Chromium names the file from the URL path only,
            // so a twitter image (…/media/<id>?format=jpg) arrives with no
            // extension at all. The bridge repairs it from the Content-Type.
            download.downloadFileName = Downloads.fileName(download.downloadFileName,
                                                           download.mimeType);
            download.accept();
            var key = "dl" + (win.dlSeq++);
            var name = download.downloadFileName;
            var path = downloadDir + "/" + download.downloadFileName;
            var started = Date.now();
            download.receivedBytesChanged.connect(function() {
                if (download.isFinished)
                    return;
                // The bridge owns the size/time gate (DESIGN 10.4 — a download
                // that takes TIME deserves a live toast even when small), so
                // feed it every byte change and let it decide + throttle.
                Downloads.progress(key, name, download.receivedBytes,
                                   download.totalBytes, Date.now() - started);
            });
            download.isFinishedChanged.connect(function() {
                if (!download.isFinished)
                    return;
                if (download.state === WebEngineDownloadRequest.DownloadCompleted)
                    Downloads.done(key, name, path);
                else
                    Downloads.failed(key, name);
            });
        }
    }

    // ---- content: one WebEngineView per tab; the one or two on screen are laid
    // out by `pane` (see the split-view block above) ----
    Item {
        id: stage
        anchors.fill: parent

        Repeater {
            id: viewRep
            model: tabs
            WebEngineView {
                id: webview
                required property int index
                required property string seed
                required property bool cold
                // -1 = not on screen. Hidden views keep the FULL window size
                // rather than a pane's, so opening the split doesn't reflow
                // every background tab.
                readonly property int pane: index === win.currentTab ? 0
                                          : ((win.splitOn && index === win.splitTab) ? 1 : -1)
                x: pane === 1 ? win.paneBX : 0
                y: pane === 1 ? win.paneBY : 0
                width: pane === 1 ? win.paneBW : (pane === 0 ? win.paneAW : stage.width)
                height: pane === 1 ? win.paneBH : (pane === 0 ? win.paneAH : stage.height)
                visible: pane >= 0 && !win.nudging
                // clicking into a pane points the chrome at it — unless this is
                // our own retargeting coming back round (see win.retargeting)
                onActiveFocusChanged: if (activeFocus && pane >= 0 && !win.retargeting)
                                          win.focusPane = pane
                profile: sharedProfile
                // Chromium's touch-emulation gesture recognizer: with it on, a
                // plain left-click drag over the page pans it like a touchscreen
                // (docs/DESIGN.md — "scrollbar and wheel only, never click-and-
                // drag to scroll"). Force it off rather than trust the platform
                // default, which is Enabled whenever Chromium THINKS the input
                // device might be a touchscreen. Wheel and the scrollbar are
                // untouched — neither goes through the touch API.
                settings.touchEventsApiEnabled: false
                // Shared, persisted zoom (Ctrl+wheel or Ctrl +/-/0). zoomFactor
                // is NOT a binding and is NEVER persisted from here: the level is
                // owned by the Zoom bridge (changed only via ZoomFilter), and each
                // view just mirrors it — seeded on create, re-applied after a
                // page's navigation reset (onLoadingChanged), and updated live
                // when any tab changes it (Connections below).
                Connections {
                    target: Zoom
                    function onLevelChanged() {
                        if (Math.abs(webview.zoomFactor - Zoom.level) > 0.001)
                            webview.zoomFactor = Zoom.level;
                    }
                }
                // render the page's tooltips ourselves (win.showTooltip), so
                // title= tooltips actually appear and match the DE
                onTooltipRequested: (request) => win.showTooltip(webview, request)
                // userscripts inject via the view's OWN collection (the view
                // ignores a Python QWebEngineProfile) — GM shim, document-start,
                // isolated worlds; see UserScripts in main.py
                userScripts.collection: UserScripts.scriptObjects
                // A cold tab is created with NO url on purpose — that is what
                // keeps it from spawning a renderer and loading the page.
                Component.onCompleted: { zoomFactor = Zoom.level; if (!cold) url = seed; }
                // …and this is where it stops being cold. Two triggers, because
                // a tab can be made current either by becoming the active index
                // (clicking its titlebar button) or by warmTab clearing the role
                // directly; whichever fires first, the other is then a no-op.
                readonly property bool activeTab: pane >= 0
                onActiveTabChanged: if (activeTab && cold) win.warmTab(index)
                onColdChanged: if (!cold && ("" + url) === "") url = seed
                // memory saver (win.discardIdleTabs): every tab remembers when
                // it was last on screen, and a hidden one that has been off for
                // `discardAfter` gets its renderer discarded. Coming back puts
                // the pane on screen again, which fires this and sets the
                // lifecycle state back to Active — that is what reloads a
                // discarded tab — and re-arms the clock.
                property int lastSeen: Date.now()
                onPaneChanged: {
                    if (pane >= 0) {
                        lifecycleState = WebEngineView.LifecycleState.Active
                        lastSeen = Date.now()
                    }
                }
                // closing this tab kills any dialog/picker it was holding — the
                // requests die with the view, so the queues must let go of them
                // here, while the view is still a valid key.
                Component.onDestruction: {
                    if (jsDialog) jsDialog.dropView(webview);
                    if (filePicker) filePicker.dropView(webview);
                }

                // userscripts are injected by the profile (document-start, GM
                // shim — see UserScripts in main.py); this just themes the
                // scrollbar once the page has loaded
                onLoadingChanged: (info) => {
                    if (info.status === WebEngineView.LoadSucceededStatus) {
                        // re-apply the saved zoom after the navigation reset
                        if (Math.abs(webview.zoomFactor - Zoom.level) > 0.001)
                            webview.zoomFactor = Zoom.level;
                        webview.runJavaScript(win.scrollbarJs());
                        // NOTE: dark mode + system-font are NOT applied here any
                        // more. They used to be, at load-finished — the page
                        // painted light first and flipped dark only once images
                        // finished loading. They now ride the shared profile as
                        // a document-creation script (PAGE_STYLE_RUNTIME_JS) that
                        // adopts the style before the first frame; live settings
                        // changes go through win.reinjectDark() below.
                        // click a plain content image -> open it in a new tab
                        webview.runJavaScript(imageClickJs);
                        // air only (empty string on top): sample which GL
                        // driver is actually serving this renderer, to catch
                        // the mid-session fallback that wrecks text antialiasing
                        // — see GPU_PROBE_JS / CmdHandler._log_gpu in main.py
                        if (gpuProbeJs) webview.runJavaScript(gpuProbeJs);
                        // NOTE: cosmetic ad-blocking is NOT here any more. It
                        // used to be, and load-finished is too late by
                        // definition — the ads had already painted, nothing
                        // re-ran on an SPA route change, and a lazily-inserted
                        // ad slot brought no new rules with it. It now rides the
                        // shared profile as a document-creation script; see
                        // sharedProfile.userScripts above and COSMETIC_RUNTIME_JS
                        // / CosmeticInjector in main.py.
                    }
                }

                // a site asked to use notifications / camera / mic / location:
                // queue it for the allow/block bar (win.askPermission)
                onPermissionRequested: (permission) => win.askPermission(permission)

                // alert() / confirm() / prompt() / beforeunload, and the file
                // picker for <input type=file>. BOTH handlers are mandatory:
                // unhandled, Chromium auto-rejects, so prompt() returns null,
                // confirm() returns false, alert() vanishes and the picker never
                // opens — silently, which reads as "the page is broken".
                // Both are queued PER VIEW (the view is passed in): only the
                // current tab's front request is shown, so a background tab
                // can't throw a modal over the page you're reading.
                onJavaScriptDialogRequested: (request) => jsDialog.show(webview, request)
                onFileDialogRequested: (request) => filePicker.show(webview, request)

                // right-click: build a context menu from what was clicked (link,
                // image, selection, editable field) plus the usual page actions,
                // and show our own themed menu (win.showContextMenu) instead of
                // Chromium's. The request's fields must be read now — they're
                // only valid during this call — so we snapshot into locals.
                onContextMenuRequested: (request) => {
                    request.accepted = true;   // suppress the native menu
                    win.showContextMenu(webview, {
                        // view-relative -> window-relative: only equal when this
                        // view spans the window, which a split pane does not
                        pos:         Qt.point(request.position.x + webview.x,
                                              request.position.y + webview.y),
                        link:        "" + request.linkUrl,
                        media:       "" + request.mediaUrl,
                        isImage:     request.mediaType === ContextMenuRequest.MediaTypeImage,
                        selection:   ("" + request.selectedText).trim(),
                        editable:    request.isContentEditable,
                        misspelled:  "" + request.misspelledWord,
                        suggestions: request.spellCheckerSuggestions
                    });
                }

                // link opening: middle-click (InNewBackgroundTab) opens a new
                // background tab; everything else (target=_blank, ctrl-click,
                // window.open) loads in THIS tab — navigating the existing view
                // instead of a fresh one, which also fixes _blank/JS opens that
                // used to spawn a tab that never loaded (empty requestedUrl).
                onNewWindowRequested: (request) => {
                    if (request.destination === WebEngineNewWindowRequest.InNewBackgroundTab)
                        win.newTabBg("" + request.requestedUrl);
                    else if (("" + request.requestedUrl) !== "")
                        webview.url = request.requestedUrl;
                    else
                        win.newTab(win.homeUrl);
                }
                // A page (YouTube's video fullscreen button, etc.) asked to go
                // fullscreen: accept it so the video expands to fill the viewport
                // — which, since the view fills the window, means the video fills
                // the window — but DO NOT flip the window itself to Window.FullScreen.
                // "Fullscreen" here means full-*window*, keeping the compositor
                // titlebar/chrome and the window's size intact.
                onFullScreenRequested: (request) => request.accept()
                // page-initiated close (window.close()) closes its tab
                onWindowCloseRequested: win.closeTab(index)
            }
        }

        // Which pane the chrome is pointed at. The titlebar has no room to say
        // it (a lit tab button means "on screen", and both panes' tabs are on
        // screen), so the window does — a 1px accent frame, drawn over the page
        // and grabbing no input.
        Rectangle {
            visible: win.splitOn
            z: 9
            x: win.focusPane === 1 ? win.paneBX : win.paneAX
            y: win.focusPane === 1 ? win.paneBY : win.paneAY
            width: win.focusPane === 1 ? win.paneBW : win.paneAW
            height: win.focusPane === 1 ? win.paneBH : win.paneAH
            color: "transparent"
            border.width: 1
            border.color: Theme.accent
        }

        // The divider: drag it to trade space between the panes — sideways when
        // the split is vertical, up/down when it is stacked, with the cursor
        // shape to match. One `splitRatio` for both axes, persisted (Prefs) on
        // release, not on every motion event.
        Rectangle {
            id: splitter
            visible: win.splitOn
            z: 10
            x: win.splitVertical ? win.paneALen : 0
            y: win.splitVertical ? 0 : win.paneALen
            width: win.splitVertical ? win.splitterW : Math.max(1, stage.width)
            height: win.splitVertical ? Math.max(1, stage.height) : win.splitterW
            color: splitDrag.pressed ? Theme.accent
                 : (splitDrag.containsMouse ? Theme.accent : Theme.border)

            MouseArea {
                id: splitDrag
                anchors.fill: parent
                // a 4px divider is a 10px grab target, on whichever axis it runs
                anchors.leftMargin: win.splitVertical ? -3 : 0
                anchors.rightMargin: win.splitVertical ? -3 : 0
                anchors.topMargin: win.splitVertical ? 0 : -3
                anchors.bottomMargin: win.splitVertical ? 0 : -3
                hoverEnabled: true
                cursorShape: win.splitVertical ? Qt.SplitHCursor : Qt.SplitVCursor
                onPositionChanged: (m) => {
                    if (!pressed) return;
                    var p = mapToItem(stage, m.x, m.y);
                    win.setSplitRatio(win.splitVertical
                                      ? p.x / Math.max(1, stage.width)
                                      : p.y / Math.max(1, stage.height));
                }
                onReleased: Prefs.saveSplitRatio(win.splitRatio)
            }
        }
    }

    // The desktop's motion, read from the plugin's published key — see
    // qmlcommon/Motion.qml. Both tooltip slides below take it; they used to
    // carry a 220ms literal each, which stopped matching the titlebar tooltip
    // they exist to feel like the moment the desktop converged on the roll.
    Motion { id: motion }

    // webpage tooltip: slides OUT to the left of the cursor point the page
    // reported (a clipped reveal growing leftward, OutCubic at the desktop's
    // slide — the same feel as the hyprvtb titlebar tooltips), and slides back
    // in on hide.
    Item {
        id: tip
        z: 2000
        property real slide: (win.tipShown && win.tipText.length > 0) ? 1 : 0
        Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }
        readonly property real gap: 14
        readonly property real fullW: Math.min(tipLabel.implicitWidth + 14, win.width - 40)
        readonly property real fullH: tipLabel.implicitHeight + 8
        // fixed right edge just left of the cursor, clamped so the fully-revealed
        // chip (which extends fullW to the left) stays on-screen at either margin
        readonly property real rightEdge: Math.max(fullW + 4, Math.min(win.tipX - gap, win.width - 4))
        visible: slide > 0.001
        clip: true
        width: fullW * slide            // grows from 0 → fullW as it slides out
        height: fullH
        x: rightEdge - width            // reveal grows leftward from the fixed right edge
        y: Math.max(4, Math.min(win.tipY - fullH / 2, win.height - fullH - 4))
        Rectangle {
            width: tip.fullW
            height: tip.fullH
            anchors.right: parent.right  // revealed from the right as the clip grows
            color: Theme.bgAlt
            border.color: Theme.accent
            border.width: 1
            PixelText {
                id: tipLabel
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 7; rightMargin: 7 }
                elide: Text.ElideRight
                text: win.tipText
                color: Theme.text
            }
        }
    }

    // ---- permission prompt bar: allow/block, over the top of the page ----
    Rectangle {
        id: permBar
        visible: win.permCurrent !== null
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 36
        color: Theme.bgAlt
        border.width: 1
        border.color: Theme.accent

        PixelText {
            anchors { left: parent.left; leftMargin: 12; right: permBtns.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            elide: Text.ElideRight
            text: win.permMsg
            color: Theme.text
        }
        Row {
            id: permBtns
            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
            spacing: 8
            BrowserButton { label: "allow"; onClicked: win.grantPermission() }
            BrowserButton { label: "block"; onClicked: win.denyPermission() }
        }
    }

    // ---- find in page (Ctrl+F) ----
    // The key is caught by main.py's window-scoped HotkeyFilter, not by a QML
    // Shortcut: Chromium holds the keyboard whenever a view has the focus, so a
    // Shortcut here would race the page for it — the same reason Ctrl +/-/0 go
    // through ZoomFilter. It searches the FOCUSED pane (win.current), like every
    // other pane-agnostic control, and docks below the permission bar while that
    // one is up rather than under it.
    FindBar {
        id: findBar
        view: win.current
        dockY: permBar.visible ? permBar.height : 0
    }
    Connections {
        target: Hotkeys
        function onFind() { findBar.openFind(); }
    }

    // ---- dark-mode config panel: a drawer that slides out from the "dm"
    // button. The hyprvtb titlebar (where the button lives) is on the window's
    // RIGHT edge, and the button sits near the top of that column, so the panel
    // docks at the top-right and slides in from the right edge toward it. A
    // transparent scrim behind it closes it on an outside click.
    MouseArea {
        id: dmScrim
        anchors.fill: parent
        z: 2400
        visible: win.dmPanelOpen
        onClicked: win.dmPanelOpen = false
    }

    // The mouse's back/forward side buttons walk the FOCUSED pane's page
    // history — the canonical reading of the desktop-global rule (docs/DESIGN.md
    // §11), and the same call the titlebar's `<`/`>` make. Sitting above the
    // WebEngineView in z is what keeps it deterministic: Chromium maps buttons
    // 8/9 to history itself, so without an overlay that accepts them first the
    // behaviour would depend on which side saw the event.
    NavButtons {
        onBack:    if (win.current && win.current.canGoBack)    win.current.goBack()
        onForward: if (win.current && win.current.canGoForward) win.current.goForward()
    }
    Rectangle {
        id: dmPanel
        z: 2500
        // slide 0 (hidden, fully off the right edge) -> 1 (docked at the edge)
        property real slide: win.dmPanelOpen ? 1 : 0
        Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }
        visible: slide > 0.001
        width: 248
        height: dmCol.implicitHeight + 24
        x: win.width - slide * width
        y: 8
        color: Theme.bgAlt
        border.width: 1
        border.color: Theme.windowBorder

        Column {
            id: dmCol
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 8

            // header: title + close, then the current host it acts on
            Item {
                width: parent.width
                height: dmTitle.implicitHeight
                PixelText {
                    id: dmTitle
                    anchors.left: parent.left
                    text: "dark mode"
                    color: Theme.accent
                }
                BrowserButton {
                    anchors.right: parent.right
                    label: "×"
                    onClicked: win.dmPanelOpen = false
                }
            }
            PixelText {
                width: parent.width
                elide: Text.ElideRight
                text: win.dmHost !== "" ? win.dmHost : "no page"
                color: Theme.textDim
            }

            // global on/off
            Item {
                width: parent.width
                height: 22
                PixelText { anchors.verticalCenter: parent.verticalCenter; text: "extension"; color: Theme.text }
                BrowserButton {
                    anchors.right: parent.right
                    label: DarkMode.enabled ? "on" : "off"
                    onClicked: DarkMode.setEnabled(!DarkMode.enabled)
                }
            }

            // per-site whitelist toggle (single button, acts on the current host)
            Item {
                width: parent.width
                height: 22
                PixelText { anchors.verticalCenter: parent.verticalCenter; text: "this site"; color: Theme.text }
                BrowserButton {
                    anchors.right: parent.right
                    enabled: win.dmHost !== ""
                    label: win.dmSiteOn ? "on" : "off"
                    onClicked: if (win.current) DarkMode.toggleSite(win.current.url.toString())
                }
            }

            // brightness
            Column {
                width: parent.width
                spacing: 4
                Item {
                    width: parent.width
                    height: dmBrLabel.implicitHeight
                    PixelText { id: dmBrLabel; anchors.left: parent.left; text: "brightness"; color: Theme.text }
                    PixelText { anchors.right: parent.right; text: DarkMode.brightness + "%"; color: Theme.textDim }
                }
                Slider {
                    width: parent.width
                    from: 50; to: 150; step: 5
                    value: DarkMode.brightness
                    onMoved: (v) => DarkMode.setBrightness(v)
                }
            }

            // contrast
            Column {
                width: parent.width
                spacing: 4
                Item {
                    width: parent.width
                    height: dmCoLabel.implicitHeight
                    PixelText { id: dmCoLabel; anchors.left: parent.left; text: "contrast"; color: Theme.text }
                    PixelText { anchors.right: parent.right; text: DarkMode.contrast + "%"; color: Theme.textDim }
                }
                Slider {
                    width: parent.width
                    from: 50; to: 150; step: 5
                    value: DarkMode.contrast
                    onMoved: (v) => DarkMode.setContrast(v)
                }
            }

            // divider
            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // system font: force the desktop pixel font on this site's text
            // (family only; per-site, combines with dark mode).
            Item {
                width: parent.width
                height: 22
                PixelText { anchors.verticalCenter: parent.verticalCenter; text: "system font"; color: Theme.text }
                BrowserButton {
                    anchors.right: parent.right
                    enabled: win.dmHost !== ""
                    label: win.dmFontOn ? "on" : "off"
                    onClicked: if (win.current) DarkMode.toggleSystemFontSite(win.current.url.toString())
                }
            }
        }
    }

    // page dialogs + file picker: modal overlays above the page (and above the
    // dark-mode drawer), below the right-click menu.
    // currentView is what makes the queues per-tab: each panel shows only the
    // current view's front request, and re-syncs when the current tab changes.
    JsDialog {
        id: jsDialog
        anchors.fill: parent
        currentView: win.current
    }
    // No `anchors.fill` and nothing on screen: the file dialog is filer, in its
    // own window (see FilePicker.qml). This is the queue that runs it.
    FilePicker {
        id: filePicker
        currentView: win.current
    }

    // reusable right-click menu — overlays the whole window, above everything.
    ContextMenu {
        id: ctxMenu
        anchors.fill: parent
    }
}

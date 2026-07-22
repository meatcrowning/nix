import QtQuick
import QtQuick.Window
import QtWebEngine

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
    function showTooltip(request) {
        request.accepted = true;   // suppress the native tooltip; draw our own
        if (request.type === TooltipRequest.Show && request.text.length > 0) {
            tipText = request.text;
            tipX = request.x;
            tipY = request.y;
            tipShown = true;
        } else {
            tipShown = false;      // keep tipText so it stays legible while retracting
        }
    }

    onClosing: { win.saveSession(); Qt.quit(); }

    // ---- tabs ----
    // Each row is { tid, seed }: tid is a stable id (survives reorder/remove so
    // titlebar button ids and the active-tab pointer stay valid); seed is only
    // the initial url — live navigation state stays inside each WebEngineView.
    ListModel { id: tabs }
    property int nextTid: 1
    property int currentTab: 0
    property int tabRev: 0   // bumped on any add/remove/move so tbButtons re-evaluates
    readonly property Item current: viewRep.count > currentTab && currentTab >= 0
                                    ? viewRep.itemAt(currentTab) : null

    // WAKE nudge: after the window is un-hidden (roll-up restore) QtWebEngine
    // presents black until it redraws; hide+show the live view to force a frame.
    property bool nudging: false
    Timer { id: nudgeTimer; interval: 32; onTriggered: win.nudging = false }
    function nudgeCurrent() { win.nudging = true; nudgeTimer.restart(); }

    property int dlSeq: 0   // per-download key for download toasts

    function newTab(url) {
        tabs.append({ tid: nextTid, seed: url });
        nextTid += 1;
        currentTab = tabs.count - 1;
        tabRev += 1;
    }
    // like newTab but leaves focus on the current tab (middle-click a link)
    function newTabBg(url) {
        tabs.append({ tid: nextTid, seed: (url && url !== "") ? url : homeUrl });
        nextTid += 1;
        tabRev += 1;
    }
    function tabIndexByTid(tid) {
        for (var i = 0; i < tabs.count; i++)
            if (tabs.get(i).tid === tid) return i;
        return -1;
    }
    function closeTab(i) {
        if (i < 0 || i >= tabs.count) return;
        if (tabs.count <= 1) { Qt.quit(); return; }
        var wasCur = currentTab;
        tabs.remove(i);
        if (wasCur > i) currentTab = wasCur - 1;
        else if (wasCur === i) currentTab = Math.min(i, tabs.count - 1);
        tabRev += 1;
    }
    function moveTab(fromIdx, toIdx) {
        if (fromIdx < 0 || toIdx < 0 || fromIdx >= tabs.count || toIdx >= tabs.count || fromIdx === toIdx)
            return;
        var curTid = tabs.get(currentTab).tid;
        tabs.move(fromIdx, toIdx, 1);
        currentTab = tabIndexByTid(curTid);
        tabRev += 1;
    }

    // spinner: tell the titlebar plugin whether the current tab is loading, so
    // it animates a | \ - / spinner above the address bar (see hyprvtb).
    readonly property bool currentLoading: current ? current.loading : false
    onCurrentLoadingChanged: Titlebar.setLoading(currentLoading)

    // 2-letter tab label from the page title (what the titlebar used to show).
    // Strip a leading notification counter — "(3) ", "[3] ", bullet markers —
    // so a site that blinks its title for unread counts doesn't flip the label
    // back and forth.
    function tabLabel(v) {
        var t = (v && v.title) ? v.title.trim() : "";
        t = t.replace(/^\s*[\(\[]\s*\d+\s*[\)\]]\s*/, "");
        t = t.replace(/^\s*[•·*•●✱]\s*/, "").trim();
        if (t.length === 0) return "·";
        return t.substring(0, 2);
    }


    // ---- page theming: wal-coloured scrollbars ----
    // Chromium's default scrollbars clash with the wal palette, so inject a
    // stylesheet into every page (::-webkit-scrollbar + the standard
    // scrollbar-color) matching the DE. Injected via runJavaScript on load
    // (WebEngineScript isn't a creatable QML element in this Qt build).
    function cssColor(c) {
        return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + ","
             + Math.round(c.b * 255) + "," + c.a.toFixed(3) + ")";
    }
    function scrollbarJs() {
        var bg = cssColor(Theme.bg), thumb = cssColor(Theme.border), hover = cssColor(Theme.accent);
        var css = "::-webkit-scrollbar{width:12px;height:12px;background:" + bg + ";}"
                + "::-webkit-scrollbar-track{background:" + bg + ";}"
                + "::-webkit-scrollbar-thumb{background:" + thumb + ";border:3px solid " + bg + ";}"
                + "::-webkit-scrollbar-thumb:hover{background:" + hover + ";}"
                + "::-webkit-scrollbar-corner{background:" + bg + ";}"
                + "html{scrollbar-color:" + thumb + " " + bg + ";}";
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
    // loads pick up the current palette; reinjectScrollbar() live-updates
    // already-open pages when the wallpaper palette changes.
    Connections {
        target: WalPalette
        function onChanged() { win.reinjectScrollbar(); }
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
            var u = (v && v.url) ? v.url.toString() : tabs.get(i).seed;
            urls.push(u && u !== "" ? u : win.homeUrl);
        }
        Session.save(urls, currentTab);
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

    // ---- hyprvtb titlebar buttons (the browser's real chrome) ----
    readonly property var tbButtons: {
        void tabRev;                    // structural-change dependency
        var arr = [
            { id: "back",    label: "<",  state: current && current.canGoBack ? 0 : 2,    tip: "back" },
            { id: "fwd",     label: ">",  state: current && current.canGoForward ? 0 : 2, tip: "forward" },
            { id: "reload",  label: current && current.loading ? "x" : "r", state: 0,
              tip: current && current.loading ? "stop loading" : "reload" },
            { id: "copyurl", label: "cu", state: current ? 0 : 2,           tip: "copy url" },
            "-",
        ];
        for (var i = 0; i < tabs.count; i++) {
            var v = viewRep.count > i ? viewRep.itemAt(i) : null;
            var ttl = v && v.title ? v.title : "tab";
            arr.push({ id: "tab:" + tabs.get(i).tid, label: tabLabel(v),
                       state: i === currentTab ? 1 : 0,
                       tip: i === currentTab ? "close · " + ttl : ttl, drag: true });
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
            if (id === "newtab")  { win.newTab(win.homeUrl); return; }
            if (id === "settings") { UserScripts.openFolder(); return; }
            if (id.indexOf("tab:") === 0) {
                var idx = win.tabIndexByTid(parseInt(id.substring(4)));
                if (idx < 0) return;
                if (idx === win.currentTab) win.closeTab(idx);  // re-click active tab = close
                else win.currentTab = idx;
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

    Component.onCompleted: {
        Titlebar.setTitleEdit(true);
        Titlebar.setLoading(currentLoading);
        if (startUrl !== "") {
            newTab(normalize(startUrl));
        } else {
            var s = Session.load();
            if (s.tabs && s.tabs.length > 0) {
                for (var i = 0; i < s.tabs.length; i++) newTab(s.tabs[i]);
                currentTab = Math.min(Math.max(0, s.current), tabs.count - 1);
            } else {
                newTab(homeUrl);
            }
        }
        Titlebar.setButtons(tbButtons);
    }

    // Persistent profile (cookies/cache/localStorage on disk — GM_setValue is
    // localStorage-backed, so it must persist). Downloads land in ~/Downloads.
    WebEngineProfile {
        id: sharedProfile
        objectName: "sharedProfile"   // Python installs the gmxhr scheme handler on this
        storageName: "surfer"
        offTheRecord: false
        // downloads land in ~/Downloads; large ones get a live progress toast
        // (updated in place), every one gets a completion/failure toast — see
        // the Downloads bridge in main.py.
        onDownloadRequested: (download) => {
            download.downloadDirectory = downloadDir;
            download.accept();
            var key = "dl" + (win.dlSeq++);
            var name = download.downloadFileName;
            download.receivedBytesChanged.connect(function() {
                if (!download.isFinished && download.totalBytes > 3145728) // >3 MB
                    Downloads.progress(key, name, download.receivedBytes, download.totalBytes);
            });
            download.isFinishedChanged.connect(function() {
                if (!download.isFinished)
                    return;
                if (download.state === WebEngineDownloadRequest.DownloadCompleted)
                    Downloads.done(key, name);
                else
                    Downloads.failed(key, name);
            });
        }
    }

    // ---- content: one WebEngineView per tab, only the current one visible ----
    Item {
        anchors.fill: parent

        Repeater {
            id: viewRep
            model: tabs
            WebEngineView {
                id: webview
                required property int index
                required property string seed
                anchors.fill: parent
                visible: win.currentTab === index && !win.nudging
                profile: sharedProfile
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
                onTooltipRequested: (request) => win.showTooltip(request)
                // userscripts inject via the view's OWN collection (the view
                // ignores a Python QWebEngineProfile) — GM shim, document-start,
                // isolated worlds; see UserScripts in main.py
                userScripts.collection: UserScripts.scriptObjects
                Component.onCompleted: { zoomFactor = Zoom.level; url = seed; }

                // userscripts are injected by the profile (document-start, GM
                // shim — see UserScripts in main.py); this just themes the
                // scrollbar once the page has loaded
                onLoadingChanged: (info) => {
                    if (info.status === WebEngineView.LoadSucceededStatus) {
                        // re-apply the saved zoom after the navigation reset
                        if (Math.abs(webview.zoomFactor - Zoom.level) > 0.001)
                            webview.zoomFactor = Zoom.level;
                        webview.runJavaScript(win.scrollbarJs());
                    }
                }

                // a site asked to use notifications / camera / mic / location:
                // queue it for the allow/block bar (win.askPermission)
                onPermissionRequested: (permission) => win.askPermission(permission)

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
                onFullScreenRequested: (request) => {
                    request.accept();
                    win.visibility = request.toggleOn ? Window.FullScreen : Window.Windowed;
                }
                // page-initiated close (window.close()) closes its tab
                onWindowCloseRequested: win.closeTab(index)
            }
        }
    }

    // webpage tooltip: slides OUT to the left of the cursor point the page
    // reported (a clipped reveal growing leftward, OutCubic ~220ms — the same
    // feel as the hyprvtb titlebar tooltips), and slides back in on hide.
    Item {
        id: tip
        z: 2000
        property real slide: (win.tipShown && win.tipText.length > 0) ? 1 : 0
        Behavior on slide { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
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
}

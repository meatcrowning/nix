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

    function newTab(url) {
        tabs.append({ tid: nextTid, seed: url });
        nextTid += 1;
        currentTab = tabs.count - 1;
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

    // 2-letter tab label from the page title (what the titlebar used to show).
    function tabLabel(v) {
        var t = (v && v.title) ? v.title.trim() : "";
        if (t.length === 0) return "·";
        return t.substring(0, 2);
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

    // Persistent profile (cookies/cache under the app's data dirs), shared by
    // every tab. Downloads land in ~/Downloads with their suggested name.
    WebEngineProfile {
        id: sharedProfile
        storageName: "surfer"
        offTheRecord: false
        onDownloadRequested: (download) => download.accept()
    }

    // ---- content: one WebEngineView per tab, only the current one visible ----
    Item {
        anchors.fill: parent

        Repeater {
            id: viewRep
            model: tabs
            WebEngineView {
                required property int index
                required property string seed
                anchors.fill: parent
                visible: win.currentTab === index && !win.nudging
                profile: sharedProfile
                Component.onCompleted: url = seed

                onNewWindowRequested: (request) => win.newTab(request.requestedUrl)
                onFullScreenRequested: (request) => {
                    request.accept();
                    win.visibility = request.toggleOn ? Window.FullScreen : Window.Windowed;
                }
                // page-initiated close (window.close()) closes its tab
                onWindowCloseRequested: win.closeTab(index)
            }
        }
    }
}

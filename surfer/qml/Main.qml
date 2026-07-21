import QtQuick
import QtQuick.Window
import QtWebEngine

// surfer — minimal wal-themed browser. The content engine is QtWebEngine
// (open Chromium); most of the browser chrome lives in the hyprvtb titlebar's
// app-button column (back/forward/reload/tabs/copy-url), leaving the window
// itself with just an address row + tab strip in filer's pixel-font style.
Window {
    id: win

    width: 1100
    height: 720
    minimumWidth: 480
    minimumHeight: 320
    visible: true
    color: Theme.bg
    title: "surf: " + (current && current.title !== "" ? current.title : "new tab")

    // Focus-aware foreground, same idiom as filer: controls grey to the
    // titlebar's inactive tone while the window is unfocused.
    readonly property color fgAccent: win.active ? Theme.accent : Theme.inactive
    readonly property color fgText:   win.active ? Theme.text  : Theme.inactive

    readonly property string homeUrl: "https://start.duckduckgo.com/"

    onClosing: Qt.quit()

    // ---- tabs ----
    // `seed` is only the initial url; live navigation state stays inside each
    // WebEngineView. NB (prototype): removing a tab makes the Repeater rebuild
    // the views after it, which reloads those tabs — fine for v1.
    ListModel { id: tabs }
    property int currentTab: 0
    readonly property Item current: viewRep.count > currentTab && currentTab >= 0
                                    ? viewRep.itemAt(currentTab) : null

    function newTab(url) {
        tabs.append({ seed: url });
        currentTab = tabs.count - 1;
    }
    function closeTab(i) {
        if (tabs.count <= 1) { Qt.quit(); return; }
        tabs.remove(i);
        if (currentTab >= tabs.count) currentTab = tabs.count - 1;
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

    // ---- hyprvtb titlebar buttons (the browser's real chrome) ----
    readonly property var tbButtons: [
        { id: "back",     label: "<",  state: current && current.canGoBack ? 0 : 2,    tip: "back" },
        { id: "fwd",      label: ">",  state: current && current.canGoForward ? 0 : 2, tip: "forward" },
        { id: "reload",   label: current && current.loading ? "x" : "r", state: 0,
          tip: current && current.loading ? "stop loading" : "reload" },
        { id: "newtab",   label: "+t", state: 0,                          tip: "new tab" },
        { id: "closetab", label: "xt", state: 0,                          tip: "close tab" },
        { id: "nexttab",  label: ">t", state: tabs.count > 1 ? 0 : 2,     tip: "next tab" },
        { id: "copyurl",  label: "cu", state: current ? 0 : 2,            tip: "copy url" },
    ]
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "back":     if (win.current) win.current.goBack(); break;
            case "fwd":      if (win.current) win.current.goForward(); break;
            case "reload":
                if (!win.current) break;
                if (win.current.loading) win.current.stop(); else win.current.reload();
                break;
            case "newtab":   win.newTab(win.homeUrl); addr.selectAll(); addr.forceActiveFocus(); break;
            case "closetab": win.closeTab(win.currentTab); break;
            case "nexttab":  if (tabs.count > 1) win.currentTab = (win.currentTab + 1) % tabs.count; break;
            case "copyurl":  if (win.current) Clip.copy(win.current.url.toString()); break;
            }
        }
    }

    Component.onCompleted: {
        Titlebar.setButtons(tbButtons);
        newTab(startUrl !== "" ? normalize(startUrl) : homeUrl);
    }

    // Persistent profile (cookies/cache under the app's data dirs), shared by
    // every tab. Downloads land in ~/Downloads with their suggested name.
    WebEngineProfile {
        id: sharedProfile
        storageName: "surfer"
        offTheRecord: false
        onDownloadRequested: (download) => download.accept()
    }

    // ---- header: back-context address bar (filer's header look) ----
    Rectangle {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 30
        visible: win.visibility !== Window.FullScreen
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: 1

        Rectangle {
            id: addrBox
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 8; rightMargin: 8 }
            height: 22
            clip: true
            color: Theme.bg
            border.width: 1
            border.color: addr.activeFocus ? Theme.accent : Theme.border

            TextInput {
                id: addr
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; verticalCenterOffset: -1; leftMargin: 6; rightMargin: 6 }
                color: addr.activeFocus ? (win.active ? Theme.text : Theme.inactive)
                                        : (win.active ? Theme.textDim : Theme.inactive)
                font.family: Theme.font
                font.pixelSize: Theme.fontSize
                font.hintingPreference: Font.PreferFullHinting
                renderType: Text.NativeRendering
                antialiasing: false
                clip: true
                selectByMouse: true

                // mirror the live tab's url without a plain binding (typing
                // would break it) — same pattern as filer's path field
                property string bound: win.current ? win.current.url.toString() : ""
                onBoundChanged: if (!activeFocus) text = bound
                onActiveFocusChanged: if (activeFocus) selectAll()

                onAccepted: {
                    const u = win.normalize(text);
                    if (u !== "" && win.current) { win.current.url = u; win.current.forceActiveFocus(); }
                }
                Keys.onEscapePressed: { text = bound; if (win.current) win.current.forceActiveFocus(); }
            }
        }
    }

    // ---- tab strip ----
    Rectangle {
        id: tabstrip
        anchors { top: header.bottom; left: parent.left; right: parent.right }
        height: 22
        visible: win.visibility !== Window.FullScreen
        color: Theme.bg

        Row {
            anchors.fill: parent
            Repeater {
                model: tabs
                Rectangle {
                    required property int index
                    readonly property Item view: viewRep.count > index ? viewRep.itemAt(index) : null
                    readonly property bool active: win.currentTab === index
                    width: Math.min(180, (tabstrip.width - 24) / Math.max(1, tabs.count))
                    height: tabstrip.height
                    color: active ? Theme.highlight : Theme.bg
                    border.width: 1
                    border.color: active ? (win.active ? Theme.accent : Theme.inactive) : Theme.border

                    PixelText {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 6; rightMargin: 6 }
                        elide: Text.ElideRight
                        text: parent.view && parent.view.title !== "" ? parent.view.title : "…"
                        color: parent.active ? win.fgAccent : win.fgText
                    }
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                        onClicked: (e) => {
                            if (e.button === Qt.MiddleButton) win.closeTab(parent.index);
                            else win.currentTab = parent.index;
                        }
                    }
                }
            }

            // new-tab box at the end of the strip
            Rectangle {
                width: 24
                height: tabstrip.height
                color: plusMa.containsMouse ? Theme.bgAlt : Theme.bg
                border.width: 1
                border.color: plusMa.containsMouse ? win.fgAccent : Theme.border
                PixelText { anchors.centerIn: parent; text: "+"; color: win.fgText }
                MouseArea {
                    id: plusMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { win.newTab(win.homeUrl); addr.selectAll(); addr.forceActiveFocus(); }
                }
            }
        }
    }

    // ---- content: one WebEngineView per tab, only the current one visible ----
    Item {
        anchors { top: tabstrip.visible ? tabstrip.bottom : parent.top; left: parent.left; right: parent.right; bottom: parent.bottom }

        Repeater {
            id: viewRep
            model: tabs
            WebEngineView {
                required property int index
                required property string seed
                anchors.fill: parent
                visible: win.currentTab === index
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

import QtQuick
import QtQuick.Window

// player's window: album grid / album detail / playlists / now-playing views
// under a single header row, with the transport controls in the hyprvtb
// titlebar (buttons + PLAYBAR seek bar — the same bridge viewer uses for
// video). All state flows through the context properties main.py installs:
// Library (the Bridge), Player, the *Model list models, Prefs, Titlebar.
Window {
    id: win

    // "albums" | "detail" | "playlists" | "now"
    property string view: Prefs.get("view", "albums")
    property int detailAlbumId: 0
    property bool searching: false
    property string sortMode: Prefs.get("sort", "orig_year")
    property string scanStatus: ""
    property bool scanning: false

    readonly property bool act: win.active

    title: "player"
    width: 1080
    height: 720
    minimumWidth: 480
    minimumHeight: 320
    visible: true
    color: Theme.bg

    onClosing: Qt.quit()

    function fmtTime(s) {
        s = Math.max(0, Math.round(s));
        var m = Math.floor(s / 60);
        var r = s % 60;
        return m + ":" + (r < 10 ? "0" : "") + r;
    }

    function openAlbum(albumId) {
        detailAlbumId = albumId;
        Library.openAlbum(albumId);
        view = "detail";
    }

    function setView(v) {
        view = v;
        Prefs.set("view", v === "detail" ? "albums" : v);
    }

    function cycleSort() {
        var order = ["orig_year", "artist", "album"];
        sortMode = order[(order.indexOf(sortMode) + 1) % order.length];
        Library.setSort(sortMode);
        Prefs.set("sort", sortMode);
    }

    Component.onCompleted: Library.setSort(sortMode)

    Connections {
        target: Library
        function onScanStatus(text) { win.scanStatus = text; }
        function onScanRunning(on) { win.scanning = on; }
    }

    // ---- hyprvtb titlebar: transport ----
    readonly property var tbButtons: {
        const has = Player.queueLength > 0 ? 0 : 2;
        const loopLabel = Player.loop === 1 ? "1" : "o";
        return [
            { id: "prev",      label: "<<", state: has, tip: "previous" },
            { id: "playpause", label: Player.playing ? "||" : ">", state: has,
              tip: Player.playing ? "pause" : "play" },
            { id: "next",      label: ">>", state: has, tip: "next" },
            { id: "shuffle",   label: "*",  state: Player.shuffle ? 1 : 0, tip: "shuffle" },
            { id: "loop",      label: loopLabel, state: Player.loop > 0 ? 1 : 0,
              tip: Player.loop === 1 ? "repeat track" : (Player.loop === 2 ? "repeat all" : "repeat") },
            { id: "close",     label: "×",  state: 0, tip: "close" },
        ];
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    // Footer: track identity only — it changes per track, not per tick (a
    // fast-changing footer would re-raster the titlebar text stack).
    readonly property string footerStr: {
        var t = Player.current;
        return (t && t.title) ? ((t.artist ? t.artist + " — " : "") + t.title) : "";
    }
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    function pushPlaybar() {
        // Floor the fraction: hyprvtb builds ≤2.44 abort the compositor on a
        // zero-height fill rect (paused at 0:00), and a 0.2% fill is invisible.
        if (Player.duration > 0 && Player.index >= 0)
            Titlebar.setPlaybar(true, Math.max(0.002, Player.position / Player.duration));
        else
            Titlebar.setPlaybar(false, 0);
    }
    Timer {
        interval: 250; repeat: true
        running: Player.playing
        onTriggered: win.pushPlaybar()
    }
    Connections {
        target: Player
        function onCurrentChanged() { win.pushPlaybar(); }
        function onDurationChanged() { win.pushPlaybar(); }
    }
    Component.onDestruction: Titlebar.setPlaybar(false, 0)

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "prev":      Player.previous();                  break;
            case "playpause": Player.toggle();                    break;
            case "next":      Player.next();                      break;
            case "shuffle":   Player.setShuffle(!Player.shuffle); break;
            case "loop":      Player.cycleLoop();                 break;
            case "close":     Qt.quit();                          break;
            }
        }
        function onSeek(frac) { Player.seekFrac(frac); }
    }

    // ---- header row ----
    Rectangle {
        id: header
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 28
        color: Theme.bg
        border.width: 0

        Row {
            anchors.left: parent.left
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            HeaderButton {
                label: "[albums]"
                lit: win.view === "albums" || win.view === "detail"
                onClicked: win.setView("albums")
            }
            HeaderButton {
                label: "[playlists]"
                lit: win.view === "playlists"
                onClicked: win.setView("playlists")
            }
            HeaderButton {
                label: "[now playing]"
                lit: win.view === "now"
                onClicked: win.setView("now")
            }
            HeaderButton {
                visible: win.view === "albums" || win.view === "detail"
                label: "sort: " + (win.sortMode === "orig_year" ? "year"
                                   : win.sortMode === "artist" ? "artist" : "album")
                onClicked: win.cycleSort()
            }
            HeaderButton {
                visible: !win.scanning
                label: "rescan"
                onClicked: Library.rescan()
            }
            PixelText {
                text: win.scanStatus
                color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // Search field, right-aligned. Ctrl+F focuses; typing filters albums
        // live; Enter opens the full search overlay over everything.
        Rectangle {
            id: searchBox
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            width: 220
            height: 20
            color: Theme.bgAlt
            border.color: searchInput.activeFocus ? Theme.accent : Theme.border
            border.width: 1

            TextInput {
                id: searchInput
                anchors.fill: parent
                anchors.leftMargin: 5
                anchors.rightMargin: 5
                verticalAlignment: TextInput.AlignVCenter
                font.family: Theme.font
                font.pixelSize: Theme.fontSize
                font.hintingPreference: Font.PreferFullHinting
                renderType: Text.NativeRendering
                color: Theme.text
                clip: true
                onTextChanged: {
                    if (win.searching) Library.search(text);
                    else Library.setAlbumFilter(text);
                }
                onAccepted: {
                    if (text.length > 0) {
                        win.searching = true;
                        Library.search(text);
                    }
                }
                Keys.onEscapePressed: {
                    text = "";
                    win.searching = false;
                    Library.setAlbumFilter("");
                    focus = false;
                }
                PixelText {
                    visible: !parent.text && !parent.activeFocus
                    anchors.verticalCenter: parent.verticalCenter
                    text: "search (ctrl+f)"
                    color: Theme.dim
                }
            }
        }
    }

    Rectangle {  // hairline under the header
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 1
        color: Theme.border
    }

    // ---- content views ----
    Item {
        id: content
        anchors.top: header.bottom
        anchors.topMargin: 1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        AlbumGrid {
            anchors.fill: parent
            visible: win.view === "albums"
            onOpened: function(albumId) { win.openAlbum(albumId); }
        }
        AlbumDetail {
            anchors.fill: parent
            visible: win.view === "detail"
            albumId: win.detailAlbumId
            onBack: win.setView("albums")
        }
        PlaylistsView {
            anchors.fill: parent
            visible: win.view === "playlists"
        }
        NowPlaying {
            anchors.fill: parent
            visible: win.view === "now"
            onOpenAlbum: function(albumId) { win.openAlbum(albumId); }
        }
    }

    SearchOverlay {
        anchors.fill: parent
        anchors.topMargin: header.height + 1
        visible: win.searching
        query: searchInput.text
        onClosed: {
            win.searching = false;
            searchInput.text = "";
            Library.setAlbumFilter("");
        }
    }

    // ---- global keys ----
    Shortcut { sequence: "Ctrl+F"; onActivated: { searchInput.forceActiveFocus(); searchInput.selectAll(); } }
    Shortcut { sequence: "Space";  enabled: !searchInput.activeFocus; onActivated: Player.toggle() }
    Shortcut { sequence: "Ctrl+Right"; onActivated: Player.next() }
    Shortcut { sequence: "Ctrl+Left";  onActivated: Player.previous() }
    Shortcut {
        sequence: "Escape"
        enabled: !searchInput.activeFocus && !win.searching
        onActivated: if (win.view === "detail") win.setView("albums")
    }
}

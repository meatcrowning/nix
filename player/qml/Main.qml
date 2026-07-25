import QtQuick
import QtQuick.Window

// player's window: album gallery / playlists / now-playing views. There is no
// separate album page — clicking a cover opens an AlbumPanel section inline,
// under that cover's row in the gallery.
// ALL chrome lives in the hyprvtb titlebar (the same bridge viewer uses):
// transport (<< >/|| >> shuffle repeat), the view switcher (a/p/n), the sort
// cycler, a search toggle whose bar slides in from the titlebar edge, and a
// bottom-anchored rescan — no in-window header row. Window close is the outer
// titlebar's standard [x]. Everything flows through the context properties
// main.py installs: Library (the Bridge), Player, the *Model list models,
// Prefs, Titlebar.
Window {
    id: win

    // "albums" | "playlists" | "now"  ("detail" is a pre-inline-panel leftover
    // that may still sit in prefs — fold it back into the gallery)
    property string view: {
        var v = Prefs.get("view", "albums");
        return v === "detail" ? "albums" : v;
    }
    // The album whose inline section is open in the gallery (0 = none).
    property int openAlbumId: 0
    property bool searching: false          // full results overlay
    property bool searchOpen: false         // slide-out bar
    property string sortMode: Prefs.get("sort", "orig_year")
    property string scanStatus: ""
    property bool scanning: false

    readonly property bool act: win.active

    // The OUTER titlebar shows the window title — put the playing track there
    // ("artist — title") instead of a static app name; the inner column's
    // footer stays unused so the playbar gets the full lower run.
    title: footerStr !== "" ? footerStr : "player"
    width: 1080
    height: 720
    minimumWidth: 480
    minimumHeight: 320
    visible: true
    color: Theme.bg

    onClosing: Qt.quit()

    // View history for the mouse back/forward buttons (browser-style: going
    // somewhere new clears the forward stack).
    property var histBack: []
    property var histForward: []

    function _here() { return { view: view, albumId: openAlbumId }; }
    function _apply(s) {
        openAlbumId = s.albumId;   // the AlbumPanel loads that album's tracks itself
        view = s.view;
    }
    function goBack() {
        if (histBack.length === 0) return;
        histForward.push(_here());
        _apply(histBack.pop());
    }
    function goForward() {
        if (histForward.length === 0) return;
        histBack.push(_here());
        _apply(histForward.pop());
    }
    function _navigate(s) {
        histBack.push(_here());
        if (histBack.length > 50) histBack.shift();
        histForward = [];
        _apply(s);
    }

    // Open (or, with 0, close) an album's inline section in the gallery. Always
    // lands on the gallery, so it works from now-playing too.
    function openAlbum(albumId) {
        _navigate({ view: "albums", albumId: albumId });
    }

    function setView(v) {
        _navigate({ view: v, albumId: openAlbumId });
        Prefs.set("view", v);
    }

    function cycleSort() {
        var order = ["orig_year", "artist", "album"];
        sortMode = order[(order.indexOf(sortMode) + 1) % order.length];
        Library.setSort(sortMode);
        Prefs.set("sort", sortMode);
    }

    function openSearch() {
        searchOpen = true;
        searchInput.forceActiveFocus();
        searchInput.selectAll();
    }

    function closeSearch() {
        searchInput.text = "";
        searching = false;
        searchOpen = false;
        Library.setAlbumFilter("");
        searchInput.focus = false;
    }

    // Click-out: drop keyboard focus so Space is play/pause again; keep the
    // bar (and its filter) if a query is typed, retract it when empty.
    function unfocusSearch() {
        searchInput.focus = false;
        if (searchInput.text === "")
            closeSearch();
    }

    Component.onCompleted: Library.setSort(sortMode)

    Connections {
        target: Library
        function onScanStatus(text) { win.scanStatus = text; }
        function onScanRunning(on) { win.scanning = on; }
    }

    // ---- hyprvtb titlebar: transport + views + sort + search + rescan ----
    readonly property var tbButtons: {
        const has = Player.queueLength > 0 ? 0 : 2;
        const sortLabel = sortMode === "orig_year" ? "yr" : (sortMode === "artist" ? "ar" : "al");
        const sortTip = "sort: " + (sortMode === "orig_year" ? "year" : sortMode) + " (click to cycle)";
        return [
            { id: "prev",      label: "<<", state: has, tip: "previous" },
            { id: "playpause", label: Player.playing ? "||" : ">", state: has,
              tip: Player.playing ? "pause" : "play" },
            { id: "next",      label: ">>", state: has, tip: "next" },
            { id: "shuffle",   label: "*",  state: Player.shuffle ? 1 : 0, tip: "shuffle" },
            { id: "loop",      label: Player.loop === 1 ? "1" : "o", state: Player.loop > 0 ? 1 : 0,
              tip: Player.loop === 1 ? "repeat track" : (Player.loop === 2 ? "repeat all" : "repeat") },
            "-",
            { id: "albums",    label: "a", state: view === "albums" ? 1 : 0, tip: "albums" },
            { id: "playlists", label: "p", state: view === "playlists" ? 1 : 0, tip: "playlists" },
            { id: "now",       label: "n", state: view === "now" ? 1 : 0, tip: "now playing" },
            "-",
            { id: "sort",      label: sortLabel, state: 0, tip: sortTip },
            { id: "search",    label: "/", state: win.searchOpen ? 1 : 0, tip: "search" },
            { id: "rescan",    label: "rs", state: win.scanning ? 2 : 0, tip: "rescan library", bottom: true },
        ];
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    readonly property string footerStr: {
        var t = Player.current;
        return (t && t.title) ? ((t.artist ? t.artist + " — " : "") + t.title) : "";
    }

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
            case "albums":    win.setView("albums");              break;
            case "playlists": win.setView("playlists");           break;
            case "now":       win.setView("now");                 break;
            case "sort":      win.cycleSort();                    break;
            case "search":    win.searchOpen ? win.closeSearch() : win.openSearch(); break;
            case "rescan":    Library.rescan();                   break;
            }
        }
        function onSeek(frac) { Player.seekFrac(frac); }
    }

    // ---- content views (full window — chrome is all titlebar) ----
    Item {
        id: content
        anchors.fill: parent

        AlbumGrid {
            objectName: "albumGrid"
            anchors.fill: parent
            visible: win.view === "albums"
            filtered: searchInput.text !== ""
            expandedAlbumId: win.openAlbumId
            onOpened: function(albumId) { win.openAlbum(albumId); }
            onSearchArtist: function(artist) {
                win.openSearch();
                searchInput.text = artist;   // filters the grid to that artist
            }
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
        anchors.topMargin: 36   // clear the slide-out bar
        visible: win.searching
        z: 40
        query: searchInput.text
        onClosed: win.closeSearch()
    }

    // ---- search bar: slides in from the right (titlebar) edge ----
    Rectangle {
        id: searchBar
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.right: parent.right
        anchors.rightMargin: win.searchOpen ? 8 : -(width + 4)
        Behavior on anchors.rightMargin { NumberAnimation { duration: 120 } }
        width: 260
        height: 22
        z: 50
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
            Keys.onEscapePressed: win.closeSearch()
            PixelText {
                visible: !parent.text && !parent.activeFocus
                anchors.verticalCenter: parent.verticalCenter
                text: "search…"
                color: Theme.dim
            }
        }
    }

    // Mouse back/forward buttons navigate the view history. Only these two
    // buttons are accepted, so every other press passes to the views.
    MouseArea {
        anchors.fill: parent
        z: 90
        acceptedButtons: Qt.BackButton | Qt.ForwardButton
        onClicked: function(mouse) {
            if (mouse.button === Qt.BackButton) win.goBack();
            else win.goForward();
        }
    }

    // Click anywhere outside the search bar → unfocus it (Space becomes
    // play/pause again). Refusing the press (accepted = false) lets it fall
    // through to whatever was actually clicked.
    MouseArea {
        anchors.fill: parent
        z: 100
        visible: searchInput.activeFocus
        onPressed: function(mouse) {
            var p = mapToItem(searchBar, mouse.x, mouse.y);
            if (p.x < 0 || p.y < 0 || p.x > searchBar.width || p.y > searchBar.height)
                win.unfocusSearch();
            mouse.accepted = false;
        }
    }

    // Scan progress / drive status, unobtrusive in the bottom corner.
    PixelText {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 8
        z: 60
        visible: text !== ""
        text: win.scanStatus
        color: Theme.textDim
    }

    // ---- global keys ----
    Shortcut { sequence: "Ctrl+F"; onActivated: win.openSearch() }
    Shortcut { sequence: "Space";  enabled: !searchInput.activeFocus; onActivated: Player.toggle() }
    Shortcut { sequence: "Ctrl+Right"; onActivated: Player.next() }
    Shortcut { sequence: "Ctrl+Left";  onActivated: Player.previous() }
    Shortcut {
        sequence: "Escape"
        enabled: !searchInput.activeFocus
        onActivated: {
            if (win.searching || win.searchOpen) win.closeSearch();
            else if (win.openAlbumId > 0) win.openAlbum(0);   // close the inline section
        }
    }
}

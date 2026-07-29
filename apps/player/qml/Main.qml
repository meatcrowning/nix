import QtQuick
import QtQuick.Window
import "../../qmlcommon"

// player's window: album gallery / playlists / now-playing views. There is no
// separate album page — clicking a cover opens an AlbumPanel section inline,
// under that cover's row in the gallery.
// ALL chrome lives in the hyprvtb titlebar (the same bridge viewer uses):
// transport (<< >/|| >> shuffle repeat), the view switcher (a/p/n), the sort
// cycler, a search toggle whose bar slides in from the titlebar edge, and a
// bottom-anchored settings button whose drawer slides out from that edge
// (rescan + the gallery's column count) — no in-window header row. Window
// close is the outer titlebar's standard [x]. Everything flows through the context properties
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

    // ---- settings drawer (the bottom-anchored "st" titlebar button) ----
    property bool settingsOpen: false
    readonly property int minAlbumCols: 2
    readonly property int maxAlbumCols: 12
    property int albumCols: Math.max(minAlbumCols, Math.min(maxAlbumCols,
                                     Number(Prefs.get("albumCols", 7)) || 7))

    function setAlbumCols(n) {
        n = Math.max(minAlbumCols, Math.min(maxAlbumCols, Math.round(n)));
        if (n === albumCols)
            return;
        albumCols = n;            // the grid retiles off this binding, live
        Prefs.set("albumCols", n);
    }

    // Focus-aware foreground, in lock-step with the titlebar (filer's idiom,
    // docs/DESIGN.md §3.1.1). hyprvtb greys the titlebar's text and glyphs to
    // `Theme.inactive` the moment the window loses focus, so EVERY foreground
    // in the window goes the same way — otherwise the album grid, the queue and
    // the lyrics stay lit under a dead bar and the window reads as broken
    // rather than unfocused.
    //
    // Derived ONCE here and handed down as plain colours; no pane and no
    // delegate reads `win.active` or `Theme.text/textDim/accent` for itself.
    // That is a performance rule too: the track list draws one row per track and
    // the album grid one tile per album, so a focus change re-evaluates three
    // expressions per pane instead of one per delegate.
    //
    // Three tones only. `Theme.dim` (the tertiary tone: the ♫ art placeholder,
    // an unrated star, a play count) is already below the grey and would be
    // BRIGHTENED by it; `Theme.crit` (the favourite heart) is a status colour,
    // and filer's PreviewTile keeps its error tone lit unfocused for the same
    // reason. Backgrounds, `Theme.border` hairlines, `Theme.bgAlt` inset fills
    // and the `Theme.highlight` row fill do not move at all.
    readonly property color fgText:   win.active ? Theme.text    : Theme.inactive
    readonly property color fgDim:    win.active ? Theme.textDim : Theme.inactive
    readonly property color fgAccent: win.active ? Theme.accent  : Theme.inactive

    // The OUTER titlebar shows the window title — put the playing track there
    // ("artist — title") instead of a static app name. The inner column's
    // footer carries the position readout (see tbTime), below the scrub track.
    title: footerStr !== "" ? footerStr : "player"
    width: 1080
    height: 720
    // air's screen is a fraction of top's — let the window shrink well past
    // top's floor there (the layouts already flow; the now-playing cover has
    // its own air-side cap so it stays proportionate).
    minimumWidth: OnAir ? 320 : 480
    minimumHeight: OnAir ? 240 : 320
    visible: true
    color: Theme.bg

    onClosing: Qt.quit()

    // View history for the mouse back/forward buttons (browser-style: going
    // somewhere new clears the forward stack). player's reading of the
    // desktop-global rule in docs/DESIGN.md §11: "back" is the view you came from,
    // NOT the previous track — transport already owns prev/next, and stealing
    // the side buttons for it would leave the app with no way back out of an
    // album. The stack itself is qmlcommon/NavHistory.qml.
    NavHistory {
        id: navHist
        here: function () { return win._here(); }
        onNavigate: function (s) { win._apply(s); }
    }

    function _here() { return { view: view, albumId: openAlbumId }; }
    function _apply(s) {
        openAlbumId = s.albumId;   // the AlbumPanel loads that album's tracks itself
        view = s.view;
    }
    function goBack() { navHist.back(); }
    function goForward() { navHist.forward(); }
    function _navigate(s) {
        navHist.record();
        _apply(s);
    }

    // Open (or, with 0, close) an album's inline section in the gallery. Always
    // lands on the gallery, so it works from now-playing too.
    function openAlbum(albumId) {
        _navigate({ view: "albums", albumId: albumId });
    }

    // "show me this artist": land on the gallery with the search bar open and
    // carrying their name — the same state typing it would produce, so the
    // grid is filtered to that artist's albums and Escape clears it as usual.
    function browseArtist(artist) {
        if (view !== "albums")
            setView("albums");
        searching = false;          // results overlay off: this filters the grid
        openSearch();
        searchInput.text = artist;
        Library.setAlbumFilter(artist);   // explicit: an unchanged text won't fire
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

    Component.onCompleted: {
        Library.setSort(sortMode);
        // opt in to the footer sitting below the scrub track (hyprvtb >= 2.72);
        // older plugin builds just ignore the FOOTERPOS line.
        Titlebar.setFooterBottom(true);
        Titlebar.setFooter(win.tbTime);
    }

    Connections {
        target: Library
        function onScanStatus(text) { win.scanStatus = text; }
        function onScanRunning(on) { win.scanning = on; }
    }

    // ---- hyprvtb titlebar: transport + views + sort + search + settings ----
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
            { id: "settings",  label: "st", state: win.settingsOpen ? 1 : 0, tip: "settings", bottom: true },
        ];
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    readonly property string footerStr: {
        var t = Player.current;
        return (t && t.title) ? ((t.artist ? t.artist + " — " : "") + t.title) : "";
    }

    // ---- titlebar footer: the position readout, under the scrub track -------
    // Stacked one character per line by the plugin, so length is the whole cost
    // — "3:45/5:12" is 9 cells. Minutes are left unbounded rather than growing
    // an hours field, so an 80-minute mix reads "80:14" instead of "1:20:14"
    // and the column never gains two more rows. No spaces around the slash for
    // the same reason: a space still costs a full (blank) cell.
    function fmtTime(s) {
        s = Math.max(0, Math.round(s));
        return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
    }
    readonly property string tbTime: (Player.duration > 0 && Player.index >= 0)
        ? (fmtTime(Player.position) + "/" + fmtTime(Player.duration)) : ""
    // position fires far faster than the string changes; a QML property only
    // notifies on an actual change, so this pushes once per displayed second.
    onTbTimeChanged: Titlebar.setFooter(tbTime)

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
    Component.onDestruction: {
        Titlebar.setPlaybar(false, 0);
        Titlebar.setFooter("");
    }

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
            case "settings":  win.settingsOpen = !win.settingsOpen; break;
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
            cols: win.albumCols
            fgText: win.fgText
            fgDim: win.fgDim
            fgAccent: win.fgAccent
            onOpened: function(albumId) { win.openAlbum(albumId); }
            onSearchArtist: function(artist) { win.browseArtist(artist); }
        }
        PlaylistsView {
            anchors.fill: parent
            visible: win.view === "playlists"
            fgText: win.fgText
            fgDim: win.fgDim
            fgAccent: win.fgAccent
            onOpenAlbumRequested: function(albumId) { win.openAlbum(albumId); }
            onBrowseArtistRequested: function(artist) { win.browseArtist(artist); }
        }
        NowPlaying {
            anchors.fill: parent
            visible: win.view === "now"
            fgText: win.fgText
            fgDim: win.fgDim
            fgAccent: win.fgAccent
            onOpenAlbum: function(albumId) { win.openAlbum(albumId); }
            onBrowseArtist: function(artist) { win.browseArtist(artist); }
        }
    }

    SearchOverlay {
        anchors.fill: parent
        anchors.topMargin: 36   // clear the slide-out bar
        visible: win.searching
        z: 40
        query: searchInput.text
        fgText: win.fgText
        fgDim: win.fgDim
        fgAccent: win.fgAccent
        onClosed: win.closeSearch()
        // Leaving the results for an album means leaving the overlay too — it
        // covers the gallery the album section opens in. browseArtist already
        // drops `searching` itself (it re-uses the search bar as a filter).
        onOpenAlbumRequested: function(albumId) {
            win.closeSearch();
            win.openAlbum(albumId);
        }
        onBrowseArtistRequested: function(artist) { win.browseArtist(artist); }
    }

    // The desktop's motion, from the plugin's published key (qmlcommon/Motion.qml).
    Motion { id: motion }

    // ---- search bar: slides in from the right (titlebar) edge ----
    Rectangle {
        id: searchBar
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.right: parent.right
        anchors.rightMargin: win.searchOpen ? 8 : -(width + 4)
        // A reveal sliding out of the edge it belongs to, so it takes the
        // desktop's slide (docs/DESIGN.md §6.2). It was 120ms with NO easing at
        // all, i.e. Linear — nothing chose that, it was just the default.
        Behavior on anchors.rightMargin { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }
        width: 260
        height: 22
        z: 50
        color: Theme.bgAlt
        border.color: searchInput.activeFocus ? win.fgAccent : Theme.border
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
            color: win.fgText
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

    // ---- settings drawer, slid out by the bottom "st" titlebar button ----
    SettingsPanel {
        anchors.fill: parent
        z: 70
        open: win.settingsOpen
        columns: win.albumCols
        minColumns: win.minAlbumCols
        maxColumns: win.maxAlbumCols
        scanStatus: win.scanStatus
        scanning: win.scanning
        onCloseRequested: win.settingsOpen = false
        fgText: win.fgText
        fgDim: win.fgDim
        fgAccent: win.fgAccent
        onColumnsRequested: function(n) { win.setAlbumCols(n); }
        onRescanRequested: Library.rescan()
        onReplayGainRequested: function(mode) { Player.setReplayGain(mode); }
        onRgPreampRequested: function(db) { Player.setRgPreamp(db); }
    }

    // Mouse back/forward buttons navigate the view history (docs/DESIGN.md §11).
    NavButtons {
        onBack:    win.goBack()
        onForward: win.goForward()
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
        color: win.fgDim
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
            if (win.settingsOpen) win.settingsOpen = false;
            else if (win.searching || win.searchOpen) win.closeSearch();
            else if (win.openAlbumId > 0) win.openAlbum(0);   // close the inline section
        }
    }
}

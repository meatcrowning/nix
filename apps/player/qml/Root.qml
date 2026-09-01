import QtQuick
import QtQuick.Window
import "../../qmlcommon"

// player's CONTENT: album gallery / playlists / now-playing views. There is no
// separate album page — clicking a cover opens an AlbumPanel section inline,
// under that cover's row in the gallery.
//
// AN ITEM, NOT A WINDOW, because it has two roofs (apps/AGENTS.md → kdeshell):
// under Hyprland `Main.qml` is a plain `Window` around this, and in a Plasma
// session main.py puts this same item inside a real QMainWindow's QQuickWidget,
// so the window, its chrome and its background come from the KDE style. Nothing
// Window-only lives here — the title is published as `windowTitle` and the
// geometry request goes out as `requestResize`.
//
// Under Hyprland ALL chrome is the hyprvtb titlebar (the same bridge viewer
// uses): transport (<< >/|| >> shuffle repeat), the view switcher (a/p/n), the
// sort cycler, a search toggle whose bar slides in from the titlebar edge, and
// a bottom-anchored settings button whose drawer slides out from that edge
// (rescan + the gallery's column count) — no in-window header row. Under Plasma
// that same table becomes a menubar, a view toolbar, a transport toolbar along
// the bottom and a status bar, all real widgets built by `pylib/kdeshell.py`.
// Everything flows through the context properties main.py installs: Library
// (the Bridge), Player, the *Model list models, Prefs, Titlebar.
Item {
    id: win

    // Which roof this tree is under. Everything gated on it is chrome the
    // Plasma session owns as real widgets (kdeshell) and this QML must not draw
    // a second time; `DESK_SESSION=plasma|hypr` moves it for a harness.
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

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
    // §3.1.1's app-side fade is RETIRED — his board call, 2026-08-09: with
    // "dim unfocused" on, the native decoration:dim_inactive scrim is the ONE
    // dimming mechanism, and an app that also greys its own foreground reads
    // darker than a plain window. The window always renders its focused tones;
    // the compositor dims the whole surface. Re-arm by restoring `win.active`
    // here — the plumbing is all still wired.
    readonly property bool renderActive: true
    readonly property color fgText:   renderActive ? Theme.text    : Theme.inactive
    readonly property color fgDim:    renderActive ? Theme.textDim : Theme.inactive
    readonly property color fgAccent: renderActive ? Theme.accent  : Theme.inactive

    // ...and the ARTWORK rode the same fade — HIS call (2026-07-28): "dim it
    // with everything else, the window reads as one unfocused surface", over
    // the earlier reading (an image is content and stays lit); do not "fix" it
    // back. The call survives; the mechanism died with the retirement above:
    // `fgArt` is pinned to 1.0 and the native scrim dims the whole surface —
    // art included — like any other window.
    readonly property real fgArt: renderActive ? 1.0 : 0.55

    // The window title, published rather than set: under Hyprland `Main.qml`
    // binds it, and under Plasma `kdeshell.bind_title` puts it on the
    // QMainWindow. Either way it is the playing track ("artist — title")
    // instead of a static app name — the inner titlebar column's footer carries
    // the position readout (see tbTime), below the scrub track.
    readonly property string windowTitle: footerStr !== "" ? footerStr : "player"

    // ---- the Plasma status bar, and the Plasma finder ----------------------
    // Two properties the KDE status bar is driven from (`kdeshell.bind_status`):
    // what is HAPPENING on the left, a standing fact on the right — Dolphin's
    // shape. Under Hyprland nothing reads them and the scan line is drawn in
    // the window's bottom corner as it always was.
    readonly property string statusLine: win.scanStatus
    // No fraction to be honest about: the library scan reports a sentence, not
    // a count, so the bar stays hidden and the sentence goes in the line.
    readonly property real statusProgress: -1
    readonly property string statusRight: {
        if (Player.queueLength <= 0)
            return "";
        return (Player.index + 1) + " / " + Player.queueLength;
    }

    // The finder's text, out and in. The QML `searchInput` below stays the one
    // source of truth in both sessions; under Plasma main.py mirrors it onto a
    // real QLineEdit on the toolbar and back again.
    readonly property string searchText: searchInput.text
    function setSearchText(t) {
        if (searchInput.text !== t)
            searchInput.text = t;
    }
    function submitSearch() {
        if (searchInput.text.length > 0) {
            win.searching = true;
            Library.search(searchInput.text);
        }
    }
    // The View menu's "Find…" row under Plasma: there is no bar to slide out,
    // so main.py answers this id by focusing the toolbar's field instead.
    function focusSearch() { win.openSearch(); }

    // The window's own surface. Under Plasma this is `transparent` and the KDE
    // style's gradient (drawn by StyledBackground below) shows through; under
    // Hyprland it is `Theme.bg`, exactly as the Window's `color` was.
    Rectangle {
        anchors.fill: parent
        color: Theme.windowFill
        z: -2
    }
    // The KDE style's own window background, in the Plasma session only —
    // invisible and free under Hyprland (qmlcommon/StyledBackground.qml).
    StyledBackground { anchors.fill: parent; z: -1 }

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

    // ---- ONE TABLE, EVERY CHROME ------------------------------------------
    // Under Hyprland this is the hyprvtb titlebar's button column. Under Plasma
    // `pylib/kdeshell.py` builds a real menubar, a view toolbar, a transport
    // toolbar along the bottom and their shortcuts out of the SAME array — so
    // the two faces are driven by one set of ids and one `state`, and cannot
    // drift. Everything past `id/label/state/tip/bottom` is inert on the vtb
    // wire (`vtbclient.py` reads only those), so annotating it costs the
    // titlebar nothing:
    //
    //   menu:      which menu this verb belongs to
    //   menuSep:   a divider above it, in the menu only
    //   menuText:  the menu's wording where the tooltip is not the verb
    //   icon:      a freedesktop icon name — a two-character cell is a titlebar
    //              affordance and has no place on a real toolbar
    //   bar:       true for the top toolbar, "transport" for the bottom one
    //   group:     a radio set (the three views are one)
    //   shortcut:  THIS FACE'S key. The QML `Shortcut`s below stand down under
    //              Plasma — two owners of one sequence in one window is an
    //              ambiguous shortcut, which Qt answers by firing NEITHER.
    readonly property var tbButtons: {
        const has = Player.queueLength > 0 ? 0 : 2;
        const cur = Player.current;
        // The favourite toggle follows the now-playing track exactly like the
        // header heart (NowPlaying.qml): lit while the current track is
        // favourited, dim while it is not, disabled when nothing is playing.
        // It lives here because this is the row shuffle/repeat live in — the
        // titlebar renders it in the transport's own on/off look, since it
        // has no per-button colour and its pixel font has no heart glyph.
        const favState = (cur && cur.id !== undefined) ? (cur.favorite ? 1 : 0) : 2;
        const sortLabel = sortMode === "orig_year" ? "yr" : (sortMode === "artist" ? "ar" : "al");
        const sortWord = sortMode === "orig_year" ? "year" : sortMode;
        const sortTip = "sort: " + sortWord + " (click to cycle)";
        return [
            { id: "prev",      label: "<<", state: has, tip: "previous", menu: "playback",
              menuText: "Previous Track", icon: "media-skip-backward",
              bar: "transport", shortcut: "Ctrl+Left" },
            { id: "playpause", label: Player.playing ? "||" : ">", state: has,
              tip: Player.playing ? "pause" : "play", menu: "playback",
              menuText: Player.playing ? "Pause" : "Play",
              icon: Player.playing ? "media-playback-pause" : "media-playback-start",
              bar: "transport", shortcut: "Space" },
            { id: "next",      label: ">>", state: has, tip: "next", menu: "playback",
              menuText: "Next Track", icon: "media-skip-forward",
              bar: "transport", shortcut: "Ctrl+Right" },
            // shuffle sits RIGHT of repeat now; this slot is where it used to be.
            { id: "favorite",  label: "♥",  state: favState, tip: "favourite",
              menu: "playback", menuSep: true, menuText: "Favourite",
              icon: "favorites", bar: "transport", shortcut: "L" },
            // The MODE is in the icon, not only in the lit state: off and
            // repeat-all differ by the check, repeat-track by the glyph
            // (breeze/oxygen both carry the -song face). One dim icon for all
            // three modes said nothing about which one a click had reached.
            { id: "loop",      label: Player.loop === 1 ? "1" : "o", state: Player.loop > 0 ? 1 : 0,
              tip: Player.loop === 1 ? "repeat track" : (Player.loop === 2 ? "repeat all" : "repeat"),
              menu: "playback",
              menuText: Player.loop === 1 ? "Repeat Track" : (Player.loop === 2 ? "Repeat All" : "Repeat"),
              icon: Player.loop === 1 ? "media-playlist-repeat-song" : "media-playlist-repeat",
              bar: "transport" },
            { id: "shuffle",   label: "*",  state: Player.shuffle ? 1 : 0, tip: "shuffle",
              menu: "playback", menuText: "Shuffle", icon: "media-playlist-shuffle",
              bar: "transport" },
            "-",
            // The three pages are a RADIO SET on the real toolbar: one of them
            // is always the page you are on, and two independent checkboxes
            // could claim otherwise (§3.5, §5.4).
            { id: "albums",    label: "a", state: view === "albums" ? 1 : 0, tip: "albums",
              menu: "view", menuText: "Albums", icon: "view-list-icons",
              bar: true, group: "view" },
            { id: "playlists", label: "p", state: view === "playlists" ? 1 : 0, tip: "playlists",
              menu: "view", menuText: "Playlists", icon: "view-media-playlist",
              bar: true, group: "view" },
            { id: "now",       label: "n", state: view === "now" ? 1 : 0, tip: "now playing",
              menu: "view", menuText: "Now Playing", icon: "view-media-visualization",
              bar: true, group: "view" },
            "-",
            // The full word, not the titlebar's two-character cell — a toolbar
            // has the room a titlebar cell never did (§7.6, and `barText` puts
            // the name beside the icon for this one row).
            { id: "sort",      label: sortLabel, state: 0, tip: sortTip,
              menu: "view", menuText: "Sort by " + sortWord,
              icon: "view-sort-ascending", bar: true, barText: "sort: " + sortWord },
            // Under Plasma this row does NOT go on the toolbar: the finder is a
            // real QLineEdit at its right-hand end, where Dolphin and Gwenview
            // keep theirs (kdeshell.toolbar_search). The menu row focuses it.
            { id: "search",    label: "fs", state: win.searchOpen ? 1 : 0, tip: "find (Ctrl+F)",
              menu: "view", menuText: "Find…", icon: "edit-find", shortcut: "@Find" },
            // ...and this one opens the drawer under Hyprland and the real
            // "Configure player…" dialog under Plasma — a difference in the
            // SHELL, answered by `kdeshell.on_action`, not by a branch here.
            { id: "settings",  label: "st", state: win.settingsOpen ? 1 : 0, tip: "settings",
              bottom: true, menu: "settings", menuText: "Configure player…",
              icon: "configure" },
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

    // ONE handler, TWO chromes: the hyprvtb titlebar column clicks it, and in a
    // Plasma session `menuBar` does (qmlcommon/DeskMenuBar.qml). Same ids.
    function tbAction(id) {
        switch (id) {
        case "prev":      Player.previous();                  break;
        case "playpause": Player.toggle();                    break;
        case "next":      Player.next();                      break;
        case "shuffle":   Player.setShuffle(!Player.shuffle); break;
        case "loop":      Player.cycleLoop();                 break;
        case "favorite":  if (Player.current && Player.current.id !== undefined)
                            Library.setFavorite(Player.current.id, !Player.current.favorite);
                          break;
        case "albums":    win.setView("albums");              break;
        case "playlists": win.setView("playlists");           break;
        case "now":       win.setView("now");                 break;
        case "sort":      win.cycleSort();                    break;
        case "search":    win.searchOpen ? win.closeSearch() : win.openSearch(); break;
        case "settings":  win.settingsOpen = !win.settingsOpen; break;
        }
    }

    Connections {
        target: Titlebar
        function onClicked(id) { win.tbAction(id); }
        function onSeek(frac) { Player.seekFrac(frac); }
    }

    // The menubar the Plasma session USED to get in place of the titlebar
    // column. player's Plasma face is a real QMainWindow with a real QMenuBar,
    // a view toolbar, a transport toolbar and a status bar now
    // (`pylib/kdeshell.py`), so this stands down in BOTH sessions — `systemBar`
    // — and is kept only for its 0-height contribution to the layout below and
    // for the harness that still drives it.
    DeskMenuBar {
        id: menuBar
        systemBar: true
        anchors { top: parent.top; left: parent.left; right: parent.right }
        buttons: win.tbButtons
        menuOrder: ["playback", "view", "settings"]
        onTriggered: (id) => win.tbAction(id)
    }

    // ---- content views (the rest of the window) ----
    Item {
        id: content
        anchors { top: menuBar.bottom; left: parent.left
                  right: parent.right; bottom: parent.bottom }

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
            fgArt: win.fgArt
            onOpened: function(albumId) { win.openAlbum(albumId); }
            onSearchArtist: function(artist) { win.browseArtist(artist); }
        }
        PlaylistsView {
            id: playlists
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
            fgArt: win.fgArt
            onOpenAlbum: function(albumId) { win.openAlbum(albumId); }
            onBrowseArtist: function(artist) { win.browseArtist(artist); }
        }
    }

    SearchOverlay {
        anchors.fill: parent
        // clear the Hyprland slide-out search bar. Under Plasma there is
        // nothing to clear here — the finder is a real QLineEdit on the window's
        // toolbar, outside this QML entirely.
        anchors.topMargin: menuBar.height + (win.plasma ? 8 : 36)
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

    // ---- search bar: slides in from the right (titlebar) edge under Hyprland.
    //
    // THE FIELD IS STILL THE WINDOW'S ONE SOURCE OF SEARCH TRUTH in both
    // sessions, but under Plasma nobody looks at it: the finder there is a real
    // QLineEdit at the right-hand end of the toolbar (`kdeshell.toolbar_search`,
    // where Dolphin and Gwenview keep theirs), and main.py keeps the two in step
    // — `searchText` out, `setSearchText()` in. So this box is simply invisible
    // there, and every rule below it (filter vs full search, Escape, the
    // click-out unfocus) goes on being decided in exactly one place.
    Rectangle {
        id: searchBar
        visible: !win.plasma
        anchors.top: menuBar.bottom
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
        radius: Theme.rounding

        border.color: searchInput.activeFocus ? win.fgAccent : Theme.border
        border.width: Theme.ctrlBorder

        TextInput {
            id: searchInput
            anchors.fill: parent
            anchors.leftMargin: 5
            anchors.rightMargin: 5
            verticalAlignment: TextInput.AlignVCenter
            font: Theme.editorFontAt(Screen.devicePixelRatio)   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
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
                text: "search..."
                color: Theme.dim
            }
        }
    }

    // ---- settings drawer, slid out by the bottom "st" titlebar button ----
    // Hyprland only: under Plasma the same `SettingsPage.qml` is the content of
    // a real "Configure player…" dialog, opened by `kdeshell.on_action`.
    SettingsPanel {
        visible: !win.plasma && open
        anchors { top: menuBar.bottom; left: parent.left
                  right: parent.right; bottom: parent.bottom }
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

    // Scan progress / drive status, unobtrusive in the bottom corner. (systheme
    // creation used to share this line; it is a toast with a progress bar now —
    // SysthemeToast below.)
    PixelText {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 8
        z: 60
        // Under Plasma this sentence is the status bar's (see `statusLine`);
        // drawing it here too would say it twice.
        visible: text !== "" && !win.plasma
        text: win.scanStatus
        color: win.fgDim
    }

    // systheme creation reports itself as a toast + progress bar, bottom-right.
    SysthemeToast {
        fgText: win.fgText
        fgDim: win.fgDim
    }

    // ---- global keys ----
    // EVERY ONE OF THESE STANDS DOWN UNDER PLASMA. There the same sequences are
    // on the QActions the shell builds from `tbButtons` (`shortcut:`), and two
    // owners of one sequence in one window is an ambiguous shortcut — which Qt
    // answers by firing NEITHER, so the key would simply stop working. The
    // shell also suspends the bare-key ones while its toolbar finder has the
    // keyboard (`kdeshell.guard_typing`), which is what the
    // `!searchInput.activeFocus` guards do here.
    //
    // Ctrl+F is the desktop's find key (docs/DESIGN.md §11.2). The titlebar cell
    // used to be labelled "/", which advertised a key that was never bound.
    Shortcut {
        sequence: "Ctrl+F"
        enabled: !win.plasma && !playlists.modal
        onActivated: win.openSearch()
    }
    // A Shortcut is matched before the key reaches the focused item, so any
    // modal carrying a text field has to stand Space down explicitly or its
    // name box can never contain one.
    Shortcut {
        sequence: "Space"
        enabled: !win.plasma && !searchInput.activeFocus && !playlists.modal
        onActivated: Player.toggle()
    }
    Shortcut { sequence: "Ctrl+Right"; enabled: !win.plasma; onActivated: Player.next() }
    Shortcut { sequence: "Ctrl+Left";  enabled: !win.plasma; onActivated: Player.previous() }
    // Like the current track — the same Library.setFavorite write every heart
    // and the context menu call, so all surfaces flip together. Gated off the
    // search field so typing an 'L' into a query never toggles a favourite.
    Shortcut {
        sequence: "L"
        enabled: !win.plasma && !searchInput.activeFocus && !playlists.modal
        onActivated: if (Player.current && Player.current.id !== undefined)
                         Library.setFavorite(Player.current.id, !Player.current.favorite)
    }
    // Escape keeps BOTH roofs: it closes a modal, a drawer or a search, and no
    // QAction claims it, so there is nothing here for it to be ambiguous with.
    Shortcut {
        sequence: "Escape"
        enabled: !searchInput.activeFocus
        onActivated: {
            if (playlists.modal) playlists.closeModal();
            else if (win.settingsOpen) win.settingsOpen = false;
            else if (win.searching || win.searchOpen) win.closeSearch();
            else if (win.openAlbumId > 0) win.openAlbum(0);   // close the inline section
        }
    }
}

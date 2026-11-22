import QtQuick
import QtQuick.Window
import QtQuick.Controls
import "../../qmlcommon"

// booru's content: the search row, the thumbnail grid, and the post view that
// replaces the grid when a thumbnail is opened.
//
// AN ITEM, NOT A WINDOW: under Hyprland Main.qml wraps it and the compositor
// draws the titlebar; under Plasma main.py puts it in a kdeshell QMainWindow
// whose menubar and toolbar are built from `actions` (apps/AGENTS.md).
Item {
    id: root
    NativeContentContext {}

    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

    Rectangle { anchors.fill: parent; color: Theme.windowFill; z: -2 }
    StyledBackground { anchors.fill: parent; z: -1 }

    readonly property color fg: plasma ? Theme.windowText : Theme.text
    readonly property color fgDim: plasma ? Theme.disabledText : Theme.textDim
    readonly property int pad: 6

    // ---- state --------------------------------------------------------------
    property string site: {
        var s = startSite !== "" ? startSite : String(Settings.get("site", "danbooru"));
        return siteInfo(s) ? s : "danbooru";
    }
    property string query: startQuery !== "" ? startQuery : String(Settings.get("query", ""))
    property string rating: String(Settings.get("rating", ""))
    property string order: String(Settings.get("order", ""))
    property var blacklist: Settings.get("blacklist", [])
    property bool muted: Settings.get("muted", true) !== false
    property int thumbSize: Math.max(120, Math.min(400, Number(Settings.get("thumbSize", 200)) || 200))

    property int gen: 0
    property var posts: []
    property int hidden: 0
    property int total: -1
    property int pageLoaded: 0
    property bool lastPage: false
    property string error: ""
    property bool searched: false
    property int pendingPost: -1      // a post to reopen once history's search reloads

    property int postIndex: -1
    readonly property var post: postIndex >= 0 && postIndex < posts.length ? posts[postIndex] : null
    property bool showOriginal: false
    property string mediaFile: ""
    property string mediaError: ""

    property string wikiTag: ""
    property string wikiTitle: ""
    property string wikiText: ""
    property var wikiLinks: []
    property var relatedTags: []

    property string toastText: ""
    property color toastColor: Theme.info

    readonly property var sitesList: Booru.sites
    function siteInfo(id) {
        for (var i = 0; i < Booru.sites.length; i++)
            if (Booru.sites[i].id === id) return Booru.sites[i];
        return null;
    }
    readonly property var siteCaps: { var s = siteInfo(site); return s ? s.caps : []; }
    function can(cap) { return siteCaps.indexOf(cap) >= 0; }

    readonly property string windowTitle: {
        var t = query !== "" ? query : "booru";
        if (post) t = post.site + " #" + post.id + " - " + t;
        return t + " - Booru";
    }
    readonly property string statusLine: {
        if (error !== "") return error;
        if (Booru.busy) return pageLoaded === 0 ? "searching" : "loading page " + (pageLoaded + 1);
        if (!searched) return "";
        if (posts.length === 0) return "no posts";
        return "";
    }
    readonly property real statusProgress: -1
    readonly property string statusRight: {
        if (!searched) return "";
        var s = posts.length + (total >= 0 ? " of " + total : "") + " posts";
        if (hidden > 0) s += ", " + hidden + " blacklisted";
        if (post) s = (postIndex + 1) + " / " + s;
        return s;
    }

    // ---- actions: one table for the menubar, toolbar and titlebar --------------
    readonly property bool hasPost: post !== null
    readonly property var actions: [
        { id: "save", menu: "file", menuText: "Save Original", icon: "document-save",
          shortcut: "Ctrl+S", bar: true, state: hasPost ? 0 : 2,
          tip: "save to ~/Pictures/booru" },
        { id: "viewer", menu: "file", menuText: "Open in Viewer", icon: "document-open",
          shortcut: "Ctrl+O", bar: true, state: hasPost ? 0 : 2 },
        { id: "page", menu: "file", menuText: "Open Post Page", icon: "internet-web-browser",
          shortcut: "Ctrl+Shift+O", state: hasPost ? 0 : 2 },
        { id: "copy-tags", menu: "edit", menuText: "Copy Tags", icon: "edit-copy",
          shortcut: "Ctrl+Shift+C", bar: true, state: hasPost ? 0 : 2,
          tip: "copy the post's tags as a prompt" },
        { id: "copy-link", menu: "edit", menuText: "Copy Post Link", icon: "edit-copy",
          state: hasPost ? 0 : 2 },
        { id: "find", menu: "edit", menuText: "Search", icon: "edit-find", shortcut: "Ctrl+F" },
        { id: "back", menu: "view", menuText: "Back", icon: "go-previous", shortcut: "Alt+Left",
          bar: true, state: (nav.canBack || hasPost) ? 0 : 2 },
        { id: "forward", menu: "view", menuText: "Forward", icon: "go-next", shortcut: "Alt+Right",
          state: nav.canForward ? 0 : 2 },
        "-",
        { id: "prev", menu: "view", menuText: "Previous Post", icon: "go-up", shortcut: "PgUp",
          bar: true, state: hasPost && postIndex > 0 ? 0 : 2 },
        { id: "next", menu: "view", menuText: "Next Post", icon: "go-down", shortcut: "PgDown",
          bar: true, state: hasPost && (postIndex < posts.length - 1 || !lastPage) ? 0 : 2 },
        { id: "original", menu: "view", menuText: "Show Original", checkable: true,
          state: !hasPost ? 2 : (showOriginal ? 1 : 0) },
        { id: "refresh", menu: "view", menuText: "Refresh", icon: "view-refresh", shortcut: "F5" },
        { id: "bigger", menu: "view", menuText: "Larger Thumbnails", icon: "zoom-in", shortcut: "Ctrl++" },
        { id: "smaller", menu: "view", menuText: "Smaller Thumbnails", icon: "zoom-out", shortcut: "Ctrl+-" },
        { id: "mute", menu: "settings", menuText: "Mute Video", checkable: true, state: muted ? 1 : 0 },
        { id: "blacklist", menu: "settings", menuText: "Edit Blacklist...", icon: "view-filter" }
    ]
    readonly property var menuOrder: ["edit", "view"]

    readonly property var tbButtons: [
        { id: "back", label: "bk", state: (nav.canBack || hasPost) ? 0 : 2, tip: "back" },
        { id: "prev", label: "pv", state: hasPost && postIndex > 0 ? 0 : 2, tip: "previous post" },
        { id: "next", label: "nx", state: hasPost ? 0 : 2, tip: "next post" },
        { id: "save", label: "sv", state: hasPost ? 0 : 2, tip: "save original" },
        { id: "viewer", label: "vw", state: hasPost ? 0 : 2, tip: "open in viewer" },
        { id: "copy-tags", label: "cp", state: hasPost ? 0 : 2, tip: "copy tags" },
        { id: "blacklist", label: "bl", state: blacklistBox.open ? 1 : 0, tip: "blacklist" }
    ]
    onTbButtonsChanged: if (!plasma) Titlebar.setButtons(tbButtons)

    function tbAction(id) {
        switch (id) {
        case "save": if (post) Booru.save(post); break;
        case "viewer": if (post) Booru.openViewer(post); break;
        case "page": if (post) Qt.openUrlExternally(post.page); break;
        case "copy-tags": if (post) Booru.copyText(promptFor("")); break;
        case "copy-link": if (post) Booru.copyText(post.page); break;
        case "find": queryField.forceActiveFocus(); queryField.selectAll(); break;
        case "back": goBack(); break;
        case "forward": nav.forward(); break;
        case "prev": step(-1); break;
        case "next": step(1); break;
        case "original": showOriginal = !showOriginal; loadMedia(); break;
        case "refresh": runSearch(true); break;
        case "bigger": setThumb(thumbSize + 40); break;
        case "smaller": setThumb(thumbSize - 40); break;
        case "mute": muted = !muted; Settings.set("muted", muted); break;
        case "blacklist":
            blacklistBox.open = !blacklistBox.open;
            if (blacklistBox.open) { blacklistField.text = blacklist.join(" "); blacklistField.forceActiveFocus(); }
            break;
        }
    }

    function setThumb(px) {
        thumbSize = Math.max(120, Math.min(400, px));
        Settings.set("thumbSize", thumbSize);
    }

    // ---- history: a search, or a post in it -----------------------------------
    NavHistory {
        id: nav
        here: function () { return { site: root.site, query: root.query, rating: root.rating,
                                     order: root.order, post: root.postIndex }; }
        onNavigate: function (s) {
            var same = s.site === root.site && s.query === root.query
                       && s.rating === root.rating && s.order === root.order;
            root.site = s.site; root.query = s.query; root.rating = s.rating; root.order = s.order;
            if (!same) { root.postIndex = -1; root.runSearch(true); root.pendingPost = s.post; }
            else if (s.post >= 0 && s.post < root.posts.length) root.openPost(s.post, true);
            else root.closePost(true);
        }
    }
    NavButtons { onBack: root.goBack(); onForward: nav.forward() }

    function goBack() {
        if (nav.canBack) return nav.back();
        if (post) { closePost(); return true; }
        return false;
    }

    // ---- searching -----------------------------------------------------------
    // A new search from the UI: remember where we were FIRST, then change it.
    function go(changes) {
        if (searched) nav.record();
        for (var k in changes) root[k] = changes[k];
        runSearch(true);
    }
    function runSearch(fromHistory) {
        if (fromHistory !== true && searched) nav.record();
        Settings.set("site", site);
        Settings.set("query", query);
        Settings.set("rating", rating);
        Settings.set("order", order);
        queryField.text = query;
        tags.close();
        posts = [];
        hidden = 0;
        total = -1;
        pageLoaded = 0;
        lastPage = false;
        error = "";
        searched = true;
        postIndex = -1;
        pendingPost = -1;
        grid.positionViewAtBeginning();
        gen = Booru.search(site, query, rating, order);
    }
    function more() { if (!lastPage && error === "") Booru.more(); }

    function blacklisted(p) {
        for (var i = 0; i < blacklist.length; i++)
            if (p.tags.indexOf(blacklist[i]) >= 0) return true;
        return false;
    }

    Connections {
        target: Booru
        function onPostsReady(g, list, tot, page, last) {
            if (g !== root.gen) return;
            var keep = [], drop = 0;
            var seen = {};
            for (var i = 0; i < root.posts.length; i++) seen[root.posts[i].id] = true;
            for (var j = 0; j < list.length; j++) {
                if (seen[list[j].id]) continue;
                if (root.blacklisted(list[j])) { drop++; continue; }
                keep.push(list[j]);
            }
            root.posts = root.posts.concat(keep);
            root.hidden += drop;
            if (tot >= 0) root.total = tot;
            root.pageLoaded = page;
            root.lastPage = last;
            if (root.pendingPost >= 0 && root.pendingPost < root.posts.length) {
                root.openPost(root.pendingPost, true);
                root.pendingPost = -1;
            }
            // A page that was all blacklisted or all repeats fills nothing:
            // ask for the next one rather than leave the grid short.
            if (!last && (keep.length === 0 || grid.contentHeight <= grid.height))
                Qt.callLater(root.more);
        }
        function onFailed(g, msg) { if (g === root.gen) root.error = msg; }
        function onWikiReady(tag, title, text, links) {
            if (tag !== root.wikiTag) return;
            root.wikiTitle = title; root.wikiText = text; root.wikiLinks = links;
        }
        function onRelatedReady(tag, list) { if (tag === root.wikiTag) root.relatedTags = list; }
        function onMediaReady(url, file) { if (root.post && url === root.mediaUrl()) root.mediaFile = file; }
        function onMediaFailed(url, msg) { if (root.post && url === root.mediaUrl()) root.mediaError = msg; }
        function onToast(msg, kind) { root.showToast(msg, kind); }
    }

    function searchTag(tag, add) {
        var q = tag;
        if (add) {
            var toks = query.split(/\s+/).filter(function (t) { return t !== "" && t !== tag; });
            toks.push(tag);
            q = toks.join(" ");
        }
        go({ query: q });
    }

    // ---- the post view -----------------------------------------------------------
    function openPost(i, fromHistory) {
        if (i < 0 || i >= posts.length) return;
        if (fromHistory !== true) nav.record();
        postIndex = i;
        showOriginal = false;
        loadMedia();
        var p = posts[i];
        var focus = p.groups.character.length ? p.groups.character[0]
                  : p.groups.copyright.length ? p.groups.copyright[0]
                  : p.groups.artist.length ? p.groups.artist[0] : "";
        if (focus !== "" && can("wiki")) showWiki(focus);
        else { wikiTag = ""; wikiText = ""; wikiTitle = ""; wikiLinks = []; relatedTags = []; }
        if (i >= posts.length - 4) more();
    }
    function closePost(fromHistory) {
        if (postIndex < 0) return;
        if (fromHistory !== true) nav.record();
        var i = postIndex;
        postIndex = -1;
        mediaFile = "";
        grid.positionViewAtIndex(i, GridView.Contain);
        grid.forceActiveFocus();
    }
    function step(d) {
        if (!post) return;
        var i = postIndex + d;
        if (i < 0) return;
        if (i >= posts.length) { more(); return; }
        // Stepping replaces the post rather than stacking history: Back from
        // a post goes to the grid, not through every post walked past.
        postIndex = i;
        showOriginal = false;
        loadMedia();
        if (i >= posts.length - 4) more();
    }
    function mediaUrl() {
        if (!post) return "";
        return showOriginal && post.kind === "image" ? post.original : post.view;
    }
    function loadMedia() {
        mediaFile = "";
        mediaError = "";
        if (post && post.kind !== "image") Booru.media(post.view);
    }
    function img(url) { return url ? "image://booru/" + encodeURIComponent(url) : ""; }

    function showWiki(tag) {
        wikiTag = tag; wikiTitle = ""; wikiText = ""; wikiLinks = []; relatedTags = [];
        if (can("wiki")) Booru.wiki(site, tag);
        if (can("related")) Booru.related(site, tag, "");
        if (!can("wiki")) wikiTitle = tag;
    }

    function promptFor(group) {
        if (!post) return "";
        var g = post.groups;
        var list = group !== "" ? g[group]
                 : g.character.concat(g.copyright, g.artist, g.general);
        return Booru.promptText(list);
    }

    function showToast(msg, kind) {
        toastText = msg;
        toastColor = kind === "ok" ? Theme.ok : kind === "crit" ? Theme.crit
                   : kind === "warn" ? Theme.warn : Theme.info;
        toastTimer.restart();
    }
    Timer { id: toastTimer; interval: 3200; onTriggered: root.toastText = "" }

    function tagMenu(tag, item, x, y) {
        var p = item.mapToItem(root, x, y);
        var rows = [
            { label: "search " + tag, trigger: function () { root.searchTag(tag, false) } },
            { label: "add to search", trigger: function () { root.searchTag(tag, true) } },
            { label: "exclude from search", trigger: function () { root.searchTag("-" + tag, true) } },
            { separator: true },
            { label: "wiki and related", enabled: root.can("wiki") || root.can("related"),
              trigger: function () { root.showWiki(tag) } },
            { label: "copy tag", trigger: function () { Booru.copyText(tag) } },
            { separator: true },
            { label: root.blacklist.indexOf(tag) >= 0 ? "remove from blacklist" : "blacklist tag",
              trigger: function () { root.toggleBlacklist(tag) } }
        ];
        menu.open(p.x, p.y, rows);
    }
    function toggleBlacklist(tag) {
        var b = blacklist.slice();
        var i = b.indexOf(tag);
        if (i >= 0) b.splice(i, 1); else b.push(tag);
        setBlacklist(b);
    }
    function setBlacklist(b) {
        blacklist = b;
        Settings.set("blacklist", b);
        showToast(b.length + " blacklisted tags", "info");
    }

    Component.onCompleted: {
        if (!plasma) Titlebar.setButtons(tbButtons);
        Booru.prepareTags();
        queryField.text = query;
        if (query !== "" || startQuery !== "") runSearch(true);
        queryField.forceActiveFocus();
    }

    Keys.onEscapePressed: goBack()

    // ---- search row ----------------------------------------------------------------
    Item {
        id: searchRow
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: root.pad }
        height: queryField.implicitHeight

        ComboBox {
            id: siteBox
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            width: Math.max(110, implicitWidth)
            model: root.sitesList
            textRole: "label"
            valueRole: "id"
            // Computed here, not indexOfValue(): that runs before a Python
            // list model is populated and is never re-evaluated.
            currentIndex: {
                for (var i = 0; i < root.sitesList.length; i++)
                    if (root.sitesList[i].id === root.site) return i;
                return 0;
            }
            onActivated: { if (root.query !== "" || root.searched) root.go({ site: currentValue }); else root.site = currentValue }
        }
        TextField {
            id: queryField
            anchors { left: siteBox.right; leftMargin: root.pad; right: ratingBox.left
                      rightMargin: root.pad; verticalCenter: parent.verticalCenter }
            placeholderText: "tags"
            selectByMouse: true
            persistentSelection: true
            font: Theme.editorFontForScale(Screen.devicePixelRatio)
            inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText

            property int wordStart: 0
            property bool dismissed: false
            function word() {
                var t = text, c = cursorPosition, s = c;
                while (s > 0 && t[s - 1] !== " ") s--;
                wordStart = s;
                return t.substring(s, c);
            }
            function offer() {
                var w = word();
                if (w === "" || dismissed) { tags.close(); return; }
                var have = text.split(/\s+/);
                var list = Booru.complete(w, 8).map(function (e) {
                    return { tag: e.tag, category: e.category, posts: e.posts, alias: e.alias,
                             have: have.indexOf(e.insert) >= 0,
                             trigger: function () { queryField.take(e.insert) } };
                });
                var r = positionToRectangle(wordStart);
                var p = mapToItem(root, r.x, r.y);
                tags.open(p.x, p.y, list, r.height);
            }
            function take(ins) {
                var end = cursorPosition;
                while (end < text.length && text[end] !== " ") end++;
                var t = text.substring(0, wordStart) + ins + " " + text.substring(end).replace(/^ +/, "");
                text = t;
                cursorPosition = wordStart + ins.length + 1;
            }
            onTextEdited: {
                var w = word();
                if (w === "" || text[cursorPosition - 1] === " ") dismissed = false;
                offer();
            }
            onActiveFocusChanged: if (!activeFocus) tags.close()
            onAccepted: root.go({ query: text.trim() })
            Keys.onPressed: (e) => {
                if (!tags.visible) return;
                if (e.key === Qt.Key_Down) { tags.move(1); e.accepted = true }
                else if (e.key === Qt.Key_Up) { tags.move(-1); e.accepted = true }
                else if (e.key === Qt.Key_Tab) { tags.accept(); e.accepted = true }
                else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                         && !(e.modifiers & Qt.ControlModifier)) { tags.accept(); e.accepted = true }
                else if (e.key === Qt.Key_Escape) { tags.close(); dismissed = true; e.accepted = true }
            }
        }
        ComboBox {
            id: ratingBox
            anchors { right: orderBox.left; rightMargin: root.pad; verticalCenter: parent.verticalCenter }
            width: Math.max(120, implicitWidth)
            model: [ { id: "", label: "any rating" }, { id: "g", label: "general" },
                     { id: "s", label: "sensitive" }, { id: "q", label: "questionable" },
                     { id: "e", label: "explicit" } ]
            textRole: "label"
            valueRole: "id"
            currentIndex: Math.max(0, indexOfValue(root.rating))
            onActivated: { if (root.searched) root.go({ rating: currentValue }); else root.rating = currentValue }
        }
        ComboBox {
            id: orderBox
            anchors { right: goButton.left; rightMargin: root.pad; verticalCenter: parent.verticalCenter }
            width: Math.max(110, implicitWidth)
            model: [ { id: "", label: "newest" }, { id: "score", label: "score" },
                     { id: "favcount", label: "favourites" }, { id: "rank", label: "hot" } ]
            textRole: "label"
            valueRole: "id"
            currentIndex: Math.max(0, indexOfValue(root.order))
            onActivated: { if (root.searched) root.go({ order: currentValue }); else root.order = currentValue }
        }
        Button {
            id: goButton
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            text: "Search"
            onClicked: root.go({ query: queryField.text.trim() })
        }
    }

    // ---- blacklist editor, inline under the search row (no modal) --------------------
    Item {
        id: blacklistBox
        property bool open: false
        anchors { left: parent.left; right: parent.right; top: searchRow.bottom; topMargin: open ? root.pad : 0 }
        height: open ? blacklistField.implicitHeight : 0
        visible: open
        PixelText {
            id: blLabel
            anchors { left: parent.left; leftMargin: root.pad; verticalCenter: parent.verticalCenter }
            text: "hide posts tagged"
            color: root.fgDim
        }
        TextField {
            id: blacklistField
            anchors { left: blLabel.right; leftMargin: root.pad; right: parent.right
                      rightMargin: root.pad; verticalCenter: parent.verticalCenter }
            placeholderText: "tags, space separated"
            font: Theme.editorFontForScale(Screen.devicePixelRatio)
            onAccepted: {
                root.setBlacklist(text.split(/\s+/).filter(function (t) { return t !== "" }));
                blacklistBox.open = false;
                if (root.searched) root.runSearch(true);
            }
            Keys.onEscapePressed: blacklistBox.open = false
        }
    }

    Item {
        id: body
        anchors { left: parent.left; right: parent.right; top: blacklistBox.bottom
                  topMargin: root.pad; bottom: parent.bottom }

        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 1
            color: Theme.border
        }

        // ---- the grid --------------------------------------------------------------
        KineticGridView {
            id: grid
            visible: root.postIndex < 0
            anchors { fill: parent; topMargin: 1 }
            clip: true
            focus: root.postIndex < 0
            readonly property int cols: Math.max(1, Math.floor((width - gridBar.barW) / root.thumbSize))
            cellWidth: Math.floor((width - gridBar.barW) / cols)
            cellHeight: cellWidth
            model: root.posts
            ScrollBar.vertical: VScroll { id: gridBar }
            onContentYChanged: if (contentHeight - contentY - height < cellHeight * 2) root.more()
            keyNavigationEnabled: true
            Keys.onReturnPressed: root.openPost(currentIndex)
            Keys.onEnterPressed: root.openPost(currentIndex)
            highlightFollowsCurrentItem: false

            delegate: Item {
                id: cell
                required property var modelData
                required property int index
                width: grid.cellWidth
                height: grid.cellHeight
                Rectangle {
                    anchors { fill: parent; margins: 2 }
                    color: cellMouse.containsMouse || grid.currentIndex === cell.index && grid.activeFocus
                           ? Theme.highlight : "transparent"
                    border.width: grid.currentIndex === cell.index && grid.activeFocus ? Theme.ctrlBorder : 0
                    border.color: Theme.focusColor
                }
                Image {
                    id: thumb
                    anchors { fill: parent; margins: 6 }
                    source: root.img(cell.modelData.preview)
                    sourceSize.width: width * Screen.devicePixelRatio
                    sourceSize.height: height * Screen.devicePixelRatio
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: true
                    smooth: true
                    mipmap: true
                }
                PixelText {
                    anchors.centerIn: parent
                    visible: thumb.status === Image.Error
                    text: "no preview"
                    color: root.fgDim
                }
                Rectangle {
                    visible: cell.modelData.kind !== "image"
                    anchors { right: thumb.right; bottom: thumb.bottom }
                    width: badge.implicitWidth + 8
                    height: badge.implicitHeight + 2
                    color: Theme.bgAlt
                    border { width: Theme.ctrlBorder; color: Theme.border }
                    PixelText {
                        id: badge
                        anchors.centerIn: parent
                        text: cell.modelData.kind
                        color: Theme.textDim
                    }
                }
                MouseArea {
                    id: cellMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: (m) => {
                        grid.currentIndex = cell.index;
                        if (m.button === Qt.RightButton) {
                            var p = cell.mapToItem(root, m.x, m.y);
                            var pd = cell.modelData;
                            menu.open(p.x, p.y, [
                                { label: "open", trigger: function () { root.openPost(cell.index) } },
                                { label: "save original", trigger: function () { Booru.save(pd) } },
                                { label: "open in viewer", trigger: function () { Booru.openViewer(pd) } },
                                { label: "open post page", trigger: function () { Qt.openUrlExternally(pd.page) } },
                                { label: "copy post link", trigger: function () { Booru.copyText(pd.page) } }
                            ]);
                        } else {
                            root.openPost(cell.index);
                        }
                    }
                }
            }

            Column {
                anchors.centerIn: parent
                visible: grid.count === 0
                spacing: 8
                PixelText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.error !== "" ? root.error
                          : Booru.busy ? "searching"
                          : root.searched ? "no posts" : "type tags and press return"
                    color: root.error !== "" ? Theme.crit : root.fgDim
                    width: Math.min(implicitWidth, grid.width - 40)
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        // ---- the post ---------------------------------------------------------------
        Item {
            id: postView
            visible: root.post !== null
            anchors.fill: parent
            focus: root.post !== null
            Keys.onLeftPressed: root.step(-1)
            Keys.onRightPressed: root.step(1)
            Keys.onEscapePressed: root.goBack()

            readonly property int sideW: Math.round(Math.min(Math.max(260, width * 0.3), 420))

            Item {
                id: stage
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom; right: side.left }
                clip: true

                Image {
                    id: still
                    anchors { fill: parent; margins: root.pad }
                    visible: root.post !== null && root.post.kind === "image"
                    source: visible ? root.img(root.mediaUrl()) : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: false
                    smooth: true
                    mipmap: true
                    // Under the full-size one while it loads: the thumbnail,
                    // so the post appears at once and sharpens in place.
                    Image {
                        anchors.fill: parent
                        z: -1
                        visible: still.status !== Image.Ready && root.post !== null
                        source: root.post ? root.img(root.post.preview) : ""
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        smooth: true
                    }
                }
                AnimatedImage {
                    anchors { fill: parent; margins: root.pad }
                    visible: root.post !== null && root.post.kind === "gif" && root.mediaFile !== ""
                    source: visible ? root.mediaFile : ""
                    fillMode: Image.PreserveAspectFit
                    playing: visible
                }
                Loader {
                    anchors { fill: parent; margins: root.pad }
                    active: root.post !== null && root.post.kind === "video" && root.mediaFile !== ""
                    source: "VideoPane.qml"
                    onLoaded: { item.source = Qt.binding(function () { return root.mediaFile }); item.muted = Qt.binding(function () { return root.muted }) }
                }
                PixelText {
                    anchors.centerIn: parent
                    visible: root.post !== null && (still.status === Image.Error || root.mediaError !== ""
                             || (root.post.kind !== "image" && root.mediaFile === ""))
                    text: root.mediaError !== "" ? root.mediaError
                          : still.status === Image.Error ? "could not load the image"
                          : "loading " + (root.post ? root.post.kind : "")
                    color: root.mediaError !== "" || still.status === Image.Error ? Theme.crit : root.fgDim
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.RightButton
                    onClicked: (m) => {
                        var p = mapToItem(root, m.x, m.y);
                        menu.open(p.x, p.y, [
                            { label: "save original", trigger: function () { root.tbAction("save") } },
                            { label: "open in viewer", trigger: function () { root.tbAction("viewer") } },
                            { label: "open post page", trigger: function () { root.tbAction("page") } },
                            { label: root.showOriginal ? "show sample" : "show original",
                              enabled: root.post !== null && root.post.kind === "image",
                              trigger: function () { root.tbAction("original") } },
                            { separator: true },
                            { label: "copy tags", trigger: function () { root.tbAction("copy-tags") } },
                            { label: "copy post link", trigger: function () { root.tbAction("copy-link") } }
                        ]);
                    }
                }
            }

            Rectangle {
                id: side
                anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                width: postView.sideW
                color: "transparent"
                Rectangle {
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                    width: 1
                    color: Theme.border
                }

                KineticFlickable {
                    id: sideFlick
                    anchors { fill: parent; leftMargin: 1 }
                    clip: true
                    contentWidth: width
                    contentHeight: sideCol.implicitHeight + 2 * root.pad
                    ScrollBar.vertical: VScroll { id: sideBar }

                    Column {
                        id: sideCol
                        x: root.pad
                        y: root.pad
                        width: sideFlick.width - 2 * root.pad - sideBar.barW
                        spacing: 6

                        PixelText {
                            width: parent.width
                            wrapMode: Text.Wrap
                            text: root.post ? ("#" + root.post.id + "  " + root.post.width + "x" + root.post.height
                                               + "  " + root.post.ext + "  " + root.post.rating
                                               + "  score " + root.post.score) : ""
                            color: root.fg
                        }
                        PixelText {
                            width: parent.width
                            visible: root.post !== null && root.post.source !== ""
                            elide: Text.ElideMiddle
                            text: root.post ? "source  " + root.post.source : ""
                            color: Theme.link
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: if (/^https?:\/\//.test(root.post.source)) Qt.openUrlExternally(root.post.source)
                            }
                        }

                        Repeater {
                            model: ["artist", "copyright", "character", "general", "meta"]
                            delegate: Column {
                                id: grp
                                required property string modelData
                                readonly property var list: root.post ? root.post.groups[modelData] : []
                                visible: list.length > 0
                                width: sideCol.width
                                spacing: 3
                                Item {
                                    width: parent.width
                                    height: grpLabel.implicitHeight + 4
                                    PixelText {
                                        id: grpLabel
                                        anchors.bottom: parent.bottom
                                        text: grp.modelData + "  " + grp.list.length
                                        font.bold: Theme.plasmaPalette
                                        color: root.fgDim
                                    }
                                    PixelText {
                                        anchors { right: parent.right; bottom: parent.bottom }
                                        text: "copy"
                                        color: Theme.link
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: Booru.copyText(root.promptFor(grp.modelData))
                                        }
                                    }
                                }
                                Flow {
                                    width: parent.width
                                    spacing: 3
                                    Repeater {
                                        model: grp.list
                                        delegate: TagChip { tag: modelData; required property string modelData }
                                    }
                                }
                            }
                        }

                        // wiki + related for the chosen tag
                        Column {
                            width: sideCol.width
                            visible: root.wikiTag !== ""
                            spacing: 4
                            Rectangle { width: parent.width; height: 1; color: Theme.border }
                            PixelText {
                                width: parent.width
                                text: (root.wikiTitle !== "" ? root.wikiTitle : root.wikiTag).replace(/_/g, " ")
                                font.bold: true
                                color: root.fg
                                elide: Text.ElideRight
                            }
                            PixelText {
                                width: parent.width
                                visible: text !== ""
                                text: root.wikiTitle === "" && root.can("wiki") ? "loading wiki"
                                      : root.wikiText !== "" ? root.wikiText
                                      : root.can("wiki") ? "no wiki page" : ""
                                wrapMode: Text.Wrap
                                maximumLineCount: wikiMore.expanded ? 400 : 12
                                elide: Text.ElideRight
                                color: root.fgDim
                            }
                            PixelText {
                                id: wikiMore
                                property bool expanded: false
                                visible: root.wikiText.length > 600
                                text: expanded ? "less" : "more"
                                color: Theme.link
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                            onClicked: wikiMore.expanded = !wikiMore.expanded }
                            }
                            PixelText {
                                visible: root.wikiLinks.length > 0
                                text: "links"
                                color: root.fgDim
                            }
                            Flow {
                                width: parent.width
                                spacing: 3
                                Repeater {
                                    model: root.wikiLinks.slice(0, 40)
                                    delegate: TagChip { tag: modelData; required property string modelData }
                                }
                            }
                            PixelText {
                                visible: root.relatedTags.length > 0
                                text: "related"
                                color: root.fgDim
                            }
                            Flow {
                                width: parent.width
                                spacing: 3
                                Repeater {
                                    model: root.relatedTags
                                    delegate: TagChip { tag: modelData.tag; required property var modelData }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Click: search it.  Middle or Ctrl+click: add it to the search.
    // Right-click: everything else.
    component TagChip: Rectangle {
        id: chip
        property string tag
        readonly property bool inQuery: root.query.split(/\s+/).indexOf(tag) >= 0
        width: chipText.implicitWidth + 10
        height: chipText.implicitHeight + 4
        radius: Theme.rounding
        color: chipMouse.containsMouse ? Theme.highlight : Theme.buttonBg
        border { width: Theme.ctrlBorder; color: inQuery ? Theme.focusColor : Theme.border }
        PixelText {
            id: chipText
            anchors.centerIn: parent
            text: chip.tag.replace(/_/g, " ")
            color: root.blacklist.indexOf(chip.tag) >= 0 ? Theme.inactive : Theme.buttonText
        }
        MouseArea {
            id: chipMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
            onClicked: (m) => {
                if (m.button === Qt.RightButton) root.tagMenu(chip.tag, chip, m.x, m.y);
                else root.searchTag(chip.tag, m.button === Qt.MiddleButton
                                               || (m.modifiers & Qt.ControlModifier));
            }
        }
        ToolTip.visible: chipMouse.containsMouse && info.posts !== undefined
        ToolTip.delay: 600
        readonly property var info: chipMouse.containsMouse ? Booru.tagInfo(tag) : ({})
        ToolTip.text: info.posts !== undefined ? info.category + ", " + info.posts + " posts" : ""
    }

    // ---- overlays --------------------------------------------------------------
    TagPopup { id: tags; anchors.fill: parent }
    CtxMenu { id: menu; anchors.fill: parent }

    Rectangle {
        visible: root.toastText !== ""
        z: 2800
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 12 }
        width: toastLabel.implicitWidth + 24
        height: toastLabel.implicitHeight + 10
        color: Theme.bgAlt
        radius: Theme.rounding
        border { color: root.toastColor; width: Theme.ctrlBorder }
        PixelText {
            id: toastLabel
            anchors.centerIn: parent
            text: root.toastText
            color: root.toastColor
        }
    }
}

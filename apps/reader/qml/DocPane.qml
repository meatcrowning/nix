import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// ONE document, and everything that belongs to a document rather than to the
// window: which file is open, where it is scrolled to, its own back/forward
// history, its own search cursor and its own drop target. `Main.qml` puts one
// or two of these side by side, exactly the way filer puts two BrowserPanes —
// the chrome reads the FOCUSED pane and nothing else.
Item {
    id: pane

    property string path: ""
    property real cellW: 8
    property bool focused: true
    property bool winActive: true
    property string query: ""

    // The document's foreground, faded with the window (docs/DESIGN.md §3.1.1).
    // Body text IS the accent (§3.1) and hyprvtb greys the titlebar to
    // `Theme.inactive` the moment the window loses focus — so the text under it
    // has to go the same way, or the one thing the user is actually reading is
    // the one thing still lit.
    //
    // Computed ONCE per pane and handed down. The Block delegate propagates it
    // into RichText, which already gives every word a single `color: root.color`
    // binding — so this costs no new binding per word, and a focus change
    // re-evaluates three expressions rather than one per segment of prose.
    readonly property color fg:       winActive ? Theme.text    : Theme.inactive
    readonly property color fgDim:    winActive ? Theme.textDim : Theme.inactive
    readonly property color fgAccent: winActive ? Theme.accent  : Theme.inactive

    // ---- the loaded document ----
    property var doc: ({})
    readonly property var blocks: doc.blocks || []
    readonly property var outline: doc.outline || []
    readonly property string docName: doc.name || ""
    readonly property bool ok: doc.ok === true
    // What the pane says when it cannot draw a document. §10.2: an app that
    // cannot do its job says so instead of opening broken.
    readonly property string problem: path === "" ? "no document"
                                    : (doc.error || "")

    // ---- search, within this document ----
    property var matches: []          // block indices, in document order
    property int matchAt: -1

    // The heading the top of the viewport is inside — what the outline
    // highlights, so the outline is a position readout and not just a list.
    property int topIndex: 0
    readonly property int section: {
        var s = -1;
        for (var i = 0; i < outline.length; i++)
            if (outline[i].index <= topIndex) s = i; else break;
        return s;
    }

    signal opened(string p)                       // the pane now shows this file
    signal statusChanged(string msg)              // one line for the footer
    signal contextRequested(real x, real y, int blockIndex)
    signal focusClaimed()


    // ---- opening ----
    // `where` is "" (top), "#anchor", or a block index as a number. Every entry
    // point funnels through here so history, the watch and the persisted scroll
    // position can never disagree about what is open.
    function load(p, where) {
        var target = String(p || "");
        var frag = "";
        var h = target.indexOf("#");
        if (h >= 0) { frag = target.slice(h + 1); target = target.slice(0, h); }
        if (target === "") { pane.doc = {}; pane.path = ""; return; }
        pane.doc = Docs.load(target);
        pane.path = pane.doc.path || target;
        pane.matches = [];
        pane.matchAt = -1;
        Docs.watch(pane.watchKey, pane.path);
        pane.opened(pane.path);
        if (frag !== "") jumpAnchor(frag);
        else if (typeof where === "number") jumpIndex(where);
        else if (where && String(where).charAt(0) === "#") jumpAnchor(String(where).slice(1));
        else jumpIndex(0);
        if (pane.query !== "") refreshMatches();
    }
    property string watchKey: "left"

    // The user went somewhere new: record where they were first, so the side
    // buttons walk back through it (qmlcommon/NavHistory, docs/DESIGN.md §11.1).
    function navigate(p, where) {
        if (p === pane.path && (where === undefined || where === "")) return;
        if (pane.path !== "") hist.record();
        load(p, where);
    }

    function goBack() { return hist.back(); }
    function goForward() { return hist.forward(); }
    // Bound, not queried: NavHistory reassigns its stacks rather than mutating
    // them, so these notify and a titlebar cell can grey itself honestly.
    readonly property bool canBack: hist.canBack
    readonly property bool canForward: hist.canForward

    NavHistory {
        id: hist
        here: function () { return { path: pane.path, index: pane.topIndex }; }
        onNavigate: function (s) {
            if (!s) return;
            if (s.path !== pane.path) load(s.path, s.index);
            else jumpIndex(s.index);
        }
    }

    // ---- moving about ----
    function jumpIndex(i) {
        var n = Math.max(0, Math.min(blocks.length - 1, i || 0));
        view.positionViewAtIndex(n, ListView.Beginning);
        pane.topIndex = n;
        // ...and again once the delegates around it have been built. A block's
        // height is only known after it has wrapped, so a jump made in the same
        // pass as the load lands on an estimate; the second call is what makes
        // a restored scroll position and an anchor link actually arrive.
        Qt.callLater(function () {
            view.positionViewAtIndex(n, ListView.Beginning);
            pane.topIndex = n;
        });
    }
    function jumpAnchor(a) {
        var want = String(a).toLowerCase();
        for (var i = 0; i < outline.length; i++)
            if (outline[i].anchor === want) { jumpIndex(outline[i].index); return true; }
        // An anchor that resolves to nothing is not silently swallowed: the
        // footer says so (§10 — never report a change that did not happen).
        pane.statusChanged("no section '" + want + "' in " + pane.docName);
        return false;
    }
    // Opening a cross-document search RESULT. Those carry a line number, and
    // blocks do not — so rather than guess at a mapping, the pane opens the
    // file and lands on its first match of the query that found it. The
    // highlight is what actually shows the hit either way.
    function openAtMatch(p) {
        navigate(p);
        refreshMatches();
        if (matches.length) { matchAt = 0; jumpIndex(matches[0]); }
    }

    // The file changed on disk. Reload IN PLACE, keeping the scroll position —
    // a maintenance mechanism must not be visible (docs/DESIGN.md §6.1), and an
    // editor saving over the file the user is reading is exactly that case.
    function reload() {
        if (pane.path === "") return;
        var at = pane.topIndex;
        pane.doc = Docs.load(pane.path);
        if (pane.query !== "") refreshMatches();
        jumpIndex(at);
    }

    // ---- search inside this document ----
    function refreshMatches() {
        var q = pane.query.toLowerCase(), out = [];
        if (q.length > 1)
            for (var i = 0; i < blocks.length; i++)
                if (String(blocks[i].text || "").toLowerCase().indexOf(q) >= 0)
                    out.push(i);
        pane.matches = out;
        if (out.length === 0) pane.matchAt = -1;
        else if (pane.matchAt < 0 || pane.matchAt >= out.length) pane.matchAt = 0;
    }
    function stepMatch(dir) {
        if (matches.length === 0) return;
        matchAt = ((matchAt + dir) % matches.length + matches.length) % matches.length;
        jumpIndex(matches[matchAt]);
    }
    onQueryChanged: refreshMatches()

    // ---- links ----
    function follow(href, lt) {
        if (lt === "anchor") { hist.record(); jumpAnchor(href); return; }
        if (lt === "doc") { navigate(href); return; }
        if (!Docs.openExternal(href))
            pane.statusChanged("could not open " + href);
    }

    // ---- the view ----
    KineticListView {
        id: view
        anchors.fill: parent
        anchors.margins: 10        // the house content inset (docs/DESIGN.md §4.1)
        clip: true
        model: pane.blocks
        cacheBuffer: 2000
        ScrollBar.vertical: VScroll { id: vscroll }   // qmlcommon/, docs/DESIGN.md 9.2

        // Which block the top of the viewport is in. Read from the view rather
        // than counted, so it stays right through a reflow.
        onContentYChanged: {
            var i = view.indexAt(4, view.contentY + 4);
            if (i >= 0) pane.topIndex = i;
        }

        delegate: Block {
            required property var modelData
            required property int index
            // Reserve the scrollbar's OWN width, never a literal: it is a
            // desktop-wide setting now (docs/DESIGN.md 9.2) and ranges 11-16px,
            // so the 10 this used to be left the last characters of every line
            // under an opaque win31 bar.
            width: view.width - vscroll.barW
            block: modelData
            cellW: pane.cellW
            query: pane.query
            current: pane.matchAt >= 0 && pane.matches[pane.matchAt] === index
            fg: pane.fg
            fgDim: pane.fgDim
            fgAccent: pane.fgAccent
            // A blank line between blocks — the one the source has — and two
            // before a heading. Consecutive list items are ROWS and get none
            // (§2.1: zero inter-row gap).
            topGap: index === 0 ? 0
                  : modelData.type === "h" ? Theme.fontSize * 2
                  : (modelData.type === "li"
                     && pane.blocks[index - 1].type === "li") ? 0
                  : Theme.fontSize
            onLinkActivated: (href, lt) => pane.follow(href, lt)
            onLinkHovered: (href) => pane.statusChanged(href)
        }
    }

    // The empty / broken state. It is a sentence, not a blank pane.
    PixelText {
        anchors.centerIn: parent
        visible: !pane.ok
        color: pane.fgDim
        text: pane.problem === "no document"
                ? "no document - open one from the files pane, or drop a .md file here"
                : (pane.docName + ": " + pane.problem)
    }

    // A right-click anywhere in the pane offers what a reader of this kind of
    // app expects (§7.1 — a new view ships with a context menu). The menu
    // itself lives in Main.qml so it can overlay both panes.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        propagateComposedEvents: true
        onPressed: (m) => {
            pane.focusClaimed();
            if (m.button === Qt.RightButton) {
                var p = mapToItem(null, m.x, m.y);
                pane.contextRequested(p.x, p.y,
                                      view.indexAt(4, view.contentY + m.y - 10));
            }
            m.accepted = false;      // the links underneath still get their click
        }
    }

    // Drop a `.md` file (out of filer, or anything offering local file URLs)
    // onto a pane to read it there. `Docs.docPaths` decodes the uri-list in
    // PYTHON with QUrl — never encodeURI/decodeURI in QML, which leaves `#` and
    // `?` mangled (docs/DESIGN.md §13).
    DropArea {
        id: dz
        anchors.fill: parent
        property bool takes: false
        onEntered: (d) => {
            dz.takes = Docs.docPaths(d.urls).length > 0;
            if (!dz.takes) d.accepted = false;      // decline, never a silent no-op
        }
        onExited: dz.takes = false
        onDropped: (d) => {
            var got = Docs.docPaths(d.urls);
            dz.takes = false;
            if (!got.length) { d.accepted = false; return; }
            d.acceptProposedAction();
            pane.focusClaimed();
            pane.navigate(got[0]);
        }
    }
    Rectangle {
        anchors.fill: parent
        visible: dz.containsDrag && dz.takes
        color: "transparent"
        border.width: 2
        border.color: Theme.accent
        z: 20
    }

}

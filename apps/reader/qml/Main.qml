import QtQuick
import QtQuick.Window
import "../../qmlcommon"

// reader's window: a browse pane, one or two document panes, and a search bar —
// with every control in the hyprvtb titlebar, because an app does not draw its
// own chrome strip (docs/DESIGN.md §12, §7.4).
//
// The shape is filer's, deliberately and not by coincidence: `DocPane.qml` is
// the whole reader the way `BrowserPane.qml` is the whole browser, `|` splits
// right and `_` splits down as toggles, `win.pane` is the FOCUSED pane and the
// chrome reads nothing else. Split earns its place here for the reason it earns
// it there — this repo's documents refer to each other constantly, and reading
// `docs/DESIGN.md` beside the `AGENTS.md` it governs is the whole point.
Window {
    id: win

    property string startDoc: startPath

    // Focus-aware foreground, in lock-step with the titlebar (filer's idiom,
    // docs/DESIGN.md §3.1.1). Every foreground in this window goes through one
    // of these three; the document panes derive their own from `winActive` for
    // the same reason.
    // §3.1.1's app-side fade is RETIRED — his board call, 2026-08-09: with
    // "dim unfocused" on, the native decoration:dim_inactive scrim is the ONE
    // dimming mechanism, and an app that also greys its own foreground reads
    // darker than a plain window. The window always renders its focused tones;
    // the compositor dims the whole surface. Re-arm by restoring `win.active`
    // here — the plumbing is all still wired.
    readonly property bool renderActive: true
    readonly property color fgAccent: renderActive ? Theme.accent  : Theme.inactive
    readonly property color fgText:   renderActive ? Theme.text    : Theme.inactive
    readonly property color fgDim:    renderActive ? Theme.textDim : Theme.inactive

    // The pixel font is monospace, so ONE measurement gives every layout in the
    // app its column: the advance. Measured against the real font rather than
    // computed from §2.7's `round(0.533 * fontSize)`, so it stays right if the
    // Settings font FAMILY is changed to another monospace face.
    TextMetrics {
        id: metrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real cellW: metrics.width > 0 ? metrics.width / 10
                                                    : Math.round(0.533 * Theme.fontSize)

    Motion { id: motion }

    // ---- the browse pane ----
    property bool sideOpen: true
    property string sideMode: "outline"        // files | outline | results
    property real sideWidth: 260
    readonly property real minSide: 24 * cellW
    readonly property real sideShown: sideOpen ? Math.max(minSide, Math.min(width * 0.6, sideWidth)) : 0

    function setSide(mode) {
        // Each button is a TOGGLE and the pair re-modes in place — filer's two
        // split buttons, the same gesture: asking for the mode you are already
        // showing closes the pane, asking for the other switches to it.
        if (sideOpen && sideMode === mode) { sideOpen = false; }
        else { sideMode = mode; sideOpen = true; }
        Settings.set("sideOpen", sideOpen);
        Settings.set("sideMode", sideMode);
    }

    // ---- split ----
    property bool splitOn: false
    property bool splitVertical: true
    property real splitRatio: 0.5
    property int focusPane: 0
    readonly property int splitterW: 4
    // A pane narrower than this cannot hold a readable line; the minimum along
    // Y only has to keep a few rows on screen.
    readonly property int minPaneW: 40 * cellW
    readonly property int minPaneH: 6 * Theme.fontSize
    readonly property real splitSpan: splitVertical ? docArea.width : docArea.height
    readonly property real minPane: splitVertical ? minPaneW : minPaneH
    readonly property real paneLeadSize: splitOn
        ? Math.max(minPane, Math.min(splitSpan - splitterW - minPane,
                                     Math.round((splitSpan - splitterW) * splitRatio)))
        : splitSpan
    readonly property real paneTrailPos: paneLeadSize + splitterW
    // Never zero: reader feeds the vtb socket and hyprvtb's renderRect aborts
    // the compositor on a zero-size box (docs/DESIGN.md §12).
    readonly property real paneTrailSize: Math.max(1, splitSpan - paneTrailPos)

    readonly property Item pane: (splitOn && focusPane === 1 && paneRLoader.item)
                                 ? paneRLoader.item : paneL
    property string splitStartPath: ""

    function setSplit(vertical) {
        if (splitOn && splitVertical === vertical) {
            if (paneRLoader.item) splitStartPath = paneRLoader.item.path;
            splitOn = false;
            focusPane = 0;
        } else if (splitOn) {
            splitVertical = vertical;      // re-orient, keeping both panes
        } else {
            if (splitStartPath === "" || !Docs.exists(splitStartPath))
                splitStartPath = paneL.path;
            splitVertical = vertical;
            splitOn = true;
            focusPane = 1;
        }
        Settings.set("split", splitOn);
        Settings.set("splitVertical", splitVertical);
    }
    function setSplitRatio(r) {
        splitRatio = Math.max(0.15, Math.min(0.85, r));
    }

    // ---- search ----
    property bool searchOpen: false
    property string query: ""
    property var results: []
    property string status: ""

    function runSearch() {
        pane.query = query;
        if (query.length > 1) {
            results = Library.search(pane.path, query);
            sideMode = "results";
            sideOpen = true;
        } else {
            results = [];
        }
    }
    // Ctrl+F is the desktop's find key (docs/DESIGN.md §11.2), so pressing it
    // again while the bar is already open re-selects the query rather than
    // doing nothing — the find-again gesture every other program has.
    function openSearch() {
        searchOpen = true;
        searchField.forceActiveFocus();
        searchField.selectAll();
    }
    function closeSearch() {
        searchOpen = false;
        query = "";
        paneL.query = "";
        if (paneRLoader.item) paneRLoader.item.query = "";
        results = [];
        if (sideMode === "results") sideMode = "outline";
    }

    // ---- go to page (PDF mode only) ----
    // The same chip as find, on the same reveal, one cell in from it: a page
    // number is the other thing you type at a document, and a 400-page scan
    // whose only jump is scrolling is not a reader. It refuses a number outside
    // the document VISIBLY rather than doing nothing (§10.2).
    property bool gotoOpen: false
    function openGoto() {
        if (!pdfMode) return;
        gotoOpen = true;
        gotoField.text = String(pane.topIndex + 1);
        gotoField.forceActiveFocus();
        gotoField.selectAll();
    }
    function closeGoto() {
        gotoOpen = false;
        stage.forceActiveFocus();
    }
    function gotoPage(s) {
        var n = parseInt(String(s), 10);
        if (isNaN(n) || n < 1 || n > pane.pageCount) {
            win.status = "no page " + String(s) + " - this document has " + pane.pageCount;
            return;
        }
        pane.jumpTo(n - 1);
        closeGoto();
    }

    // ---- the document panes ----
    function openIn(p, path) { p.navigate(path); }

    title: pane && pane.docName !== "" ? pane.docName : "reader"
    width: 1000
    height: 760
    minimumWidth: 360
    minimumHeight: 240
    visible: true
    color: Theme.bg

    onClosing: {
        persist();
        Qt.quit();
    }

    function persist() {
        Settings.set("path", paneL.path);
        Settings.set("topIndex", paneL.topIndex);
        Settings.set("sideOpen", sideOpen);
        Settings.set("sideMode", sideMode);
        Settings.set("sideWidth", sideWidth);
        Settings.set("split", splitOn);
        Settings.set("splitVertical", splitVertical);
        Settings.set("splitRatio", splitRatio);
        Settings.set("rightPath", paneRLoader.item ? paneRLoader.item.path : splitStartPath);
    }
    // Where the user is in a document is state they would notice reverting
    // (docs/DESIGN.md §14), but it changes on every wheel notch — so it is written
    // on a settle timer rather than per event.
    Timer {
        id: persistTimer
        interval: 800
        onTriggered: win.persist()
    }

    // ---- hyprvtb titlebar: reader's whole chrome ----
    // ASCII, lowercase, one or two characters (§12.1). `|` and `_` are kitty's
    // split glyphs and therefore everyone's; `_` and not `-`, because a bare
    // `-` is the SPACER token in the vtb button-array protocol.
    //
    // The PDF cells are inserted, not appended: a mode's own controls belong
    // beside what they act on, and the two splits stay at the trailing end in
    // every app that has them. `−` is U+2212 and not a hyphen because a bare
    // `-` is the SPACER token in the vtb button-array protocol; viewer's zoom
    // pair is the same two glyphs (§12.1 — a function keeps its glyph).
    readonly property bool pdfMode: pane ? pane.isPdf : false
    // `menu:` is the Plasma session's half of this array — the menubar
    // qmlcommon/DeskMenuBar.qml draws where there is no hyprvtb to draw this
    // column. Inert on the wire (vtbclient.py reads id/label/state/tip).
    readonly property var tbButtons: [
        { id: "back",    label: "<",  state: pane && pane.canBack ? 0 : 2,    tip: "back",
          menu: "go" },
        { id: "forward", label: ">",  state: pane && pane.canForward ? 0 : 2, tip: "forward",
          menu: "go" },
        "-",
        { id: "files",   label: "fl", state: sideOpen && sideMode === "files" ? 1 : 0,
          tip: "browse documents", menu: "view" },
        { id: "outline", label: "ol", state: sideOpen && sideMode === "outline" ? 1 : 0,
          tip: pdfMode ? "this document's bookmarks" : "this document's headings",
          menu: "view" },
        { id: "search",  label: "fs", state: searchOpen ? 1 : 0, tip: "find (Ctrl+F)",
          menu: "edit" },
    ].concat(pdfMode ? [
        "-",
        { id: "zoomout", label: "−",  state: 0, tip: "zoom out", menu: "view" },
        { id: "zoomin",  label: "+",  state: 0, tip: "zoom in", menu: "view" },
        { id: "fitw",    label: "fw", state: pane && pane.fit === "width" ? 1 : 0,
          tip: "fit width", menu: "view" },
        { id: "fitp",    label: "fp", state: pane && pane.fit === "page" ? 1 : 0,
          tip: "fit page", menu: "view" },
        { id: "goto",    label: "gp", state: gotoOpen ? 1 : 0, tip: "go to page (Ctrl+G)",
          menu: "go", menuSep: true },
    ] : []).concat([
        "-",
        { id: "vsplit",  label: "|",  state: splitOn && splitVertical ? 1 : 0,
          tip: "split right", menu: "view" },
        { id: "hsplit",  label: "_",  state: splitOn && !splitVertical ? 1 : 0,
          tip: "split down", menu: "view" },
    ])
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    readonly property string footerStr: {
        if (status !== "") return status;
        var pfx = splitOn ? ("p" + (focusPane + 1) + "/2  ") : "";
        if (query.length > 1 && pane)
            return pfx + (pane.matches.length ? (pane.matchAt + 1) + "/" + pane.matches.length
                                              : "0/0") + "  " + query;
        // Where you are in a PDF is the thing a page view has to say, and the
        // footer is where this app already says it (§7.4). Page first, because
        // that is what is asked for; the zoom after it, so the two `fit` cells
        // report a number rather than only a lit state (§10.6).
        if (pdfMode && pane && pane.pageCount > 0)
            return pfx + (pane.topIndex + 1) + "/" + pane.pageCount + "  "
                   + Math.round(pane.zoomPct) + "%  " + pane.docName;
        return pfx + (pane ? pane.docName : "");
    }
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    // ONE handler, TWO chromes: the hyprvtb titlebar column clicks it, and in a
    // Plasma session `menuBar` does (qmlcommon/DeskMenuBar.qml). Same ids.
    function tbAction(id) {
        switch (id) {
        case "back":    win.pane.goBack();     break;
        case "forward": win.pane.goForward();  break;
        case "files":   win.setSide("files");  break;
        case "outline": win.setSide("outline"); break;
        case "search":
            if (win.searchOpen) win.closeSearch();
            else win.openSearch();
            break;
        case "vsplit":  win.setSplit(true);    break;
        case "hsplit":  win.setSplit(false);   break;
        case "zoomout": win.pane.zoomOut();    break;
        case "zoomin":  win.pane.zoomIn();     break;
        case "fitw":    win.pane.fitWidth();   break;
        case "fitp":    win.pane.fitPage();    break;
        case "goto":
            if (win.gotoOpen) win.closeGoto();
            else win.openGoto();
            break;
        }
    }

    Connections {
        target: Titlebar
        function onClicked(id) { win.tbAction(id); }
    }

    // A document edited underneath us reloads in place, keeping the scroll
    // position (§6.1). The key says which pane asked to be told.
    Connections {
        target: Docs
        function onFileChanged(key) {
            if (key === "left") paneL.reload();
            else if (paneRLoader.item) paneRLoader.item.reload();
        }
    }

    // The mouse's side buttons walk DOCUMENT history — the file you came from,
    // and the section you came from within it — on the FOCUSED pane, like every
    // other control here. Desktop-global rule, docs/DESIGN.md §11.1.
    NavButtons {
        onBack:    win.pane.goBack()
        onForward: win.pane.goForward()
    }

    Component.onCompleted: {
        sideOpen = Settings.get("sideOpen", true) === true;
        sideMode = String(Settings.get("sideMode", "outline"));
        sideWidth = Number(Settings.get("sideWidth", 260)) || 260;
        splitOn = Settings.get("split", false) === true;
        splitVertical = Settings.get("splitVertical", true) !== false;
        splitRatio = Number(Settings.get("splitRatio", 0.5)) || 0.5;
        splitStartPath = String(Settings.get("rightPath", ""));
        paneL.load(win.startDoc, Number(Settings.get("topIndex", 0)) || 0);
        Titlebar.setButtons(tbButtons);
        Titlebar.setFooter(footerStr);
    }

    // ---- layout ----
    // The menubar the Plasma session gets in place of the titlebar column;
    // 0-height and invisible in the Hyprland one.
    DeskMenuBar {
        id: menuBar
        anchors { top: parent.top; left: parent.left; right: parent.right }
        buttons: win.tbButtons
        menuOrder: ["edit", "go", "view"]
        onTriggered: (id) => win.tbAction(id)
    }

    Item {
        id: stage
        anchors { top: menuBar.bottom; left: parent.left
                  right: parent.right; bottom: parent.bottom }
        focus: true

        Keys.onPressed: (e) => {
            const alt = (e.modifiers & Qt.AltModifier) !== 0;
            switch (e.key) {
            case Qt.Key_Escape:
                if (win.gotoOpen) { win.closeGoto(); e.accepted = true; }
                else if (win.searchOpen) { win.closeSearch(); e.accepted = true; }
                break;
            // The page-view keys. `+` `−` `0` are viewer's, verbatim — zoom
            // keeps its keys in every app that zooms, the way it keeps its
            // glyphs (§12.1) — and `w` is fit-width, which viewer has no need
            // of. They are PDF-only: in markdown they would claim keys that
            // mean nothing there.
            case Qt.Key_Plus: case Qt.Key_Equal:
                if (win.pdfMode) { win.pane.zoomIn();   e.accepted = true; }
                break;
            case Qt.Key_Minus:
                if (win.pdfMode) { win.pane.zoomOut();  e.accepted = true; }
                break;
            case Qt.Key_0:
                if (win.pdfMode) { win.pane.fitPage();  e.accepted = true; }
                break;
            case Qt.Key_W:
                if (win.pdfMode) { win.pane.fitWidth(); e.accepted = true; }
                break;
            case Qt.Key_PageDown:
                if (win.pdfMode) { win.pane.pageStep(1);  e.accepted = true; }
                break;
            case Qt.Key_PageUp:
                if (win.pdfMode) { win.pane.pageStep(-1); e.accepted = true; }
                break;
            case Qt.Key_Home:
                if (win.pdfMode) { win.pane.jumpTo(0); e.accepted = true; }
                break;
            case Qt.Key_End:
                if (win.pdfMode) { win.pane.jumpTo(win.pane.pageCount - 1); e.accepted = true; }
                break;
            case Qt.Key_F3:
                win.setSplit(e.modifiers & Qt.ShiftModifier ? !win.splitVertical : win.splitVertical);
                e.accepted = true;
                break;
            case Qt.Key_Left:
                if (alt) { win.pane.goBack(); e.accepted = true; }
                break;
            case Qt.Key_Right:
                if (alt) { win.pane.goForward(); e.accepted = true; }
                break;
            case Qt.Key_Tab:
                if (win.splitOn) { win.focusPane = win.focusPane === 0 ? 1 : 0; e.accepted = true; }
                break;
            }
        }

        // the browse pane
        Sidebar {
            id: side
            x: 0
            y: 0
            width: win.sideShown
            height: parent.height
            visible: win.sideOpen
            mode: win.sideMode
            cellW: win.cellW
            winActive: win.renderActive
            query: win.query
            files: win.fileIndex
            outline: win.pane ? win.pane.outline : []
            results: win.results
            currentPath: win.pane ? win.pane.path : ""
            section: win.pane ? win.pane.section : -1
            onOpenDoc: (p) => win.pane.navigate(p)
            onOpenResult: (p) => win.pane.openAtMatch(p)
            onJumpIndex: (i) => win.pane.jumpIndex(i)
        }

        // The sidebar divider. It tracks the pointer exactly — a
        // direct-manipulation drag has zero easing (§6.4) — and the width is
        // persisted on RELEASE, never per motion event.
        MouseArea {
            id: sideGrip
            visible: win.sideOpen
            x: win.sideShown - 2
            width: 5
            height: parent.height
            hoverEnabled: true
            cursorShape: Qt.SplitHCursor
            onPositionChanged: (m) => {
                if (!pressed) return;
                win.sideWidth = Math.max(win.minSide,
                                         Math.min(win.width * 0.6, mapToItem(stage, m.x, 0).x));
            }
            onReleased: Settings.set("sideWidth", win.sideWidth)
            Rectangle {
                anchors.centerIn: parent
                width: 1
                height: parent.height
                color: sideGrip.pressed || sideGrip.containsMouse ? Theme.accent : Theme.border
            }
        }

        // the documents
        Item {
            id: docArea
            x: win.sideShown
            width: parent.width - x
            height: parent.height
            clip: true

            DocPane {
                id: paneL
                watchKey: "left"
                x: 0
                y: 0
                width: win.splitOn && win.splitVertical ? win.paneLeadSize : docArea.width
                height: win.splitOn && !win.splitVertical ? win.paneLeadSize : docArea.height
                cellW: win.cellW
                winActive: win.renderActive
                focused: !win.splitOn || win.focusPane === 0
                onFocusClaimed: win.focusPane = 0
                onStatusChanged: (m) => win.status = m
                onContextRequested: (x, y, i) => win.showMenu(paneL, x, y, i)
                onOpened: (p) => { win.refreshIndex(p); persistTimer.restart(); }
                onTopIndexChanged: persistTimer.restart()
            }

            Loader {
                id: paneRLoader
                active: win.splitOn
                // Synchronous: nothing on screen loads asynchronously (§6.1).
                asynchronous: false
                x: win.splitVertical ? win.paneTrailPos : 0
                y: win.splitVertical ? 0 : win.paneTrailPos
                width: win.splitVertical ? win.paneTrailSize : docArea.width
                height: win.splitVertical ? docArea.height : win.paneTrailSize
                sourceComponent: DocPane {
                    watchKey: "right"
                    cellW: win.cellW
                    winActive: win.renderActive
                    focused: win.focusPane === 1
                    onFocusClaimed: win.focusPane = 1
                    onStatusChanged: (m) => win.status = m
                    onContextRequested: (x, y, i) => win.showMenu(paneRLoader.item, x, y, i)
                    onTopIndexChanged: persistTimer.restart()
                    Component.onCompleted: load(win.splitStartPath !== ""
                                                ? win.splitStartPath : paneL.path, 0)
                }
            }

            // The splitter, on whichever axis is live.
            MouseArea {
                id: splitGrip
                visible: win.splitOn
                x: win.splitVertical ? win.paneLeadSize : 0
                y: win.splitVertical ? 0 : win.paneLeadSize
                width: win.splitVertical ? win.splitterW : docArea.width
                height: win.splitVertical ? docArea.height : win.splitterW
                hoverEnabled: true
                cursorShape: win.splitVertical ? Qt.SplitHCursor : Qt.SplitVCursor
                onPositionChanged: (m) => {
                    if (!pressed) return;
                    var p = mapToItem(docArea, m.x, m.y);
                    win.setSplitRatio((win.splitVertical ? p.x / docArea.width
                                                         : p.y / docArea.height));
                }
                onReleased: Settings.set("splitRatio", win.splitRatio)
                Rectangle {
                    anchors.fill: parent
                    color: splitGrip.pressed || splitGrip.containsMouse ? Theme.accent
                                                                        : Theme.border
                }
            }

            // Which pane the chrome is pointed at — a 1px accent frame, drawn
            // over the content and grabbing no input (viewer's and surfer's
            // split mark theirs the same way). Only meaningful once split.
            Rectangle {
                visible: win.splitOn
                z: 9
                x: win.pane === paneL ? 0 : paneRLoader.x
                y: win.pane === paneL ? 0 : paneRLoader.y
                width: win.pane === paneL ? paneL.width : paneRLoader.width
                height: win.pane === paneL ? paneL.height : paneRLoader.height
                color: "transparent"
                radius: Theme.rounding
                border.width: Theme.ctrlBorder
                border.color: win.renderActive ? Theme.accent : Theme.dim
            }

            // ---- the search bar ----
            // The canonical reveal (§6.2.1): a clipped chip growing from a
            // FIXED far edge, toward the titlebar cell that owns it, at the
            // desktop's own slide duration and curve. It overlays the document
            // rather than reflowing it — the text under it must not move.
            Item {
                id: searchClip
                z: 30
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: 10
                anchors.topMargin: 10
                width: win.searchOpen ? chipW : 0
                height: Theme.lineHeight + 10
                clip: true
                visible: width > 0

                readonly property real chipW: Math.min(docArea.width - 20, 46 * win.cellW)
                Behavior on width {
                    NumberAnimation {
                        duration: motion.ms(motion.slideMs)
                        easing.type: motion.slideEasing
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    width: searchClip.chipW
                    height: parent.height
                    color: Theme.bgAlt
                    radius: Theme.rounding
                    border.width: Theme.ctrlBorder
                    border.color: win.fgAccent

                    TextInput {
                        id: searchField
                        anchors {
                            left: parent.left; leftMargin: 6
                            right: count.left; rightMargin: 6
                            verticalCenter: parent.verticalCenter
                        }
                        font: Theme.editorFont   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
                        renderType: Text.NativeRendering
                        color: win.fgText
                        // accent/bg, not the near-black `highlight` fill: a
                        // second Ctrl+F re-SELECTS the query (openSearch), and
                        // at 1.15:1 on black that gesture looked like nothing
                        // happening. askpass, painter and surfer's own find bar
                        // all select this way.
                        selectionColor: Theme.accent
                        selectedTextColor: Theme.bg
                        clip: true
                        text: win.query
                        onTextChanged: {
                            win.query = text;
                            win.pane.query = text;
                            searchDebounce.restart();
                        }
                        Keys.onPressed: (e) => {
                            if (e.key === Qt.Key_Escape) { win.closeSearch(); stage.forceActiveFocus(); e.accepted = true; }
                            else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                                win.pane.stepMatch(e.modifiers & Qt.ShiftModifier ? -1 : 1);
                                e.accepted = true;
                            }
                        }
                    }
                    // The count is the honest report of what the query found:
                    // never a blank box that might or might not have searched.
                    PixelText {
                        id: count
                        anchors {
                            right: parent.right; rightMargin: 6
                            verticalCenter: parent.verticalCenter
                        }
                        color: win.fgDim
                        text: win.query.length < 2 ? ""
                            : (win.pane.matches.length
                               ? (win.pane.matchAt + 1) + "/" + win.pane.matches.length
                               : "0/0") + "  " + win.results.length + "f"
                    }
                }
            }
            // ---- go to page ----
            // The find chip's twin: same reveal, same clip, same duration
            // (§6.2.1), stacked under it when both are open rather than
            // overlapping it. It is only ever built in PDF mode.
            Item {
                id: gotoClip
                z: 30
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: 10
                anchors.topMargin: 10 + (win.searchOpen ? searchClip.height + 6 : 0)
                width: win.gotoOpen ? chipW : 0
                height: Theme.lineHeight + 10
                clip: true
                visible: width > 0 && win.pdfMode

                readonly property real chipW: Math.min(docArea.width - 20, 22 * win.cellW)
                Behavior on width {
                    NumberAnimation {
                        duration: motion.ms(motion.slideMs)
                        easing.type: motion.slideEasing
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    width: gotoClip.chipW
                    height: parent.height
                    color: Theme.bgAlt
                    radius: Theme.rounding
                    border.width: Theme.ctrlBorder
                    border.color: win.fgAccent

                    PixelText {
                        id: gotoLabel
                        anchors {
                            left: parent.left; leftMargin: 6
                            verticalCenter: parent.verticalCenter
                        }
                        color: win.fgDim
                        text: "page"
                    }
                    TextInput {
                        id: gotoField
                        anchors {
                            left: gotoLabel.right; leftMargin: 6
                            right: ofN.left; rightMargin: 6
                            verticalCenter: parent.verticalCenter
                        }
                        font: Theme.editorFont   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
                        renderType: Text.NativeRendering
                        color: win.fgText
                        selectionColor: Theme.accent
                        selectedTextColor: Theme.bg
                        clip: true
                        validator: IntValidator { bottom: 1 }
                        Keys.onPressed: (e) => {
                            if (e.key === Qt.Key_Escape) { win.closeGoto(); e.accepted = true; }
                            else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                                win.gotoPage(gotoField.text);
                                e.accepted = true;
                            }
                        }
                    }
                    // What you may type — the honest bound, not a box that
                    // silently rejects (§10.2).
                    PixelText {
                        id: ofN
                        anchors {
                            right: parent.right; rightMargin: 6
                            verticalCenter: parent.verticalCenter
                        }
                        color: win.fgDim
                        text: "/" + (win.pane ? win.pane.pageCount : 0)
                    }
                }
            }

            // Cross-document search is a filesystem walk, so it runs when the
            // typing settles; the in-document highlight is live and free.
            Timer {
                id: searchDebounce
                interval: 220
                onTriggered: win.runSearch()
            }
        }

        // The context menu overlays both panes, so it lives here and not in
        // one of them (the same reason filer keeps one instance at the root).
        CtxMenu {
            id: menu
            anchors.fill: parent
        }
    }

    // ---- the files index ----
    property var fileIndex: []
    function refreshIndex(p) {
        var got = Library.index(p);
        fileIndex = got.files || [];
    }

    // ---- the context menu (§7.1: a new view ships with one) ----
    function showMenu(p, x, y, blockIndex) {
        var b = (blockIndex >= 0 && blockIndex < p.blocks.length) ? p.blocks[blockIndex] : null;
        var items = [];
        if (b && b.type === "code")
            items.push({ label: "copy code", trigger: () => Docs.copy(b.text) });
        if (b)
            items.push({ label: b.type === "code" ? "copy line" : "copy text",
                         trigger: () => Docs.copy(b.text) });
        items.push({ label: "copy path", enabled: p.path !== "",
                     trigger: () => Docs.copy(p.path) });
        items.push({ separator: true });
        items.push({ label: "reload", enabled: p.path !== "", trigger: () => p.reload() });
        items.push({ label: "open folder in filer", enabled: p.path !== "",
                     trigger: () => { if (!Docs.openFolder(p.path)) win.status = "could not run filer"; } });
        menu.open(x, y, items);
    }

    // ---- global keys ----
    // A window-scoped Shortcut, not a case in stage's Keys handler: find has to
    // work while the focus is in a pane, the sidebar or the search field itself
    // (docs/DESIGN.md §11.2).
    Shortcut { sequence: "Ctrl+F"; onActivated: win.openSearch() }
    // Ctrl+G is go-to-page, for the same reason and by the same route: it has
    // to work while the focus is in a pane, the sidebar or the find chip.
    Shortcut { sequence: "Ctrl+G"; onActivated: win.openGoto() }

    // A status line is a report, not a permanent label: it clears itself so the
    // footer goes back to saying what is open.
    onStatusChanged: if (status !== "") statusClear.restart()
    Timer {
        id: statusClear
        interval: 4000
        onTriggered: win.status = ""
    }
}

import QtQuick
import QtWebEngine
import "../../qmlcommon"

// find-in-page — Ctrl+F. The bar docks at the TOP-RIGHT of the page and slides
// down out of the window edge, the same motion (and the same `Motion` source)
// the dark-mode drawer and the page tooltip use.
//
// The hotkey does NOT arrive here as a QML `Shortcut`. Chromium owns the
// keyboard whenever a WebEngineView has the focus, so the key is caught by the
// window-scoped `HotkeyFilter` in main.py — upstream of the view, the same place
// Ctrl +/-/0 are taken — and Main.qml turns its `Hotkeys.find` signal into
// `openFind()`. Escape is the mirror image and needs no filter: it only has to
// work while THIS field holds the keyboard, and then Qt delivers it here.
//
// The search runs against `view` — the FOCUSED pane, so it follows the chrome
// like every other control (apps/AGENTS.md). Switching pane or tab while the
// bar is open clears the highlight off the view we were searching before
// re-running on the new one; a highlight left behind on a page nobody searched
// is indistinguishable from a bug.
Rectangle {
    id: root

    // the WebEngineView to search: win.current (the focused pane)
    property var view: null
    // the view findText() was last aimed at, so its highlight can be cleared
    // even after `view` has moved on
    property var searched: null

    property bool shown: false

    // The window's focus state, handed down (docs/DESIGN.md §3.1.1). A leaf
    // never reads Window.active itself: `Qt.application.state` is per-APPLICATION
    // and stays Active while another of surfer's windows takes focus.
    property bool winActive: true
    // how far down the top edge the bar docks — the permission bar takes the
    // first 36px when it is up, and two overlapping bars at the top edge is
    // exactly the dead-space defect docs/DESIGN.md 5.2 names
    property real dockY: 0

    property int matches: 0
    property int activeMatch: 0

    // The query and the count are exposed rather than buried in the field, so
    // tools/find-test.py can drive and read this bar offscreen without knowing
    // its internals (and without a screen — the user does the visual check).
    property alias query: input.text
    readonly property bool hasQuery: query.length > 0
    readonly property bool canStep: matches > 0
    readonly property string countLabel: !hasQuery ? ""
        : matches > 0 ? (activeMatch + "/" + matches)
        : "no matches"
    readonly property bool fieldFocused: input.activeFocus

    signal closed()

    function openFind() {
        shown = true;
        input.forceActiveFocus();
        input.selectAll();      // a second Ctrl+F replaces the old query
        if (query.length > 0) search(false);
    }

    function closeFind() {
        clearHighlight();
        shown = false;
        matches = 0;
        activeMatch = 0;
        // hand the keyboard back to the page, or the next keystroke goes
        // nowhere at all (docs/DESIGN.md 11: never a state that needs two clicks)
        if (view) view.forceActiveFocus();
        root.closed();
    }

    // findText("") is what drops Chromium's highlight; without it the matches
    // stay lit on a page whose find bar is gone.
    function clearHighlight() {
        var v = searched;
        searched = null;
        if (!v) return;
        try { v.findText(""); } catch (e) {}
        try { v.runJavaScript(root.markJs("", 0, 0)); } catch (e) {}
    }

    // ---- the marks the eye actually reads ---------------------------------
    //
    // Chromium DOES light every match (yellow) and the one you are on (orange),
    // and under dark mode it may as well not: the whole-page invert filter runs
    // over the markers too, so #ffff00 lands as #252500 on a near-black page —
    // invisible, i.e. exactly the "find just scrolls" complaint. Measured
    // offscreen, and dark mode is on globally with a per-site exception list,
    // so this is what almost every page does.
    //
    // So the marks are ours: the CSS Custom Highlight API over ranges we find
    // ourselves, painted in the wal palette (docs/DESIGN.md §3.1 — `dim` is
    // "inactive", `accent` is "active", and §16's page scrollbars are the
    // precedent for the palette reaching inside a page). Every match is a dim
    // box with accent text; the one you are ON inverts to an accent box with
    // black text, which is the same current-vs-rest ladder every list on this
    // desktop uses and reads at a glance rather than by hue.
    //
    // Dark mode is beaten rather than avoided: DarkMode.compensate() returns
    // the colour whose IMAGE under the page filter is the palette colour, the
    // same trick _dark_css already plays on media. It is the identity when the
    // filter is off, so there is one code path.
    function cssHex(c) {
        function h(x) { var s = Math.round(x * 255).toString(16); return s.length < 2 ? "0" + s : s; }
        return "#" + h(c.r) + h(c.g) + h(c.b);
    }
    function pageColor(c) {
        var hex = cssHex(c);
        if (typeof DarkMode === "undefined" || !view) return hex;
        return DarkMode.compensate(view.url.toString(), hex);
    }

    // `expect` is Chromium's own match count: our walk and its walk can differ
    // (shadow DOM, a match split across block boundaries), and marking the
    // WRONG match as current is worse than marking none, so a disagreement
    // drops the active mark and leaves every match lit.
    function markJs(q, activeIndex, expect) {
        var css = "::highlight(surferFind){background-color:" + pageColor(Theme.dim)
                + ";color:" + pageColor(Theme.text) + "}"
                + "::highlight(surferFindActive){background-color:" + pageColor(Theme.accent)
                + ";color:" + pageColor(Theme.bg) + "}";
        return "(function(q,act,expect,css){"
             + "var SID='__surfer_findhl__';"
             + "var s=document.getElementById(SID);"
             + "if(!s){s=document.createElement('style');s.id=SID;(document.head||document.documentElement).appendChild(s);}"
             + "s.textContent=css;"
             + "if(!window.CSS||!CSS.highlights||!window.Highlight)return;"
             + "CSS.highlights.delete('surferFind');CSS.highlights.delete('surferFindActive');"
             + "window.__surferFindHl={n:0,active:-1};"
             + "if(!q)return;"
             + "var SKIP={SCRIPT:1,STYLE:1,NOSCRIPT:1,TEXTAREA:1,SELECT:1,TITLE:1,HEAD:1};"
             + "var BLOCK={ADDRESS:1,ARTICLE:1,ASIDE:1,BLOCKQUOTE:1,BR:1,DD:1,DETAILS:1,DIV:1,DL:1,"
             + "DT:1,FIELDSET:1,FIGCAPTION:1,FIGURE:1,FOOTER:1,FORM:1,H1:1,H2:1,H3:1,H4:1,H5:1,H6:1,"
             + "HEADER:1,HR:1,LI:1,MAIN:1,NAV:1,OL:1,P:1,PRE:1,SECTION:1,TABLE:1,TD:1,TH:1,TR:1,UL:1};"
             + "var root=document.body||document.documentElement;if(!root)return;"
             + "var w=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT,"
             + "{acceptNode:function(n){return (n.nodeType===1&&SKIP[n.nodeName])"
             + "?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT;}});"
             // one flat string plus a node index, so a match may straddle the
             // inline elements a word gets chopped into; a block boundary
             // becomes U+0001, which no query and no \s can cross — Chromium
             // does not match across one either
             + "var text='',map=[],n;"
             + "while((n=w.nextNode())){"
             + "if(n.nodeType===1){if(BLOCK[n.nodeName])text+='\\u0001';continue;}"
             + "var v=n.nodeValue;if(!v)continue;map.push([n,text.length]);text+=v;}"
             // whitespace in the query matches any run of it: HTML source wraps
             // lines, so a two-word query would otherwise miss
             + "var pat=q.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&').replace(/\\s+/g,'\\\\s+');"
             + "var re;try{re=new RegExp(pat,'gi');}catch(e){return;}"
             + "function locate(off){var lo=0,hi=map.length-1,best=0;"
             + "while(lo<=hi){var mid=(lo+hi)>>1;if(map[mid][1]<=off){best=mid;lo=mid+1;}else hi=mid-1;}"
             + "return best;}"
             + "var hits=[],m,guard=0;"
             + "while((m=re.exec(text))&&guard++<2000){"
             + "if(m[0].length===0){re.lastIndex++;continue;}"
             + "var a=locate(m.index),b=locate(m.index+m[0].length-1);"
             + "var r=document.createRange();"
             + "try{r.setStart(map[a][0],m.index-map[a][1]);"
             + "r.setEnd(map[b][0],m.index+m[0].length-map[b][1]);}catch(e){continue;}"
             // a range with no client rects is text nobody can see, which is
             // what Chromium skips too — dropping it keeps the two counts equal
             + "if(!r.getClientRects().length)continue;"
             + "hits.push(r);}"
             + "var idx=(expect>0&&hits.length!==expect)?-1:act;"
             + "var all=new Highlight(),cur=new Highlight();"
             + "for(var i=0;i<hits.length;i++){(i===idx?cur:all).add(hits[i]);}"
             + "CSS.highlights.set('surferFind',all);"
             + "if(idx>=0)CSS.highlights.set('surferFindActive',cur);"
             + "window.__surferFindHl={n:hits.length,active:idx};"
             + "})(" + JSON.stringify(q) + "," + activeIndex + "," + expect + ","
             + JSON.stringify(css) + ");";
    }

    // Chromium's activeMatch is 1-based; -1 when there is nothing to be on.
    function applyMarks() {
        if (!searched) return;
        try { searched.runJavaScript(root.markJs(query, matches > 0 ? activeMatch - 1 : -1, matches)); }
        catch (e) {}
    }

    // `query.length`, never `hasQuery`: this runs from onTextChanged, and the
    // bound property is not guaranteed to have re-evaluated yet — reading it
    // here left a cleared field still holding the highlight (measured).
    function search(backward) {
        if (!view) { matches = 0; activeMatch = 0; return; }
        if (query.length === 0) { clearHighlight(); matches = 0; activeMatch = 0; return; }
        if (searched && searched !== view) clearHighlight();
        searched = view;
        view.findText(query, backward ? WebEngineView.FindBackward : 0);
    }

    // The count comes back on the SIGNAL, not through findText()'s callback
    // argument: on PySide6 6.11 / QtWebEngine 6.11 that third-argument callback
    // is never invoked at all, while findTextFinished carries the same
    // QWebEngineFindTextResult and fires every time (measured offscreen —
    // tools/find-test.py asserts the count, so a regression here is loud).
    Connections {
        target: root.view
        ignoreUnknownSignals: true
        function onFindTextFinished(result) {
            // the result outlives the keystroke: the bar may already be closed,
            // or pointed somewhere else, by the time it lands
            if (!root.shown) return;
            root.matches = result.numberOfMatches;
            root.activeMatch = result.activeMatch;
            root.applyMarks();
        }
    }

    // pane/tab switch under an open bar: unlight the old page, light the new one
    onViewChanged: {
        if (searched && searched !== view) clearHighlight();
        if (shown && query.length > 0) search(false);
        else { matches = 0; activeMatch = 0; }
    }

    Motion { id: motion }
    property real slide: shown ? 1 : 0
    Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }

    visible: slide > 0.001
    z: 2100
    width: bodyRow.implicitWidth + 12
    height: 34
    // docked at the right edge, sliding down out of the top one
    x: parent ? Math.max(0, parent.width - width - 8) : 0
    y: -height + slide * (height + dockY)
    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: Theme.accent

    // the page must not receive clicks aimed at the bar
    MouseArea { anchors.fill: parent }

    // Positioned, not anchor-filled: `width` above reads this Row's
    // implicitWidth, and a Row that fills its parent would make that a loop.
    Row {
        id: bodyRow
        x: 6
        y: 6
        height: 22
        spacing: 6

        Rectangle {
            width: 200
            height: parent.height
            color: Theme.bg
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: input.activeFocus ? Theme.accent : Theme.border

            TextInput {
                id: input
                anchors { fill: parent; margins: 4 }
                verticalAlignment: TextInput.AlignVCenter
                color: Theme.text
                font: (typeof DeskStyle !== "undefined" && DeskStyle
                       && typeof DeskStyle.editorFontForScale === "function")
                      ? DeskStyle.editorFontForScale(Screen.devicePixelRatio)
                      : Theme.editorFontForScale(Screen.devicePixelRatio) // whole QFont, including Kitty cell spacing
                renderType: Text.NativeRendering
                clip: true
                selectByMouse: true
                selectionColor: Theme.accent
                selectedTextColor: Theme.bg

                onTextChanged: root.search(false)

                // Enter steps forward, Shift+Enter back, Escape closes — so the
                // hand that typed the query never has to leave the keyboard.
                // ONE handler rather than Keys.onReturnPressed/onEscapePressed:
                // the modifier-carrying variants of those never reached us
                // (Shift+Enter did nothing at all, measured), and reading
                // `event.modifiers` here works.
                Keys.onPressed: (event) => {
                    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                        root.search((event.modifiers & Qt.ShiftModifier) !== 0);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Escape) {
                        root.closeFind();
                        event.accepted = true;
                    }
                }
            }

            PixelText {
                anchors { left: parent.left; leftMargin: 5; verticalCenter: parent.verticalCenter }
                visible: input.text.length === 0
                text: "find"
                color: Theme.dim
            }
        }

        // The count, in a fixed slot: it is the widest string this bar draws and
        // it changes on every keystroke, so the space is reserved and only the
        // label comes and goes (docs/DESIGN.md 5.4). "no matches" is warn, not
        // crit — a query that isn't there yet is not an error.
        Item {
            width: 84
            height: parent.height
            PixelText {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                elide: Text.ElideRight
                width: parent.width
                horizontalAlignment: Text.AlignRight
                text: root.countLabel
                color: root.matches > 0 ? Theme.textDim : Theme.warn
            }
        }

        // `<`/`>` are the titlebar's step vocabulary (docs/DESIGN.md 12.1) and
        // both are in the pixel font's cmap. Dimmed AND refusing while there is
        // nothing to step through — 10.2 wants both halves.
        BrowserButton {
            winActive: root.winActive
            label: "<"
            enabled: root.canStep
            onClicked: root.search(true)
        }
        BrowserButton {
            winActive: root.winActive
            label: ">"
            enabled: root.canStep
            onClicked: root.search(false)
        }
        BrowserButton {
            winActive: root.winActive
            label: "x"
            onClicked: root.closeFind()
        }
    }
}

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
    border.width: 1
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
            border.width: 1
            border.color: input.activeFocus ? Theme.accent : Theme.border

            TextInput {
                id: input
                anchors { fill: parent; margins: 4 }
                verticalAlignment: TextInput.AlignVCenter
                color: Theme.text
                font.family: Theme.font
                font.pixelSize: Theme.fontSize
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
            label: "<"
            enabled: root.canStep
            onClicked: root.search(true)
        }
        BrowserButton {
            label: ">"
            enabled: root.canStep
            onClicked: root.search(false)
        }
        BrowserButton {
            label: "x"
            onClicked: root.closeFind()
        }
    }
}

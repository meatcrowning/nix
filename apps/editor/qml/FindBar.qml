import QtQuick
import "../../qmlcommon"

// find / replace — Ctrl+F and Ctrl+R. The house find-bar idiom
// (`apps/surfer/qml/FindBar.qml`, and reader's find chip): a clipped chip
// docked at the TOP-RIGHT of the content, growing out of a FIXED far edge
// toward the titlebar cell that owns it, at the desktop's own slide duration
// and curve (docs/DESIGN.md §6.2.1). It OVERLAYS the code rather than
// reflowing it — the line you were reading must not move because you pressed
// Ctrl+F.
//
// What is editor's own, and why:
//
//  * **A second row for replace**, revealed by the same growth on the other
//    axis, so Ctrl+F and Ctrl+R are one control in two heights rather than two
//    bars fighting for the same corner.
//  * **Three modifier toggles** — regex, case, whole-word — drawn as lit
//    buttons, which is §12.1's inverted-toggle vocabulary borrowed from the
//    titlebar so a lit thing looks lit everywhere.
//  * **The all-matches highlight is not drawn here at all.** It is painted by
//    the document's own syntax highlighter (`highlight.py`, `set_query`), so
//    every match in the file is lit in one pass with no geometry arithmetic and
//    no second scan. This bar only reports the COUNT and steps between them.
//  * `bad regex` is a distinct answer from `no matches`, because they are
//    distinct facts and reporting one as the other is the silent failure §10.2
//    forbids.
Rectangle {
    id: root

    property bool shown: false
    property bool replaceMode: false
    property bool winActive: true

    property alias query: input.text
    property alias replacement: repInput.text
    property bool useRegex: false
    property bool caseSensitive: false
    property bool wholeWords: false

    property int matches: 0
    property int activeMatch: 0         // 1-based; 0 = not on one
    property bool valid: true

    readonly property bool hasQuery: query.length > 0
    readonly property bool canStep: matches > 0
    readonly property string countLabel: !hasQuery ? ""
        : !valid ? "bad regex"
        : matches === 0 ? "no matches"
        : (activeMatch > 0 ? activeMatch + "/" + matches : matches + " found")
    readonly property bool fieldFocused: input.activeFocus || repInput.activeFocus

    // `requery`, not `queryChanged`: `query` is a property alias, so QML already
    // generates a `queryChanged` signal and declaring one collides silently.
    signal requery()
    signal step(bool backward)
    signal replaceCurrent()
    signal replaceEverything()
    signal closed()

    function openFind(replacing) {
        replaceMode = replacing === true ? true : (replacing === false ? false : replaceMode);
        shown = true;
        input.forceActiveFocus();
        input.selectAll();              // §11.2: a second Ctrl+F re-selects
        if (query.length > 0) root.requery();
    }

    function closeFind() {
        shown = false;
        root.closed();
    }

    // Seed the query from whatever is selected, the way every editor does — but
    // only for a single-line selection, since a multi-line one is a region you
    // are about to act on, not a thing you are looking for.
    function seed(text) {
        if (text.length > 0 && text.indexOf("\n") < 0 && text.length < 200)
            input.text = text;
    }

    Motion { id: motion }
    property real slide: shown ? 1 : 0
    Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs)
                                          easing.type: motion.slideEasing } }

    readonly property real rowH: Theme.lineHeight + 10
    readonly property real fullH: (replaceMode ? 2 : 1) * rowH + (replaceMode ? 4 : 0) + 8

    visible: slide > 0.001
    z: 2100
    width: Math.min(parent ? parent.width - 12 : 400, bodyCol.implicitWidth + 12)
    height: fullH
    x: parent ? Math.max(6, parent.width - width - 8) : 0
    y: -height + slide * (height + 8)
    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: winActive ? Theme.accent : Theme.inactive

    Behavior on height { NumberAnimation { duration: motion.ms(motion.slideMs)
                                           easing.type: motion.slideEasing } }

    // the content must not receive clicks aimed at the bar
    MouseArea { anchors.fill: parent }

    Column {
        id: bodyCol
        x: 6
        y: 4
        spacing: 4

        // ---- the query row ----
        Row {
            height: root.rowH
            spacing: 6

            Rectangle {
                width: 22 * root.oneW
                height: parent.height
                color: Theme.bg
                radius: Theme.rounding
                border.width: Theme.ctrlBorder
                border.color: input.activeFocus ? (root.winActive ? Theme.accent : Theme.inactive)
                                                : Theme.border

                TextInput {
                    id: input
                    anchors { fill: parent; margins: 4 }
                    verticalAlignment: TextInput.AlignVCenter
                    color: root.winActive ? Theme.text : Theme.inactive
                    font: Theme.editorFont   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
                    renderType: Text.NativeRendering
                    clip: true
                    selectByMouse: true
                    selectionColor: Theme.highlight
                    selectedTextColor: Theme.accent

                    onTextChanged: root.requery()

                    // ONE handler, not Keys.onReturnPressed/onEscapePressed: the
                    // modifier-carrying variants of those never arrive (surfer's
                    // FindBar measured Shift+Enter doing nothing at all), and
                    // reading `event.modifiers` here works.
                    Keys.onPressed: (e) => {
                        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                            if ((e.modifiers & Qt.ControlModifier) && root.replaceMode)
                                root.replaceEverything();
                            else
                                root.step((e.modifiers & Qt.ShiftModifier) !== 0);
                            e.accepted = true;
                        } else if (e.key === Qt.Key_Escape) {
                            root.closeFind();
                            e.accepted = true;
                        } else if (e.key === Qt.Key_Down && root.replaceMode) {
                            repInput.forceActiveFocus();
                            e.accepted = true;
                        }
                    }
                }

                PixelText {
                    anchors { left: parent.left; leftMargin: 5
                              verticalCenter: parent.verticalCenter }
                    visible: input.text.length === 0
                    text: "find"
                    color: Theme.dim
                }
            }

            // The count, in a FIXED slot: it is the widest string this bar draws
            // and it changes on every keystroke, so the space is reserved and
            // only the label comes and goes (§5.4). `no matches` is warn and
            // `bad regex` is crit — a query that has not matched yet is not an
            // error, an unparseable one is.
            Item {
                width: 11 * root.oneW
                height: parent.height
                PixelText {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    width: parent.width
                    horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                    text: root.countLabel
                    color: !root.valid ? Theme.crit
                         : root.matches > 0 ? Theme.textDim : Theme.warn
                }
            }

            // `<`/`>` are the desktop's step vocabulary (§12.1), and both are in
            // the pixel font. Dimmed AND refusing while there is nothing to step
            // through — §10.2 wants both halves.
            EdButton {
                label: "<"; winActive: root.winActive; enabled: root.canStep
                onClicked: root.step(true)
            }
            EdButton {
                label: ">"; winActive: root.winActive; enabled: root.canStep
                onClicked: root.step(false)
            }
            EdButton {
                label: ".*"; winActive: root.winActive; lit: root.useRegex
                onClicked: { root.useRegex = !root.useRegex; root.requery(); }
            }
            EdButton {
                label: "Aa"; winActive: root.winActive; lit: root.caseSensitive
                onClicked: { root.caseSensitive = !root.caseSensitive; root.requery(); }
            }
            EdButton {
                label: "ab"; winActive: root.winActive; lit: root.wholeWords
                onClicked: { root.wholeWords = !root.wholeWords; root.requery(); }
            }
            EdButton {
                label: "x"; winActive: root.winActive
                onClicked: root.closeFind()
            }
        }

        // ---- the replace row ----
        Row {
            visible: root.replaceMode
            height: root.rowH
            spacing: 6

            Rectangle {
                width: 22 * root.oneW
                height: parent.height
                color: Theme.bg
                radius: Theme.rounding
                border.width: Theme.ctrlBorder
                border.color: repInput.activeFocus ? (root.winActive ? Theme.accent : Theme.inactive)
                                                   : Theme.border

                TextInput {
                    id: repInput
                    anchors { fill: parent; margins: 4 }
                    verticalAlignment: TextInput.AlignVCenter
                    color: root.winActive ? Theme.text : Theme.inactive
                    font: Theme.editorFont   // whole QFont: NoAntialias (docs/DESIGN.md 2.2)
                    renderType: Text.NativeRendering
                    clip: true
                    selectByMouse: true
                    selectionColor: Theme.highlight
                    selectedTextColor: Theme.accent

                    Keys.onPressed: (e) => {
                        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                            if (e.modifiers & Qt.ControlModifier) root.replaceEverything();
                            else root.replaceCurrent();
                            e.accepted = true;
                        } else if (e.key === Qt.Key_Escape) {
                            root.closeFind();
                            e.accepted = true;
                        } else if (e.key === Qt.Key_Up) {
                            input.forceActiveFocus();
                            e.accepted = true;
                        }
                    }
                }

                PixelText {
                    anchors { left: parent.left; leftMargin: 5
                              verticalCenter: parent.verticalCenter }
                    visible: repInput.text.length === 0
                    text: root.useRegex ? "replace ($1 ok)" : "replace with"
                    color: Theme.dim
                }
            }

            // Reserved to the same width as the count slot above, so the two
            // rows' buttons line up in one column instead of stepping (§5.5).
            Item { width: 11 * root.oneW; height: parent.height }

            EdButton {
                label: "rp"; winActive: root.winActive; enabled: root.canStep
                onClicked: root.replaceCurrent()
            }
            EdButton {
                label: "all"; winActive: root.winActive; enabled: root.canStep
                onClicked: root.replaceEverything()
            }
        }
    }

    // The pixel font is monospace, so one measurement gives every reserved slot
    // in this bar its column — §2.7: a fixed pixel budget standing in for a
    // character count breaks the moment the font size slider moves.
    TextMetrics {
        id: cellMetrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real oneW: cellMetrics.width > 0 ? cellMetrics.width / 10
                                                       : Math.round(0.533 * Theme.fontSize)
}

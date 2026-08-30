import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// The open / save-as prompt: one path field with live completion, docked at the
// TOP-LEFT of the content and sliding out of the top edge — the find bar's twin,
// on the other side, so the two can never overlap.
//
// **Why this and not a `FileDialog`.** Qt's platform dialog is the one thing
// this desktop could put on screen that would look like nothing else on it, and
// docs/DESIGN.md §7.2 is explicit that menus and pickers are ours. A monospace
// path field with completion is also strictly faster for the case this editor is
// for — typing `~/nix/home/prog/ed<Tab>` — and it is the same gesture the shell
// in the terminal next to it already has.
//
// filer's FileChooser portal is the other route and is deliberately not used:
// it ships dormant (`filer-portal-switch on`), so an editor that depended on it
// would have no way to open a file on a machine where it is off.
Rectangle {
    id: root

    property bool shown: false
    property string mode: "open"          // open | saveas | goto
    property bool winActive: true

    property alias path: input.text
    property var entries: []
    property int hi: -1                   // highlighted completion, -1 = none

    signal accepted(string path)
    signal cancelled()

    readonly property bool fieldFocused: input.activeFocus
    readonly property string caption: mode === "saveas" ? "save as"
                                    : mode === "goto" ? "line" : "open"
    //: go-to-line is the same prompt with no filesystem behind it — one chip, one
    //: place the keyboard lands, rather than a third slide-out that looks the
    //: same and behaves differently.
    readonly property bool completing: mode !== "goto"

    function openPrompt(m, seedPath) {
        mode = m;
        input.text = seedPath || "";
        shown = true;
        input.forceActiveFocus();
        input.cursorPosition = input.text.length;
        refresh();
    }

    function closePrompt() {
        shown = false;
        entries = [];
        hi = -1;
        root.cancelled();
    }

    function refresh() {
        entries = completing ? Files.complete(input.text) : [];
        hi = -1;
    }

    // Tab completes to the longest unambiguous prefix, then lists — readline's
    // behaviour, because that is the one every hand here already knows. A single
    // match that is a directory gets its `/` so the next Tab descends.
    function completeNow() {
        if (entries.length === 0) return;
        if (entries.length === 1) {
            input.text = entries[0].path + (entries[0].dir ? "/" : "");
            input.cursorPosition = input.text.length;
            refresh();
            return;
        }
        var common = entries[0].name;
        for (var i = 1; i < entries.length; i++) {
            var n = entries[i].name, j = 0;
            while (j < common.length && j < n.length && common[j] === n[j]) j++;
            common = common.substring(0, j);
        }
        if (common.length > 0) {
            var dir = entries[0].path.substring(0, entries[0].path.length - entries[0].name.replace(/\/$/, "").length);
            input.text = dir + common;
            input.cursorPosition = input.text.length;
        }
    }

    function take(i) {
        if (i < 0 || i >= entries.length) return;
        var e = entries[i];
        input.text = e.path + (e.dir ? "/" : "");
        input.cursorPosition = input.text.length;
        refresh();
        if (!e.dir) root.accepted(input.text);
    }

    Motion { id: motion }
    property real slide: shown ? 1 : 0
    Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs)
                                          easing.type: motion.slideEasing } }

    readonly property real rowH: Theme.lineHeight + 10
    readonly property real listH: Math.min(10 * (Theme.fontSize + 2),
                                           entries.length * (Theme.fontSize + 2))

    visible: slide > 0.001
    z: 2100
    width: Math.min(parent ? parent.width - 16 : 520, 64 * oneW)
    height: rowH + 8 + (entries.length > 0 ? listH + 1 : 0)
    x: 8
    y: -height + slide * (height + 8)
    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: winActive ? Theme.accent : Theme.inactive

    MouseArea { anchors.fill: parent }

    Row {
        id: headRow
        x: 6
        y: 4
        height: root.rowH
        spacing: 6

        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            text: root.caption
            color: root.winActive ? Theme.textDim : Theme.inactive
        }

        Rectangle {
            width: root.width - 12 - root.oneW * (root.caption.length + 1) - 6
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
                font.letterSpacing: Theme.fontLetterSpacing(Screen.devicePixelRatio)
                renderType: Text.NativeRendering
                clip: true
                selectByMouse: true
                selectionColor: Theme.highlight
                selectedTextColor: Theme.accent

                onTextChanged: root.refresh()

                Keys.onPressed: (e) => {
                    if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                        if (root.hi >= 0) root.take(root.hi);
                        else if (input.text.length > 0) root.accepted(input.text);
                        e.accepted = true;
                    } else if (e.key === Qt.Key_Escape) {
                        root.closePrompt();
                        e.accepted = true;
                    } else if (e.key === Qt.Key_Tab) {
                        root.completeNow();
                        e.accepted = true;
                    } else if (e.key === Qt.Key_Down) {
                        root.hi = Math.min(root.entries.length - 1, root.hi + 1);
                        list.positionViewAtIndex(root.hi, ListView.Contain);
                        e.accepted = true;
                    } else if (e.key === Qt.Key_Up) {
                        root.hi = Math.max(-1, root.hi - 1);
                        if (root.hi >= 0) list.positionViewAtIndex(root.hi, ListView.Contain);
                        e.accepted = true;
                    }
                }
            }
        }
    }

    // The completion list. Rows are ONE font line box tall with no padding —
    // §9.1's row height and §5.1's zero-gap, the same as the context menu's.
    KineticListView {
        id: list
        visible: root.entries.length > 0
        x: 1
        y: root.rowH + 8
        width: root.width - 2
        height: root.listH
        clip: true
        model: root.entries
        ScrollBar.vertical: VScroll {}

        delegate: Rectangle {
            required property var modelData
            required property int index
            width: list.width
            height: Theme.lineHeight + 2
            color: index === root.hi || ma.containsMouse ? Theme.highlight : "transparent"

            PixelText {
                anchors { left: parent.left; leftMargin: 6
                          right: parent.right; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                elide: Text.ElideMiddle
                text: modelData.name
                // A directory is the brighter tier because it is the thing you
                // are about to descend into (§3.2).
                color: modelData.dir ? (root.winActive ? Theme.accent : Theme.inactive)
                                     : (root.winActive ? Theme.text : Theme.inactive)
            }

            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.take(index)
            }
        }
    }

    TextMetrics {
        id: cellMetrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real oneW: cellMetrics.width > 0 ? cellMetrics.width / 10
                                                       : Math.round(0.533 * Theme.fontSize)
}

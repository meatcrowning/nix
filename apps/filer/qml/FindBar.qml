import QtQuick
import "../../qmlcommon"

// filer's Ctrl+F bar (docs/DESIGN.md §11.2) — one per PANE, because the thing
// being filtered is a directory and a split window is showing two of them.
//
// The same object board's find bar is: docked top-right, sliding down out of the
// surface's edge on the desktop's one motion (`Motion`), a `bgAlt` inset with a
// 1px accent border, the caret in a `bg` box that lights on focus, and a fixed
// slot for the count so the bar never reflows keystroke to keystroke (§5.4).
// It FILTERS rather than stepping through marks, for board's reason: the hits
// are whole rows and tiles and every one of them is shown at once, so there is
// nothing to be "on" (§3.6 does not apply).
Rectangle {
    id: bar

    // Driven by the pane: `open` slides it, `query` is the live text (two-way —
    // the pane owns the value so a close can clear it), `count` and `busy` fill
    // the readout slot.
    property bool open: false
    property string query: ""
    property int count: 0
    property bool busy: false
    property color fgAccent: Theme.accent
    property color fgText: Theme.text

    signal closeRequested()

    // The ONE entry point for the caret: opening, and a second Ctrl+F while it
    // is already open, both land here — the field takes focus and selects its
    // query so the next keystroke replaces it (§11.2's find-again gesture).
    function focusField() {
        input.forceActiveFocus();
        input.selectAll();
    }

    readonly property string countLabel:
        query.trim() === "" ? ""
      : busy ? "…"
      : count > 0 ? (count + (count === 1 ? " match" : " matches"))
      : "no matches"

    Motion { id: motion }
    property real slide: open ? 1 : 0
    Behavior on slide {
        NumberAnimation {
            duration: motion.ms(motion.slideMs)
            easing.type: motion.slideEasing
        }
    }

    visible: slide > 0.001
    z: 900
    width: row.implicitWidth + 12
    height: 34
    x: Math.max(0, parent.width - width - 8)
    y: -height + slide * (height + 8)
    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: bar.fgAccent

    // The pane below must not receive clicks aimed at the bar (its right-click
    // overlay would open a context menu behind it).
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton }

    Row {
        id: row
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
            border.color: input.activeFocus ? bar.fgAccent : Theme.border

            TextInput {
                id: input
                anchors { fill: parent; margins: 4 }
                verticalAlignment: TextInput.AlignVCenter
                color: bar.fgText
                // Whole QFont: an editable item draws a scalable pixel font
                // grey-fringed otherwise (docs/DESIGN.md §2.2).
                font: Theme.editorFont
            font.letterSpacing: Theme.fontLetterSpacing(Screen.devicePixelRatio)
                renderType: Text.NativeRendering
                clip: true
                selectByMouse: true
                selectionColor: bar.fgAccent
                selectedTextColor: Theme.bg
                text: bar.query
                onTextChanged: bar.query = text

                // Escape closes and restores the full listing; it only has to
                // work while this field holds the keyboard. Enter keeps the
                // filter as it is — every match is already on screen.
                Keys.onPressed: (event) => {
                    if (event.key === Qt.Key_Escape) {
                        bar.closeRequested();
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

        // The count, in a reserved slot (§5.4). "no matches" is warn, not crit —
        // a query with nothing behind it yet is not an error; "…" is the first
        // pass over a directory of gens still reading their metadata.
        Item {
            width: 90
            height: parent.height
            PixelText {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                text: bar.countLabel
                color: bar.busy ? Theme.dim
                     : bar.count > 0 ? bar.fgText : Theme.warn
            }
        }

        // Closes exactly as Escape does — the bar carries its own way out, since
        // the titlebar cell that opened it is a column away (§10.1).
        Rectangle {
            width: 22
            height: parent.height
            color: closeArea.containsMouse ? Theme.bgAlt : "transparent"
            radius: Theme.rounding
            border.width: closeArea.containsMouse ? Theme.ctrlBorder : 0
            border.color: bar.fgAccent
            PixelText {
                anchors.centerIn: parent
                text: "x"
                color: closeArea.containsMouse ? bar.fgAccent : Theme.dim
            }
            MouseArea {
                id: closeArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: bar.closeRequested()
            }
        }
    }
}

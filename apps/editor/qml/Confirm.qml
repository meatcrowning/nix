import QtQuick

// The unsaved-changes guard, and the only modal this app has.
//
// It exists because of one rule and is shaped by two others:
//
//  * **Never silently clobber** (docs/DESIGN.md §10.2). Closing a document with
//    unsaved edits, and reloading one that changed on disk while you were
//    editing it, are both "the user is about to lose typing" — so both come
//    through here.
//  * **A destructive answer is a deliberate act** (§10.3), so `discard` is drawn
//    in `crit` and is never the default the keyboard lands on. Escape is always
//    cancel.
//  * A modal **dims everything under it** (§7.5). This one is in-window rather
//    than a second toplevel: it belongs to the document it is about, an
//    application-modal window would be wrong for a per-tab question, and hyprvtb
//    would give a second toplevel a titlebar full of cells this dialog must not
//    have.
Item {
    id: root
    visible: false
    z: 4000

    property string message: ""
    property string detail: ""
    property string acceptLabel: "save"
    property string discardLabel: "discard"
    property bool showDiscard: true
    property bool winActive: true

    signal accepted()
    signal discarded()
    signal cancelled()

    // The three answers are FUNCTIONS as well as signals: the buttons call these,
    // and so does the offscreen harness — a QML signal cannot be invoked from
    // Python, so a guard tested only through its buttons is a guard nothing can
    // test at all.
    function chooseAccept()  { close(); root.accepted(); }
    function chooseDiscard() { close(); root.discarded(); }
    function chooseCancel()  { close(); root.cancelled(); }

    function ask(msg, det, acc, disc) {
        message = msg;
        detail = det || "";
        acceptLabel = acc || "save";
        discardLabel = disc || "discard";
        visible = true;
        sink.forceActiveFocus();
    }

    function close() { visible = false; }

    // the scrim: dims the window and swallows every click that is not the
    // dialog's own
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.55)
        MouseArea { anchors.fill: parent }
    }

    Item {
        id: sink
        focus: root.visible
        Keys.onPressed: (e) => {
            if (e.key === Qt.Key_Escape) {
                root.chooseCancel(); e.accepted = true;
            } else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                root.chooseAccept(); e.accepted = true;
            }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(root.width - 40, Math.max(body.implicitWidth, det.implicitWidth,
                                                  buttons.implicitWidth) + 32)
        height: body.implicitHeight + (root.detail !== "" ? det.implicitHeight + 6 : 0)
                + buttons.height + 32
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.windowBorderWidth
        border.color: root.winActive ? Theme.windowBorder : Theme.windowBorderInactive

        PixelText {
            id: body
            anchors { top: parent.top; topMargin: 12
                      left: parent.left; leftMargin: 16; right: parent.right
                      rightMargin: 16 }
            wrapMode: Text.Wrap
            text: root.message
            color: Theme.text
        }

        PixelText {
            id: det
            anchors { top: body.bottom; topMargin: 6
                      left: parent.left; leftMargin: 16; right: parent.right
                      rightMargin: 16 }
            visible: root.detail !== ""
            wrapMode: Text.Wrap
            elide: Text.ElideMiddle
            text: root.detail
            color: Theme.textDim
        }

        Row {
            id: buttons
            anchors { bottom: parent.bottom; bottomMargin: 12
                      right: parent.right; rightMargin: 16 }
            spacing: 8

            EdButton {
                label: "cancel"
                winActive: root.winActive
                onClicked: root.chooseCancel()
            }
            EdButton {
                label: root.discardLabel
                visible: root.showDiscard
                danger: true
                winActive: root.winActive
                onClicked: root.chooseDiscard()
            }
            EdButton {
                label: root.acceptLabel
                winActive: root.winActive
                onClicked: root.chooseAccept()
            }
        }
    }
}

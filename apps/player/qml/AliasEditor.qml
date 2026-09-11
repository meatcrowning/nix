import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

// "SAME PERSON AS…" — the editor for an artist identity (main.py's
// `artistalias`). Daniel Lopatin's records are tagged Oneohtrix Point Never,
// Chuck Person, Games and his own name, and every one of those tags is right:
// this is where he says they are one person, after which typing any of the
// names finds all of the work.
//
// It changes MATCHING only. Nothing is retagged, nothing is merged, and the
// gallery still files each record under the name it was released as — so the
// worst a wrong entry can do is widen a search, and removing it undoes that.
//
// The shape is the rule editor's (SmartEditor.qml): docs/DESIGN.md §7.2/§7.5 —
// 0.5 black scrim, click-outside cancels, a SheetFrame box with 12px margins,
// a right-aligned button row, and the live count in the footer as the honest
// readout that the identity does something (§10.1).
Item {
    id: root
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    signal saved(string artist)

    visible: false

    // Plasma's controls are taller than the pixel face's 24px rows and crop the
    // frame they draw if pinned to it; `ctrlH` is 0 outside a Plasma session,
    // so every Math.max(24, ctrlH) below is exactly 24 there (SmartEditor.qml).
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    readonly property int ctrlH: root.plasma ? hProbe.implicitHeight : 0
    EditField { id: hProbe; visible: false }

    // ---- working copy: the store never sees a keystroke, so cancel is free.
    property string artist: ""
    property var names: []
    property int matchCount: 0

    function edit(name) {
        name = (name || "").trim();
        if (name === "")
            return;                       // an untagged row names nobody
        artist = name;
        names = Library.artistAliases(name);   // themselves when unclaimed
        visible = true;
        recount();
        forceActiveFocus();
    }

    function cancel() { visible = false; }

    function save() {
        // One name is not an identity; main.py reads that as "dissolve the
        // group", which is exactly what clearing the rows here should mean.
        Library.setArtistAliases(artist, names);
        visible = false;
        root.saved(artist);
    }

    // ---- name edits. `names` is reassigned only when a ROW appears or goes
    // (that is what rebuilds the delegates); a keystroke mutates in place, or
    // the box being typed into loses the caret after its first character.
    function setName(i, text) {
        names[i] = text;
        recount();
    }

    function addName() {
        var n = names.slice();
        n.push("");
        names = n;
    }

    function removeName(i) {
        var n = names.slice();
        n.splice(i, 1);
        names = n;
        recount();
    }

    function recount() { debounce.restart(); }

    Timer {
        id: debounce
        interval: 160
        onTriggered: root.matchCount = Library.artistAliasCount(root.names)
    }

    Motion { id: motion }

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.5)
        MouseArea { anchors.fill: parent; onClicked: root.cancel() }
    }

    SheetFrame {
        id: box
        anchors.centerIn: parent
        width: Math.min(380, root.width - 16)
        height: Math.min(head.height + body.contentHeight + foot.height + 24,
                         root.height - 16)

        MouseArea { anchors.fill: parent }   // swallow: not an outside click

        readonly property int inner: width - 24

        Item {
            id: head
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
            height: Math.max(20, root.ctrlH)
            PixelText {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 28
                elide: Text.ElideRight
                text: "same person as " + root.artist
                color: root.fgAccent
            }
            HeaderButton {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                label: "x"
                iconName: "window-close"; iconOnly: true
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.cancel()
            }
        }

        Rectangle {
            id: headRule
            anchors { top: head.bottom; topMargin: 8; left: parent.left; right: parent.right }
            anchors.leftMargin: 1; anchors.rightMargin: 1
            height: 1
            color: Theme.border
        }

        KineticFlickable {
            id: body
            anchors { top: headRule.bottom; bottom: footRule.top;
                      left: parent.left; right: parent.right; margins: 12 }
            clip: true
            contentHeight: col.implicitHeight
            ScrollBar.vertical: VScroll { visible: body.contentHeight > body.height }

            Column {
                id: col
                width: box.inner
                spacing: 8

                PixelText {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "every name this person releases under:"
                    color: root.fgDim
                }

                Repeater {
                    model: root.names

                    delegate: Item {
                        id: nameRow
                        required property int index
                        required property var modelData

                        width: col.width
                        height: Math.max(24, root.ctrlH)

                        EditField {
                            anchors.left: parent.left
                            anchors.right: drop.left
                            anchors.rightMargin: 4
                            anchors.verticalCenter: parent.verticalCenter
                            placeholderText: "another name"
                            maximumLength: 120
                            fgText: root.fgText; fgAccent: root.fgAccent
                            text: nameRow.modelData
                            onTextEdited: root.setName(nameRow.index, text)
                            onEscaped: root.cancel()
                            onAccepted: root.save()
                        }
                        HeaderButton {
                            id: drop
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            label: "x"
                            iconName: "list-remove"; iconOnly: true
                            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                            onClicked: root.removeName(nameRow.index)
                        }
                    }
                }

                HeaderButton {
                    label: "+ name"
                    plainLabel: "add name"; iconName: "list-add"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.addName()
                }
            }
        }

        Rectangle {
            id: footRule
            anchors { bottom: foot.top; bottomMargin: 8; left: parent.left; right: parent.right }
            anchors.leftMargin: 1; anchors.rightMargin: 1
            height: 1
            color: Theme.border
        }

        Item {
            id: foot
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right; margins: 12 }
            height: Math.max(20, root.ctrlH)
            PixelText {
                anchors.verticalCenter: parent.verticalCenter
                text: root.matchCount === 1 ? "1 track" : root.matchCount + " tracks"
                color: root.matchCount > 0 ? root.fgDim : Theme.dim
            }
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                HeaderButton {
                    label: "cancel"
                    iconName: "dialog-cancel"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.cancel()
                }
                HeaderButton {
                    label: "save"
                    iconName: "document-save"
                    lit: true
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.save()
                }
            }
        }
    }

    Keys.onEscapePressed: root.cancel()
}

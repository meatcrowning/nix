import QtQuick

// The bottom bar of `filer --pick` (the FileChooser portal backend's UI — see
// ../pick.py). Not instantiated in an ordinary filer window: Main.qml gives it
// zero height and `visible: false` when Picker.active is false, so the browser
// is byte-for-byte the window it always was.
//
// Deliberately not a dialog overlay like BrowserPrompt: the whole window IS the
// dialog here, so the bar is chrome along the bottom and every normal
// navigation gesture (expand, sort, the titlebar address bar, the preview grid)
// stays live above it.
Item {
    id: root

    // the paths currently chosen, already narrowed to what this mode accepts
    property var picked: []
    // the directory being viewed — the answer in `dir` mode when nothing is
    // explicitly selected, which is how every other file chooser behaves
    property string currentDir: ""
    property bool winActive: true

    // THE NAME BOX IS EDITABLE, so an answer can be typed or pasted as well as
    // clicked — a path from somewhere else is the whole reason a file dialog
    // has a name box at all. Clicking in the view keeps writing the name here
    // (`syncFromPicked`), and typing takes over from that moment (`typed`)
    // until the selection changes again. `Picker.resolvePath` decides where the
    // text points, in python; nothing about a path is worked out in QML.
    property bool typed: false
    // What is in the box, and a way to put the keyboard in it. Both are the
    // component's public surface (tools/pick-test.py drives it through them).
    property alias nameText: nameField.text
    function focusName() { nameField.forceActiveFocus(); nameField.selectAll(); }
    // Save-as is ALWAYS driven by the box — the name is the answer there, typed
    // or filled in by clicking a file to overwrite.
    readonly property bool boxDrives: typed || Picker.saving
    readonly property string typedPath: boxDrives ? Picker.resolvePath(nameField.text, currentDir) : ""
    readonly property string typedKind: boxDrives ? Picker.kindOf(typedPath) : "missing"
    // A typed folder in a file dialog is somewhere to GO, not the answer — the
    // same as double-clicking it. In `dir` mode it IS the answer.
    readonly property bool typedIsTravel: boxDrives && typedKind === "dir" && Picker.mode !== "dir"

    // What accept would return. A single-selection request gets one path even
    // if the tree has several selected (ctrl-click is always available), so the
    // box never promises more than the app will receive.
    readonly property var answer: {
        // SAVE-AS: the answer is the name in the box, and the file it names is
        // not supposed to exist yet — the only mode where "missing" is fine.
        // Its folder still has to be real, or the app is handed a path it
        // cannot write (Picker.accept drops one).
        if (Picker.saving) {
            if (typedIsTravel) return [];
            return (typedPath !== "" && typedKind !== "dir"
                    && Picker.writable(typedPath)) ? [typedPath] : [];
        }
        if (typed) {
            return (typedPath !== "" && !typedIsTravel
                    && Picker.selectable(typedPath) && typedKind !== "missing")
                   ? [typedPath] : [];
        }
        if (picked.length > 0) return Picker.multiple ? picked : [picked[0]];
        if (Picker.mode === "dir" && currentDir) return [currentDir];
        return [];
    }
    readonly property bool canAccept: answer.length > 0 || typedIsTravel
    // Saving over something is a decision, so it is asked rather than done.
    readonly property bool willOverwrite: Picker.saving && answer.length > 0
                                          && Picker.kindOf(answer[0]) === "file"

    signal accepted()
    signal cancelled()
    signal navigate(string dir)             // a typed folder: go there instead
    signal confirmOverwrite(string path)    // save-as onto an existing file

    function submit() {
        // Travel first: Enter on a typed folder opens it and hands the box back
        // to the selection, which is what every other file dialog does.
        if (typedIsTravel) {
            const dst = typedPath;
            root.navigate(dst);
            return;
        }
        if (!canAccept) return;
        // Never overwrite on the strength of a button press alone; the answer
        // is written only after the dialog comes back (BrowserPane wires it).
        if (willOverwrite) { root.confirmOverwrite(answer[0]); return; }
        doAccept();
    }
    function doAccept() {
        if (answer.length === 0) return;
        Picker.accept(answer);
        root.accepted();
    }

    // The selection is what the box shows until the user types over it. Set
    // imperatively behind a flag rather than bound: a TextInput cannot be both
    // bound and editable, and a two-way binding on one is a loop (painter's
    // PromptBox learned the same thing).
    property bool syncing: false
    function syncFromPicked() {
        syncing = true;
        nameField.text = picked.length > 1 ? (picked.length + " items")
                       : picked.length === 1 ? baseName(picked[0]) : "";
        syncing = false;
        typed = false;
    }
    function baseName(p) {
        const q = String(p).replace(/\/+$/, "");
        const i = q.lastIndexOf("/");
        return i >= 0 ? q.substring(i + 1) : q;
    }
    onPickedChanged: syncFromPicked()
    // Navigating away is a new context: a name typed for the old folder must
    // not silently point somewhere else now.
    onCurrentDirChanged: syncFromPicked()

    // The name the asking app suggested (spec `current_name`), which is the one
    // case where the box starts with something the user did not choose.
    Component.onCompleted: if (Picker.currentName !== "") {
        nameField.text = Picker.currentName;
        typed = true;
    }

    implicitHeight: Theme.lineHeight * 2 + 14

    Rectangle {
        anchors.fill: parent
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: 1

        // What will be returned, and where you type one instead: the name when
        // it is one thing, the count when it is a multi-selection, and a full
        // path the moment you type or paste one.
        Rectangle {
            id: nameBox
            anchors {
                left: parent.left; leftMargin: 10
                right: filterBox.left; rightMargin: 10
                verticalCenter: parent.verticalCenter
            }
            height: Theme.lineHeight + 10
            color: Theme.bg
            border.width: 1
            // Says whether what is in it is an answer — the accept button is
            // greyed for the same reason, but the box is where the eye is.
            border.color: !root.winActive ? Theme.inactive
                          : nameField.activeFocus ? Theme.accent
                          : (root.typed && !root.canAccept) ? Theme.crit
                          : Theme.border

            TextInput {
                id: nameField
                anchors { fill: parent; leftMargin: 6; rightMargin: 6 }
                verticalAlignment: TextInput.AlignVCenter
                clip: true
                color: !root.winActive ? Theme.inactive
                       : (root.typed && !root.canAccept) ? Theme.crit
                       : root.canAccept ? Theme.text : Theme.textDim
                font.family: Theme.font
                font.pixelSize: Theme.fontSize
                renderType: Text.NativeRendering
                selectByMouse: true
                selectionColor: Theme.accent
                selectedTextColor: Theme.bg
                // A menu row acts on the selection as it stood at the
                // right-click, and a TextInput drops it on losing focus
                // (apps/AGENTS.md, CtxMenu).
                persistentSelection: true
                onTextEdited: root.typed = true
                // Enter is the window's Shortcut (BrowserPane), so it reaches
                // submit() whether or not this box has the keyboard.
            }

            // With nothing chosen and nothing typed, say what is being ASKED —
            // this is the only place the requesting app's prompt is shown (the
            // window title is the address bar).
            PixelText {
                anchors { left: parent.left; leftMargin: 6; right: parent.right
                          rightMargin: 6; verticalCenter: parent.verticalCenter }
                visible: nameField.text === ""
                elide: Text.ElideMiddle
                text: Picker.title
                color: !root.winActive ? Theme.inactive : Theme.dim
            }
        }

        // filter chooser: only when the app offered more than one. Cycles on
        // click rather than opening a popup — there is rarely more than a
        // handful, and a popup here would fight the context-menu layer.
        PixelText {
            id: filterBox
            visible: Picker.filterNames.length > 1
            anchors { right: cancelBtn.left; rightMargin: 14; verticalCenter: parent.verticalCenter }
            text: visible ? "[" + Picker.filterName + "]" : ""
            color: !root.winActive ? Theme.inactive
                   : (filterMa.containsMouse ? Theme.accent : Theme.textDim)
            MouseArea {
                id: filterMa
                anchors.fill: parent
                anchors.margins: -4
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    const names = Picker.filterNames;
                    const i = names.indexOf(Picker.filterName);
                    Picker.setFilter(names[(i + 1) % names.length]);
                }
            }
        }

        component BarButton: Rectangle {
            id: btn
            property string label: ""
            property bool enabled: true
            property bool danger: false
            signal clicked()
            width: btnText.implicitWidth + 22
            height: Theme.lineHeight + 10
            color: ma.containsMouse && btn.enabled ? Theme.highlight : "transparent"
            border.width: 1
            border.color: !root.winActive ? Theme.inactive
                          : !btn.enabled ? Theme.border
                          : (btn.danger ? Theme.border : Theme.accent)
            PixelText {
                id: btnText
                anchors.centerIn: parent
                text: btn.label
                color: !root.winActive ? Theme.inactive
                       : !btn.enabled ? Theme.border
                       : (btn.danger ? Theme.textDim : Theme.accent)
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                enabled: btn.enabled
                cursorShape: Qt.PointingHandCursor
                onClicked: btn.clicked()
            }
        }

        BarButton {
            id: cancelBtn
            anchors { right: acceptBtn.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
            label: "cancel"
            danger: true
            onClicked: { Picker.cancel(); root.cancelled(); }
        }
        BarButton {
            id: acceptBtn
            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
            label: Picker.acceptLabel
            enabled: root.canAccept
            onClicked: root.submit()
        }
    }
}

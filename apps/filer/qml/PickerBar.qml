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

    // What accept would return. A single-selection request gets one path even
    // if the tree has several selected (ctrl-click is always available), so the
    // summary never promises more than the app will receive.
    readonly property var answer: {
        if (picked.length > 0) return Picker.multiple ? picked : [picked[0]];
        if (Picker.mode === "dir" && currentDir) return [currentDir];
        return [];
    }
    readonly property bool canAccept: answer.length > 0

    signal accepted()
    signal cancelled()

    function submit() { if (canAccept) { Picker.accept(answer); root.accepted(); } }

    implicitHeight: Theme.fontSize * 2 + 14

    Rectangle {
        anchors.fill: parent
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: 1

        // what will be returned, so the choice is never ambiguous — the count
        // when it is a multi-selection, the name when it is one thing.
        PixelText {
            id: summary
            anchors {
                left: parent.left; leftMargin: 10
                right: filterBox.left; rightMargin: 10
                verticalCenter: parent.verticalCenter
            }
            elide: Text.ElideMiddle
            color: !root.winActive ? Theme.inactive
                   : (root.canAccept ? Theme.text : Theme.textDim)
            text: {
                const a = root.answer;
                // With nothing chosen, say what is being ASKED — it is the only
                // place the requesting app's prompt is shown (the window title
                // is the address bar).
                if (a.length === 0) return Picker.title;
                if (a.length === 1) {
                    const q = a[0].replace(/\/+$/, "");
                    const i = q.lastIndexOf("/");
                    return i >= 0 ? q.substring(i + 1) : q;
                }
                return a.length + " items";
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
            height: Theme.fontSize + 10
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

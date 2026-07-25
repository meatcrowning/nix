import QtQuick
import QtWebEngine

// The file picker a page's <input type=file> (or upload button) pops.
//
// Same story as JsDialog: with no onFileDialogRequested handler the QML
// WebEngineView auto-rejects, so the picker never opens at all — the click
// registers, onchange never fires, and the page looks broken. Rather than pull
// in QtQuick.Dialogs' FileDialog (an unthemed GTK/portal window over a pixel-
// font browser) this is a small themed browser over the Files bridge, in the
// same shape as filer's list.
//
// Handles all four modes Chromium asks for: one file, many files, a folder
// (webkitdirectory), and save-as. The request is held while the picker is up
// and answered with dialogAccept(paths) / dialogReject().
Item {
    id: root
    visible: false
    z: 2700

    property var pending: null
    property string dir: ""
    property var entries: []
    property var selected: []          // absolute paths, in click order
    property bool showHidden: false
    property int mode: FileDialogRequest.FileModeOpen

    readonly property bool multi:  mode === FileDialogRequest.FileModeOpenMultiple
    readonly property bool folder: mode === FileDialogRequest.FileModeUploadFolder
    readonly property bool saving: mode === FileDialogRequest.FileModeSave

    function show(request) {
        request.accepted = true;       // "we'll handle it" — suppresses the auto-reject
        // Only one picker at a time: a page can't open a second while the first
        // blocks, and a second tab's request would fight over this one panel.
        if (pending) { request.dialogReject(); return; }
        pending = request;
        mode = request.mode;
        selected = [];
        nameField.text = (request.defaultFileName && !folder) ? request.defaultFileName : "";
        cd(Files.startDir());
        root.visible = true;
        keySink.forceActiveFocus();
    }

    function cd(path) {
        if (!Files.isDir(path)) return;
        dir = path;
        selected = [];
        refresh();
        list.currentIndex = -1;
        list.positionViewAtBeginning();
    }
    function up() { cd(Files.parentOf(dir)); }

    // Dirs first, then files, both case-insensitively by name — the ordering a
    // file list is read in, not scandir's arbitrary one.
    function refresh() {
        var all = Files.listDir(dir).filter(function(e) {
            if (e.hidden && !root.showHidden) return false;
            return folder ? e.isDir : true;   // folder mode lists only folders
        });
        all.sort(function(a, b) {
            if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
            return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1;
        });
        entries = all;
    }

    function isSelected(path) { return selected.indexOf(path) !== -1; }

    function pick(entry) {
        if (entry.isDir && !folder) { cd(entry.path); return; }
        if (multi) {
            var s = selected.slice();
            var i = s.indexOf(entry.path);
            if (i === -1) s.push(entry.path); else s.splice(i, 1);
            selected = s;
        } else {
            selected = [entry.path];
            if (saving) nameField.text = entry.name;
        }
    }

    // The chosen paths for the current mode, or [] when the pick isn't valid yet.
    function result() {
        if (saving) {
            var n = nameField.text.trim();
            return n === "" ? [] : [Files.join(dir, n)];
        }
        // folder mode: an explicitly picked folder, else the one we're browsing
        if (folder) return selected.length > 0 ? [selected[0]] : [dir];
        return selected;
    }

    // try/catch for the same reason as JsDialog: the tab can be closed from the
    // titlebar while the picker is up, invalidating the held request — the
    // panel must still come down.
    function accept() {
        var paths = result();
        if (paths.length === 0) return;
        Files.rememberDir(dir);
        try { pending.dialogAccept(paths); } catch (e) {}
        pending = null;
        root.visible = false;
    }
    function cancel() {
        if (pending) { try { pending.dialogReject(); } catch (e) {} }
        pending = null;
        root.visible = false;
    }

    MouseArea { anchors.fill: parent; onClicked: root.cancel() }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.5) }

    Item {
        id: keySink
        Keys.onEscapePressed: root.cancel()
        Keys.onReturnPressed: root.accept()
        Keys.onEnterPressed: root.accept()
    }

    Rectangle {
        anchors.centerIn: parent
        // fits the 480px minimum window width, and never taller than the window
        width: Math.min(600, root.width - 40)
        height: Math.min(440, root.height - 60)
        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        MouseArea { anchors.fill: parent }   // swallow clicks inside the panel

        // Anchored, not a Column: the listing has to take exactly the space the
        // header and footer leave, and a Column can't express "fill the middle"
        // (a `parent.height - y` list would swallow the footer's rows).
        Column {
            id: header
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
            spacing: 8

            // what's being asked for, + up / hidden toggles
            Item {
                width: parent.width
                height: 22
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.saving ? "save as"
                        : root.folder ? "select a folder"
                        : root.multi  ? "select files"
                                      : "select a file"
                    color: Theme.accent
                }
                Row {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 6
                    BrowserButton {
                        label: root.showHidden ? "hidden: on" : "hidden: off"
                        onClicked: { root.showHidden = !root.showHidden; root.refresh(); }
                    }
                    BrowserButton { label: "up"; onClicked: root.up() }
                }
            }

            PixelText {
                width: parent.width
                elide: Text.ElideLeft      // keep the deepest part of the path visible
                text: root.dir
                color: Theme.textDim
            }
        }

        // the listing: fills whatever the header and footer leave
        Rectangle {
            anchors {
                top: header.bottom; topMargin: 8
                bottom: footer.top; bottomMargin: 8
                left: parent.left; leftMargin: 12
                right: parent.right; rightMargin: 12
            }
            color: Theme.bgAlt
            border.color: Theme.border
            border.width: 1

            ListView {
                id: list
                anchors { fill: parent; margins: 1 }
                clip: true
                model: root.entries
                boundsBehavior: Flickable.StopAtBounds

                delegate: Rectangle {
                    required property var modelData
                    width: list.width
                    height: Theme.fontSize + 4
                    color: root.isSelected(modelData.path) ? Theme.highlight
                         : rowMa.containsMouse ? Theme.bg : "transparent"

                    PixelText {
                        anchors {
                            left: parent.left; leftMargin: 8
                            right: sizeLabel.left; rightMargin: 8
                            verticalCenter: parent.verticalCenter
                        }
                        elide: Text.ElideRight
                        // trailing "/" marks a folder — cheaper to read than an icon
                        text: modelData.name + (modelData.isDir ? "/" : "")
                        color: root.isSelected(modelData.path) ? Theme.accent
                             : modelData.isDir ? Theme.text : Theme.textDim
                    }
                    PixelText {
                        id: sizeLabel
                        anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        text: modelData.isDir ? "" : root.humanSize(modelData.size)
                        color: Theme.dim
                    }

                    MouseArea {
                        id: rowMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.pick(modelData)
                        // double-click a file = pick it and go (dirs are
                        // entered on the first click already)
                        onDoubleClicked: if (!modelData.isDir) root.accept()
                    }
                }
            }

            PixelText {
                anchors.centerIn: parent
                visible: root.entries.length === 0
                text: root.folder ? "no folders here" : "empty"
                color: Theme.dim
            }
        }

        Column {
            id: footer
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right; margins: 12 }
            spacing: 8

            // save-as filename
            Rectangle {
                visible: root.saving
                width: parent.width
                height: 24
                color: Theme.bgAlt
                border.color: Theme.accent
                border.width: 1
                TextInput {
                    id: nameField
                    anchors { fill: parent; margins: 4 }
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font.family: Theme.font
                    font.pixelSize: Theme.fontSize
                    renderType: Text.NativeRendering
                    clip: true
                    onAccepted: root.accept()
                    Keys.onEscapePressed: root.cancel()
                }
            }

            Item {
                width: parent.width
                height: 22
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.multi && root.selected.length > 0 ? root.selected.length + " selected" : ""
                    color: Theme.textDim
                }
                Row {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 6
                    BrowserButton { label: "cancel"; onClicked: root.cancel() }
                    BrowserButton {
                        label: root.saving ? "save" : "open"
                        enabled: root.result().length > 0
                        onClicked: root.accept()
                    }
                }
            }
        }
    }

    function humanSize(n) {
        if (n < 1024) return n + "B";
        if (n < 1024 * 1024) return Math.round(n / 1024) + "K";
        if (n < 1024 * 1024 * 1024) return Math.round(n / (1024 * 1024)) + "M";
        return (n / (1024 * 1024 * 1024)).toFixed(1) + "G";
    }
}

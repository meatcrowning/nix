import QtQuick
import Quickshell
import Quickshell.Io
import Qt.labs.folderlistmodel

// A full-ish file manager in a REAL window (FloatingWindow), so the hyprvtb
// plugin gives it the same vertical titlebar / drag / edge-resize / minimize
// as every other window — no drawn-titlebar imitation. Themed to the bar.
//
// Navigation via FolderListModel; operations shell out (argv-spliced, never
// string-interpolated, so paths with spaces/metachars are safe): open
// (xdg-open), new folder (mkdir), rename (mv), delete-to-trash (gio trash)
// or permanent (rm -rf, confirmed), and copy/cut/paste (cp -a / mv).
FloatingWindow {
    id: win

    property int browserId: 0
    property string startPath: "/home/lam"

    title: "browse: " + view.dirName
    implicitWidth: 620
    implicitHeight: 460
    minimumSize: Qt.size(360, 260)

    onClosed: Browsers.close(browserId)

    Rectangle {
        id: view
        anchors.fill: parent
        color: Theme.bg

        property string path: win.startPath
        property string selected: ""        // absolute path of the selected row
        property bool selectedIsDir: false
        property var clip: null             // { op:"copy"|"cut", path }

        readonly property string dirName: {
            const p = path.replace(/\/+$/, "");
            const i = p.lastIndexOf("/");
            return i >= 0 ? (p.substring(i + 1) || "/") : p;
        }

        function toUrl(p) { return "file://" + encodeURI(p); }
        function fromUrl(u) { return decodeURIComponent(("" + u).replace("file://", "")); }
        function join(dir, name) { return dir.replace(/\/+$/, "") + "/" + name; }
        function parentOf(p) {
            const q = p.replace(/\/+$/, "");
            const i = q.lastIndexOf("/");
            return i > 0 ? q.substring(0, i) : "/";
        }

        function go(p) { path = p; selected = ""; }
        function refresh() { folder.folder = ""; folder.folder = toUrl(path); }

        FolderListModel {
            id: folder
            folder: view.toUrl(view.path)
            showDirsFirst: true
            showHidden: false
            sortField: FolderListModel.Name
        }

        // one-shot process runner for file ops; refresh + reselect on exit
        Process {
            id: op
            property string reselect: ""
            onExited: {
                view.refresh();
                if (reselect) { view.selected = reselect; reselect = ""; }
            }
        }
        function run(argv, reselect) {
            op.reselect = reselect || "";
            op.command = argv;
            op.running = true;
        }

        // ---- header: path + up ----
        Rectangle {
            id: header
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 30
            color: Theme.bgAlt
            border.color: Theme.border
            border.width: 1

            Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 8 }
                spacing: 8
                BrowserButton { label: "↑ up"; onClicked: view.go(view.parentOf(view.path)) }
            }
            PixelText {
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 70; rightMargin: 8 }
                text: view.path
                elide: Text.ElideMiddle
                color: Theme.text
            }
        }

        // ---- file list ----
        ListView {
            id: list
            anchors { top: header.bottom; left: parent.left; right: parent.right; bottom: toolbar.top; margins: 2 }
            clip: true
            model: folder
            boundsBehavior: Flickable.StopAtBounds

            delegate: Rectangle {
                required property int index
                required property string fileName
                required property string filePath
                required property bool fileIsDir
                required property int fileSize
                width: list.width
                height: 22
                readonly property string abs: view.fromUrl(filePath)
                color: view.selected === abs ? Theme.highlight : "transparent"

                Row {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 6; rightMargin: 6 }
                    spacing: 6
                    PixelText {
                        width: parent.width - szText.width - 6
                        elide: Text.ElideRight
                        text: (parent.parent.fileIsDir ? "[ ] " : "    ") + parent.parent.fileName
                        color: parent.parent.fileIsDir ? Theme.accent : Theme.text
                    }
                    PixelText {
                        id: szText
                        text: parent.parent.fileIsDir ? "" : view_sizeStr(parent.parent.fileSize)
                        color: Theme.textDim
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: { view.selected = parent.abs; view.selectedIsDir = parent.fileIsDir; }
                    onDoubleClicked: {
                        if (parent.fileIsDir) view.go(parent.abs);
                        else Quickshell.execDetached(["xdg-open", parent.abs]);
                    }
                }
            }
        }

        // integer byte size -> compact string (delegate helper)
        function view_sizeStr(b) {
            if (b < 1024) return b + "B";
            if (b < 1048576) return Math.round(b / 1024) + "K";
            if (b < 1073741824) return (b / 1048576).toFixed(1) + "M";
            return (b / 1073741824).toFixed(1) + "G";
        }

        // ---- toolbar: operations ----
        Rectangle {
            id: toolbar
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
            height: 32
            color: Theme.bgAlt
            border.color: Theme.border
            border.width: 1

            Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 8 }
                spacing: 6

                BrowserButton { label: "new"; onClicked: newDlg.open() }
                BrowserButton {
                    label: "rename"; enabled: view.selected !== ""
                    onClicked: { renameDlg.value = view.dirNameOf(view.selected); renameDlg.open(); }
                }
                BrowserButton {
                    label: "copy"; enabled: view.selected !== ""
                    onClicked: view.clip = { op: "copy", path: view.selected }
                }
                BrowserButton {
                    label: "cut"; enabled: view.selected !== ""
                    onClicked: view.clip = { op: "cut", path: view.selected }
                }
                BrowserButton {
                    label: "paste"; enabled: view.clip !== null
                    onClicked: {
                        const src = view.clip.path;
                        const dst = view.join(view.path, view.dirNameOf(src));
                        if (view.clip.op === "copy") view.run(["cp", "-a", "--", src, dst], dst);
                        else { view.run(["mv", "--", src, dst], dst); view.clip = null; }
                    }
                }
                BrowserButton {
                    label: "trash"; enabled: view.selected !== ""
                    onClicked: { view.run(["gio", "trash", "--", view.selected], ""); view.selected = ""; }
                }
                BrowserButton {
                    label: "delete"; danger: true; enabled: view.selected !== ""
                    onClicked: delDlg.open()
                }
            }
        }

        function dirNameOf(p) {
            const q = p.replace(/\/+$/, "");
            const i = q.lastIndexOf("/");
            return i >= 0 ? q.substring(i + 1) : q;
        }

        // ---- modal dialogs (simple centered prompts) ----
        BrowserPrompt {
            id: newDlg
            title: "new folder name"
            onAccepted: (t) => { if (t) view.run(["mkdir", "--", view.join(view.path, t)], view.join(view.path, t)); }
        }
        BrowserPrompt {
            id: renameDlg
            title: "rename to"
            onAccepted: (t) => {
                if (t) {
                    const dst = view.join(view.parentOf(view.selected), t);
                    view.run(["mv", "--", view.selected, dst], dst);
                }
            }
        }
        BrowserConfirm {
            id: delDlg
            text: "permanently delete?\n" + view.dirNameOf(view.selected)
            onConfirmed: { view.run(["rm", "-rf", "--", view.selected], ""); view.selected = ""; }
        }
    }
}

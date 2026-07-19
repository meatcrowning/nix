pragma Singleton
import Quickshell
import QtQuick

// Registry of open file-browser windows. shell.qml has a Repeater over
// `entries` that instantiates one FileBrowser (a real FloatingWindow) per
// entry. While any are open, Popups.diskPinned pins the disk panel behind
// them and shoves the other popups left.
Singleton {
    id: root

    property var entries: [] // [{id, path}]
    property int nextId: 1

    function open(path) {
        const id = nextId++;
        const e = entries.slice();
        e.push({ id: id, path: path });
        entries = e;
    }

    function close(id) {
        entries = entries.filter(e => e.id !== id);
    }
}

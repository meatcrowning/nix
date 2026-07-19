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
        Popups.diskPinned = true; // opening via a drive always pins
    }

    function close(id) {
        entries = entries.filter(e => e.id !== id);
        // only auto-unpin once the LAST browser closes; while others remain,
        // leave the pin as-is so a manual unpin isn't undone
        if (entries.length === 0)
            Popups.diskPinned = false;
    }
}

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Wallpaper picker: a vertical stack of previews from ~/Pictures/wall that
// slides out like the Launcher/Cheatsheet. Flipping through it with the arrow
// keys (or hovering with the mouse) *is* setting the wallpaper — each
// highlight change actually runs wal-set.sh on that image (debounced so key
// repeat doesn't hammer it), which tiles/scales exactly like every other
// wallpaper change in this config and regenerates the theme. There is no
// separate confirm step and no revert: whatever you land on stays when you
// close the picker. Single instance, like Launcher/Cheatsheet/PowerMenu.
PanelWindow {
    id: root

    property bool open: false

    // Stay mapped through the slide-out, then hide once off-screen — same
    // lifecycle as Launcher/Cheatsheet.
    visible: open || card.x < card.hidden - 1
    color: "transparent"

    anchors { top: true; bottom: true; right: true }
    margins { top: Theme.gap; bottom: Theme.gap; right: Theme.gap }
    implicitWidth: 260
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-wallpaper"
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    // Qt.resolvedUrl() resolves against this file's real path in a Singleton
    // (see SysInfo.qml) but returns a bogus "qrc:/qs-blackhole" placeholder
    // from inside a PanelWindow-rooted component, so paths here are resolved
    // via a shell's own $HOME expansion instead — same trick currentProc
    // below already uses to read ~/.cache/wal/current.
    readonly property string wallSetPath: "$HOME/.config/scripts/wal-set.sh"
    readonly property string listScriptPath: "$HOME/.config/quickshell/scripts/list-wallpapers.sh"

    property var images: []          // absolute paths, name-sorted
    property string currentPath: ""  // the wallpaper active when the picker opened
    property bool initializing: false
    // True once the user actually flipped to a different wallpaper this
    // session — opening and closing the picker without touching anything
    // must NOT re-apply the theme.
    property bool dirty: false

    function toFileUrl(p) {
        return "file://" + encodeURI(p);
    }
    function fileName(p) {
        const i = p.lastIndexOf("/");
        return i >= 0 ? p.substring(i + 1) : p;
    }

    // Re-scan the directory (picks up newly-added images) and re-read which
    // wallpaper is currently active, then (re)sync the selection to it.
    function refresh() {
        listProc.running = false;
        listProc.running = true;
        currentProc.running = false;
        currentProc.running = true;
    }

    function trySyncSelection() {
        if (images.length === 0) return;
        // Once the user has intentionally flipped, list.currentIndex is the
        // source of truth — do NOT let a late async refresh (the on-open
        // listProc/currentProc, or the 3s poll) yank the selection back to the
        // still-active wallpaper. That race is what made the first pick after
        // opening get discarded, so the theme only changed on the *second* pick.
        if (dirty) return;
        const idx = currentPath ? images.indexOf(currentPath) : -1;
        initializing = true;
        list.currentIndex = idx >= 0 ? idx : 0;
        initializing = false;
    }

    Process {
        id: listProc
        command: ["sh", "-c", root.listScriptPath]
        stdout: StdioCollector {
            onStreamFinished: {
                const next = this.text.split("\n").map(s => s.trim()).filter(s => s.length > 0);
                // Only reassign when the set actually changed: assigning a new
                // array (even an identical one) resets the ListView, which
                // clobbers currentIndex and would fire a spurious re-preview on
                // every 3s poll while browsing.
                if (next.length !== root.images.length || next.some((v, i) => v !== root.images[i]))
                    root.images = next;
                root.trySyncSelection();
            }
        }
    }

    Process {
        id: currentProc
        command: ["sh", "-c", "cat \"$HOME/.cache/wal/current\" 2>/dev/null"]
        stdout: StdioCollector {
            onStreamFinished: {
                root.currentPath = this.text.trim();
                root.trySyncSelection();
            }
        }
    }

    // Two-phase apply, forced by how Quickshell's hot-reload actually works:
    // wal-set.sh's full run rewrites Theme.qml in place, which Quickshell
    // sees as a config change and hot-reloads — but a reload destroys and
    // recreates the ENTIRE QML object tree from source (confirmed by
    // testing), so `root.open` itself resets to its default and the picker
    // window closes out from under you on every single flip. So while
    // flipping, only `previewProc` runs (--wallpaper-only: hyprpaper IPC,
    // no Theme.qml write, no reload, picker stays open, instant); the full
    // apply (theme/kitty/border) only runs once via `commitProc`, when the
    // picker actually closes, on whatever was last highlighted.
    //
    // previewProc runs at most one wal-set.sh at a time; a flip that lands
    // mid-run just overwrites pendingPath, and onExited immediately re-runs
    // with whatever the latest pick was — so rapid flipping always converges
    // on the last image instead of piling up overlapping runs.
    property string pendingPath: ""

    // wal-set.sh rewrites Theme.qml in place on every full apply, which
    // Quickshell sees as a config change and hot-reloads — normally
    // announced with a "config reloaded" toast (see shell.qml). That's the
    // right toast for an actual edit but not for a wallpaper change, so
    // commitPath() touches this marker just before running the full
    // wal-set.sh; shell.qml checks its freshness (not just existence, so a
    // stale marker from a crashed run doesn't suppress forever) before
    // deciding whether to toast. A plain in-memory flag can't do this job —
    // see the reload comment above, it wouldn't survive the very reload it's
    // meant to gate.
    readonly property string suppressMarker: "$HOME/.cache/wal/.suppress-reload"

    Process {
        id: previewProc
        onExited: {
            if (root.pendingPath) {
                const p = root.pendingPath;
                root.pendingPath = "";
                root.previewPath(p);
            }
        }
    }

    function previewPath(path) {
        if (previewProc.running) {
            pendingPath = path;
            return;
        }
        // "$1" via the sh -c argv-splice idiom, not string interpolation, so
        // a path can't smuggle in shell metacharacters.
        previewProc.command = ["sh", "-c",
            "exec \"" + root.wallSetPath + "\" --wallpaper-only \"$1\" >>\"$HOME/.cache/wal/wallpaper-picker.log\" 2>&1",
            "_", path];
        previewProc.running = true;
    }

    Process {
        id: commitProc
    }

    // Runs the full (theme-included) apply exactly once, on whatever's
    // currently highlighted — called when the picker closes, not per-flip.
    // A close with no flips is a no-op (see `dirty`).
    function commitFinal() {
        if (!dirty || commitProc.running) return;
        const item = list.currentItem;
        if (!item) return;
        commitProc.command = ["sh", "-c",
            "touch \"" + root.suppressMarker + "\"; exec \"" + root.wallSetPath + "\" \"$1\" >>\"$HOME/.cache/wal/wallpaper-picker.log\" 2>&1",
            "_", item.path];
        commitProc.running = true;
    }

    // Debounced so holding an arrow key doesn't queue a wal-set.sh per repeat.
    Timer {
        id: applyTimer
        interval: 90
        onTriggered: {
            const item = list.currentItem;
            if (!item) return;
            root.previewPath(item.path);
        }
    }

    // Poll for new files while open (FolderListModel-style live watching isn't
    // worth the extra dependency for a rarely-changing directory); a fresh
    // scan also happens on every open.
    Timer {
        interval: 3000
        running: root.open
        repeat: true
        onTriggered: root.refresh()
    }

    onOpenChanged: {
        if (open) {
            dirty = false;
            refresh();
            list.forceActiveFocus();
        } else {
            commitFinal();
        }
    }

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        readonly property real shown: 0
        readonly property real hidden: width
        x: root.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        PixelText {
            id: title
            anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
            text: "wallpaper"
            color: Theme.accent
        }

        ListView {
            id: list
            focus: true
            anchors {
                top: title.bottom; topMargin: 8
                left: parent.left; right: parent.right; bottom: parent.bottom
                margins: 10
            }
            clip: true
            spacing: 8
            model: root.images
            boundsBehavior: Flickable.StopAtBounds
            onCurrentIndexChanged: {
                positionViewAtIndex(currentIndex, ListView.Contain);
                if (!root.initializing) {
                    root.dirty = true;
                    applyTimer.restart();
                }
            }

            Keys.onDownPressed: currentIndex = Math.min(currentIndex + 1, count - 1)
            Keys.onUpPressed: currentIndex = Math.max(currentIndex - 1, 0)
            Keys.onEscapePressed: root.open = false
            Keys.onReturnPressed: root.open = false
            Keys.onEnterPressed: root.open = false

            delegate: Rectangle {
                id: delegateRoot
                required property string modelData
                required property int index
                readonly property string path: modelData

                width: list.width
                height: 130
                color: Theme.bgAlt
                radius: 0
                border.width: index === list.currentIndex ? 2 : 1
                border.color: index === list.currentIndex ? Theme.accent : Theme.border

                Image {
                    anchors.fill: parent
                    anchors.margins: delegateRoot.border.width + 2
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    clip: true
                    sourceSize.width: 240
                    sourceSize.height: 130
                    source: root.toFileUrl(delegateRoot.path)
                }

                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    anchors.margins: delegateRoot.border.width + 2
                    height: 18
                    color: Qt.rgba(0, 0, 0, 0.55)

                    PixelText {
                        anchors.centerIn: parent
                        width: parent.width - 8
                        elide: Text.ElideMiddle
                        horizontalAlignment: Text.AlignHCenter
                        text: root.fileName(delegateRoot.path)
                        color: Theme.text
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    // Click = pick it: select, apply the full theme, close.
                    // (Hover deliberately does NOT flip the selection — it
                    // caused accidental re-themes just from mousing past.)
                    onClicked: {
                        applyTimer.stop();
                        list.currentIndex = delegateRoot.index;
                        root.open = false;
                    }
                }
            }
        }
    }
}

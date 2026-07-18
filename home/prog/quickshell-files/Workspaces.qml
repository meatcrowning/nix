import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Widgets
import Quickshell.Hyprland

// Vertical list of workspace squares.
// Occupied / currently-viewed workspaces are bright; empty & unviewed are dimmed.
// The active-workspace highlight is a single box that SLIDES vertically between
// cells on a switch (up toward workspace 1, down toward the last), so the change
// reads as movement up and down the vertical stack — 1 on top, 2 below it, etc.
Item {
    id: root

    // Match the inner Column so this lays out like a plain Column did inside the
    // bar's top cluster.
    implicitWidth: col.implicitWidth
    implicitHeight: col.implicitHeight

    // workspace id -> class of its first window, and window count per workspace.
    // We parse `hyprctl clients -j` ourselves because this Hyprland build does
    // not advertise hyprland-toplevel-mapping-v1, so Quickshell cannot attach
    // IPC data to its Wayland toplevels and `lastIpcObject` (hence the window
    // class we need for the icon) comes back empty.
    property var wsClass: ({})
    property var wsCount: ({})

    // Ordered, visible workspaces (special / negative ids hidden), sorted by id
    // so the column always reads 1 (top) .. N (bottom). This is BOTH the repeater
    // model and the basis for the highlight's position, so the two never drift.
    // Only re-evaluates when workspaces are added/removed — not on a mere switch.
    readonly property var wsList: {
        const arr = (Hyprland.workspaces.values || []).filter(w => w.id > 0);
        arr.sort((a, b) => a.id - b.id);
        return arr;
    }

    // Visual index of the active workspace within wsList. Reads each workspace's
    // `active` flag, so a switch re-evaluates it and (via the handler below) the
    // persistent indicator animates to the new cell. May be -1 for a frame mid-
    // switch, while Hyprland is recreating/culling empty workspaces.
    readonly property int activeIndex: {
        for (let i = 0; i < wsList.length; i++)
            if (wsList[i].active) return i;
        return -1;
    }

    // The y the sliding highlight targets. Updated ONLY for a valid activeIndex,
    // held otherwise — so a transient -1 frame doesn't snap the box to the top
    // (y=0) and animate it back, which would look like a glitchy double-slide.
    // Kept as a plain (assignable) property, not a binding, for exactly that:
    // a binding would recompute to 0 on the -1 frame.
    property real activeY: 0
    property bool hasActive: false
    function syncActive() {
        if (activeIndex >= 0) {
            activeY = activeIndex * (Theme.wsCell + Theme.gap);
            hasActive = true;
        }
    }
    onActiveIndexChanged: syncActive()

    Process {
        id: clients
        command: ["hyprctl", "clients", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                const byClass = {};
                const count = {};
                try {
                    const arr = JSON.parse(this.text);
                    for (let i = 0; i < arr.length; i++) {
                        const c = arr[i];
                        if (!c.workspace) continue;
                        const id = c.workspace.id;
                        count[id] = (count[id] || 0) + 1;
                        if (byClass[id] === undefined && c.class)
                            byClass[id] = c.class;
                    }
                } catch (e) { /* ignore transient parse errors */ }
                root.wsClass = byClass;
                root.wsCount = count;
            }
        }
    }

    // Coalesce bursts of Hyprland events into a single rescan.
    Timer {
        id: debounce
        interval: 60
        onTriggered: clients.running = true
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) { debounce.restart(); }
    }
    Component.onCompleted: {
        clients.running = true;
        syncActive();   // place the highlight on the initially-active workspace
    }

    // The sliding active-workspace highlight, drawn behind the cells (which are
    // transparent, so it shows through). It animates its y between cells so a
    // workspace switch slides the box up or down the vertical stack. It is a
    // permanent child (never rebuilt with the model), so the Behavior always fires.
    //
    // Its border is the ACCENT colour, not the near-black `border` colour: this
    // box IS the thing that visibly moves, so it has to stand out against the
    // black bar. A dim box sliding on black animates perfectly but is invisible,
    // which is exactly why earlier versions read as "instant" — nothing you
    // could see was moving. A bright 2px outline gliding between cells is the
    // whole point, so make it bright.
    Rectangle {
        id: indicator
        x: 0
        y: root.activeY
        width: Theme.wsCell
        height: Theme.wsCell
        radius: 0
        color: Theme.bgAlt
        border.width: 2
        border.color: Theme.accent
        visible: root.hasActive
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }

    Column {
        id: col
        spacing: Theme.gap

        Repeater {
            model: root.wsList

            delegate: Rectangle {
                id: cell
                required property var modelData
                readonly property var ws: modelData
                readonly property bool viewed: ws.active
                readonly property string windowClass: root.wsClass[ws.id] || ""
                readonly property int windowCount: root.wsCount[ws.id] || 0
                readonly property bool occupied: windowCount > 0
                // resolve class -> desktop entry -> proper icon name
                readonly property var appEntry: windowClass !== ""
                    ? DesktopEntries.heuristicLookup(windowClass) : null
                readonly property string iconName: appEntry && appEntry.icon
                    ? appEntry.icon : windowClass

                width: Theme.wsCell
                height: Theme.wsCell
                radius: 0
                // The active box is the sliding `indicator` above; cells stay
                // transparent so it shows through.
                color: "transparent"
                opacity: (occupied || viewed) ? 1.0 : 0.4

                // App icon when something runs here; otherwise the workspace number.
                IconImage {
                    anchors.centerIn: parent
                    visible: cell.iconName !== ""
                    implicitSize: Theme.wsCell - 12
                    source: Quickshell.iconPath(cell.iconName, "application-x-executable")
                }
                PixelText {
                    anchors.centerIn: parent
                    visible: cell.iconName === ""
                    text: cell.ws.name
                    // Deliberately NOT brightened for the active workspace: the
                    // active cue is the sliding accent indicator, and an instant
                    // dim->accent flip on the number here would teleport the eye
                    // to the new cell, killing the sense of motion. Let the box
                    // slide; keep the number steady.
                    color: Theme.dim
                }

                MouseArea {
                    id: cellMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // This build drives Hyprland from Lua, so the classic
                    // "workspace N" dispatch string is rejected — go through the
                    // Lua focus dispatcher instead (matches hypr/hyprland.lua).
                    onClicked: Hyprland.dispatch("hl.dsp.focus({ workspace = " + cell.ws.id + " })")
                }

                Tooltip {
                    target: cell
                    visible: cellMouse.containsMouse
                    text: "Workspace " + cell.ws.name
                        + (cell.windowClass !== "" ? "\n" + cell.windowClass : "\n(empty)")
                        + (cell.windowCount > 1 ? " +" + (cell.windowCount - 1) : "")
                }
            }
        }
    }
}

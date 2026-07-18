pragma Singleton
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import QtQuick

// Single source of truth for the vertical per-window titlebars
// (WindowTitlebar.qml). Quickshell's own Hyprland toplevel tracking is
// unreliable on this build (same gap Workspaces.qml already works around —
// hyprland-toplevel-mapping-v1 isn't advertised), so this shells out to
// `hyprctl clients -j` for everything: geometry, title, address. Mirrors
// Workspaces.qml's debounced-Hyprland-event + Process/JSON pattern.
//
// Identity and geometry are deliberately split: `windows` is a sorted list
// of window ADDRESSES (stable values, so the Variants in shell.qml never
// destroys a titlebar just because its window moved — recreating the layer
// surface every poll is what caused the old blink/trail during drags), and
// `geometry` maps address -> {x, y, width, height, title}. A moving window
// only mutates `geometry`, which live titlebars follow through bindings.
//
// Hyprland emits no events during an interactive drag, so drag-follow is
// poll-based: a slow heartbeat, plus a fast poll that arms itself whenever a
// refresh actually saw something change and stops as soon as a poll comes
// back identical. Idle cost stays at 4 hyprctl calls/s; drags get ~20/s.
Singleton {
    id: root

    // The strip every titlebar occupies, and the buttons within it. Kept
    // equal to Theme.wsCell so buttons are perfectly square and the title
    // text below lines up flush with them.
    readonly property int titlebarWidth: Theme.wsCell

    // hypr/hyprland.lua's general.gaps_out — keep in sync if that changes.
    readonly property int gapOut: 35

    // Addresses of windows on the active workspace only — titlebars for
    // other workspaces' windows shouldn't render (they're not visible
    // either). Sorted so the list only changes when windows open/close.
    property var windows: []

    // address -> { x, y, width, height, title, floating }
    property var geometry: ({})

    // address -> {x, y, w, h} saved just before maximizing, so a second
    // toggleMaximize() click restores it. Presence of a key means "currently
    // maximized".
    property var maximizedState: ({})

    function _activeWorkspaceId() {
        const list = Hyprland.workspaces.values || [];
        for (let i = 0; i < list.length; i++) {
            if (list[i].active) return list[i].id;
        }
        return -1;
    }

    function _monitorSize() {
        const s = Quickshell.screens[0];
        return s ? { w: s.width, h: s.height } : { w: 1920, h: 1080 };
    }

    function refresh() {
        clientsProc.running = true;
    }

    Process {
        id: clientsProc
        command: ["hyprctl", "clients", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                let arr;
                try {
                    arr = JSON.parse(text);
                } catch (e) {
                    return;
                }
                const wsId = root._activeWorkspaceId();

                const addrs = [];
                const geo = {};
                for (let i = 0; i < arr.length; i++) {
                    const c = arr[i];
                    if (!c.workspace || c.workspace.id !== wsId) continue;
                    if (!c.at || !c.size) continue;
                    addrs.push(c.address);
                    geo[c.address] = {
                        x: c.at[0], y: c.at[1],
                        width: c.size[0], height: c.size[1],
                        title: c.title, floating: c.floating
                    };
                }
                addrs.sort();

                let changed = addrs.length !== root.windows.length;
                for (let i = 0; i < addrs.length && !changed; i++) {
                    const a = addrs[i];
                    const o = root.geometry[a], n = geo[a];
                    changed = a !== root.windows[i] || !o ||
                        o.x !== n.x || o.y !== n.y ||
                        o.width !== n.width || o.height !== n.height ||
                        o.title !== n.title;
                }
                if (!changed) return;

                // geometry before windows: a titlebar Variants is about to
                // create for a new address must already find its entry.
                root.geometry = geo;
                root.windows = addrs;
                fastPoll.restart();
            }
        }
    }

    Timer {
        id: debounce
        interval: 60
        onTriggered: root.refresh()
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) { debounce.restart(); }
    }

    // Slow heartbeat — catches whatever the event stream doesn't announce
    // (interactive drags emit no events at all).
    Timer {
        interval: 250
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    // Fast follow while something is actually moving: re-armed by every
    // refresh that saw a change, decays on the first one that didn't.
    Timer {
        id: fastPoll
        interval: 50
        onTriggered: root.refresh()
    }

    Component.onCompleted: refresh()

    function closeWindow(address) {
        Hyprland.dispatch("hl.dsp.window.close({ window = \"address:" + address + "\" })");
    }

    function toggleMaximize(address) {
        const saved = maximizedState[address];
        if (saved) {
            Hyprland.dispatch("hl.dsp.window.move({ window = \"address:" + address +
                "\", x = " + saved.x + ", y = " + saved.y + " })");
            Hyprland.dispatch("hl.dsp.window.resize({ window = \"address:" + address +
                "\", x = " + saved.w + ", y = " + saved.h + " })");
            const next = Object.assign({}, maximizedState);
            delete next[address];
            maximizedState = next;
        } else {
            const current = geometry[address];
            if (!current) return;

            const mon = _monitorSize();
            const targetX = gapOut;
            const targetY = gapOut;
            const targetW = mon.w - gapOut * 2 - Theme.barWidth - titlebarWidth;
            const targetH = mon.h - gapOut * 2;

            const next = Object.assign({}, maximizedState);
            next[address] = { x: current.x, y: current.y, w: current.width, h: current.height };
            maximizedState = next;

            Hyprland.dispatch("hl.dsp.window.move({ window = \"address:" + address +
                "\", x = " + targetX + ", y = " + targetY + " })");
            Hyprland.dispatch("hl.dsp.window.resize({ window = \"address:" + address +
                "\", x = " + targetW + ", y = " + targetH + " })");
        }
    }
}

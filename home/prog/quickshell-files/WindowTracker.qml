pragma Singleton
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import QtQuick

// Single source of truth for the vertical per-window titlebars
// (WindowTitlebar.qml).
//
// Identity and geometry are deliberately split: `windows` is a sorted list
// of window ADDRESSES (stable values, so the Variants in shell.qml never
// destroys a titlebar just because its window moved — recreating the layer
// surface every update is what caused the old blink/trail during drags),
// and `geometry` maps address -> {x, y, width, height, title, ...}. A
// moving window only mutates `geometry`, which live titlebars follow
// through bindings.
//
// Geometry is EVENT-DRIVEN, not polled: hypr/hyprland.lua runs an
// in-compositor ~60Hz diff (hl.timer) and emits a socket2 custom event
// ("tbgeom|<addr>,x,y,w,h,fhid;...") only when window geometry, stacking,
// or the active-workspace window set actually changed — Hyprland itself
// emits nothing during an interactive drag, so this Lua stream is what
// keeps titlebars glued to moving windows without spawning anything.
//
// Titles can't ride in that stream (arbitrary characters vs a line-based
// protocol), and Quickshell's own Hyprland toplevel tracking is unreliable
// on this build (same gap Workspaces.qml works around), so titles/floating
// still come from `hyprctl clients -j` — but only on the rare discrete
// socket2 events (openwindow / windowtitle / ...) plus a slow safety-net
// heartbeat, mirroring Workspaces.qml's debounced Process/JSON pattern.
//
// Layer-shell surfaces can't interleave with regular windows, so true
// z-order is impossible; instead each entry carries `intervals` — the
// y-ranges (titlebar-local px) of the strip NOT covered by any window
// above this one (stacking approximated by focusHistoryID, which tracks
// raise order for floating windows). TitlebarOverlay/WindowTitlebar render
// only inside those intervals, so a covering window visually clips the
// titlebar exactly where it overlaps, as if the titlebar sat beneath it.
// `focused` drives the active/inactive frame colour.
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
    // either). Sorted so the list only changes when the window set does.
    property var windows: []

    // address -> { x, y, width, height, title, floating, focused, fhid,
    //              intervals: [[y0, y1], ...] }
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

    function _sameIntervals(a, b) {
        if (!a || a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++)
            if (a[i][0] !== b[i][0] || a[i][1] !== b[i][1]) return false;
        return true;
    }

    // Occlusion + change detection + publish, shared by both sources.
    // `addrs` must be sorted; entries must carry x/y/width/height/title/
    // focused/fhid.
    function _publish(addrs, geo) {
        const mon = _monitorSize();
        const bw = Theme.windowBorderWidth;
        const tbMaxLeft = mon.w - Theme.barWidth - titlebarWidth;
        for (let i = 0; i < addrs.length; i++) {
            const g = geo[addrs[i]];
            const tx = Math.min(g.x + g.width, tbMaxLeft);
            const ty = g.y - bw, th = g.height + bw * 2;

            // y-ranges of the strip covered by windows above this one.
            // (A covering window is treated as spanning the strip's full
            // 32px width — partial-x overlap is a sliver case not worth a
            // 2D region decomposition.)
            const covered = [];
            for (let j = 0; j < addrs.length; j++) {
                if (j === i) continue;
                const o = geo[addrs[j]];
                if (o.fhid < g.fhid &&
                    o.x < tx + titlebarWidth && o.x + o.width > tx &&
                    o.y - bw < ty + th && o.y + o.height + bw > ty) {
                    covered.push([Math.max(0, o.y - bw - ty),
                                  Math.min(th, o.y + o.height + bw - ty)]);
                }
            }
            covered.sort((p, q) => p[0] - q[0]);

            // Complement of the merged covered ranges = visible intervals.
            const iv = [];
            let cursor = 0;
            for (let j = 0; j < covered.length; j++) {
                if (covered[j][0] > cursor) iv.push([cursor, covered[j][0]]);
                cursor = Math.max(cursor, covered[j][1]);
            }
            if (cursor < th) iv.push([cursor, th]);

            // Keep the previous array REFERENCE when nothing changed, so
            // the per-titlebar slice Repeater doesn't rebuild during plain
            // moves.
            const prev = geometry[addrs[i]];
            g.intervals = (prev && _sameIntervals(prev.intervals, iv))
                ? prev.intervals : iv;
        }

        let changed = addrs.length !== windows.length;
        for (let i = 0; i < addrs.length && !changed; i++) {
            const a = addrs[i];
            const o = geometry[a], n = geo[a];
            changed = a !== windows[i] || !o ||
                o.x !== n.x || o.y !== n.y ||
                o.width !== n.width || o.height !== n.height ||
                o.title !== n.title || o.focused !== n.focused ||
                o.intervals !== n.intervals;
        }
        if (!changed) return;

        // geometry before windows: a titlebar Variants is about to create
        // for a new address must already find its entry.
        geometry = geo;
        windows = addrs;
    }

    // The fast path: geometry pushed by the Lua timer in hyprland.lua.
    // Titles/floating are carried over from the last hyprctl refresh; a
    // brand-new address shows an empty title for the ~60ms until the
    // openwindow event's refresh fills it in.
    function _applyGeomEvent(payload) {
        const addrs = [];
        const geo = {};
        const parts = payload.length > 0 ? payload.split(";") : [];
        for (let i = 0; i < parts.length; i++) {
            const f = parts[i].split(",");
            if (f.length < 6) continue;
            const a = f[0];
            const prev = geometry[a];
            addrs.push(a);
            geo[a] = {
                x: +f[1], y: +f[2], width: +f[3], height: +f[4],
                fhid: +f[5], focused: +f[5] === 0,
                title: prev ? prev.title : "",
                floating: prev ? prev.floating : true
            };
        }
        _publish(addrs, geo);   // already address-sorted by the Lua side
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
                        title: c.title, floating: c.floating,
                        focused: c.focusHistoryID === 0,
                        fhid: c.focusHistoryID
                    };
                }
                addrs.sort();
                root._publish(addrs, geo);
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
        function onRawEvent(event) {
            if (event.name === "custom") {
                // Our own Lua geometry stream — consume directly, and don't
                // let it trigger hyprctl refreshes.
                if (event.data.indexOf("tbgeom|") === 0)
                    root._applyGeomEvent(event.data.substring(7));
                return;
            }
            debounce.restart();
        }
    }

    // Slow safety net only — geometry updates arrive via the Lua event
    // stream; this just re-syncs titles/floating if a discrete event was
    // somehow missed.
    Timer {
        interval: 2000
        running: true
        repeat: true
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

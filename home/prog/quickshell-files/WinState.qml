pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Hyprvtb's roll-up/minimize state is absent from the foreign-toplevel protocol,
// so this singleton joins that list by class/title with `hyprctl clients -j`.
// Rolled windows are hidden on the active workspace; minimized windows are
// visible but parked at the monitor's logical right edge. The join is
// intentionally fail-visible when titles are ambiguous.
//
// The same client poll identifies virtual outputs for sandbox windows. An
// output is physical when it has hardware identity (size, make, model, serial,
// or description); `HEADLESS-*` is corroboration only. A class/title is hidden
// only when every mapped client is virtual, so a real window is never removed
// from the taskbar because a matching test window exists elsewhere.
Singleton {
    id: root

    // "class\ntitle" -> "rolled" | "minimized". Windows in neither state are
    // absent, so a miss means "ordinary window", which is also the right answer
    // when the poll has not landed yet.
    property var byKey: ({})

    // "class\ntitle" -> "0x…", the Hyprland window address, for the SAME windows
    // byKey covers. It is filled in the same pass, so any key with a state also
    // has an address: hyprvtb's `rollup(address)` is the only way to act on a
    // window that is not the active one, and the toplevel list carries no
    // handle the compositor would recognise.
    property var addrByKey: ({})

    // "class\ntitle" -> true when every mapped window under that key is on a
    // NON-PHYSICAL output (the agents' sandbox monitor). Absent means "the user
    // can see this one", which is also the right answer before the first poll.
    property var offOutputByKey: ({})

    // Is a real fullscreen window up on a workspace the user is looking at?
    // Hyprland's `fullscreen` is 0 none / 1 maximized / 2 fullscreen, and only
    // 2 is the "something is playing, do not toast over it" case a maximized
    // editor is not. Notifications.qml reads it for auto-DND.
    property bool fullscreenShown: false

    function keyOf(appId, title) { return (appId || "") + "\n" + (title || ""); }
    // Reading root.byKey inside the call is what registers the binding
    // dependency, so cells recolour when a poll changes something.
    function stateOf(appId, title) { return root.byKey[keyOf(appId, title)] || ""; }
    function addrOf(appId, title) { return root.addrByKey[keyOf(appId, title)] || ""; }
    // Is this toplevel on a monitor the user cannot see? Anything that draws or
    // acts on the toplevel list must ask — see the OUTPUTS block above.
    function offOutput(appId, title) { return !!root.offOutputByKey[keyOf(appId, title)]; }

    // Does this Quickshell screen belong to a physical output? The same question
    // as offOutput(), asked of a `Quickshell.screens` entry instead of a window —
    // which is what a per-monitor widget has to hand. ShellScreen carries only
    // `name`, `model` and `serialNumber` of the identity above (measured: DP-5
    // model "DELL P2422HE", HEADLESS-6 model ""), so this is the same rule on a
    // thinner slice, and it is SYNCHRONOUS: it must never wait on the poll, or
    // anything gated on it would be absent for the first frames of every reload.
    function screenIsVirtual(s) {
        if (!s) return false;
        return (String(s.name || "").indexOf("HEADLESS-") === 0)
            || (String(s.model || "") === "" && String(s.serialNumber || "") === "");
    }

    // A refresh asked for while one is in flight is REMEMBERED, not dropped.
    // Dropping it was why the notch's seam "only sometimes" kept up: a maximize
    // fires several compositor events in a burst, the first one starts the
    // hyprctl call, and every later one — including the one that carried the
    // state we actually needed — hit a running process and returned silently.
    // The panel then showed the previous world until the 1s tick.
    property bool _pending: false
    function refresh() {
        if (clientsProc.running) {
            root._pending = true;
            return;
        }
        clientsProc.running = true;
    }
    // Re-runs a coalesced request as soon as the last call is off the wire. A
    // Timer rather than a direct restart inside onRunningChanged: re-entering a
    // property's own change handler is a good way to lose the second edge, and
    // 30ms also rate-limits a burst into one extra call.
    Timer {
        id: pendingKick
        interval: 30
        onTriggered: if (root._pending) {
            root._pending = false;
            root.refresh();
        }
    }

    // 1s: fast enough that a roll-up recolours its icon while you are still
    // looking at it, cheap enough (~4ms of hyprctl) to leave running. Windows
    // are the only reason the taskbar exists, so this idles when there are none.
    Timer {
        interval: 1000
        repeat: true
        running: {
            const t = ToplevelManager.toplevels;
            const v = t ? t.values : null;
            return !!(v && v.length > 0);
        }
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    // Minimizing hands focus to another window and restoring takes it back, so
    // a focus change is very often the same event we are polling for — sample
    // immediately instead of up to a second later.
    Connections {
        target: ToplevelManager
        function onActiveToplevelChanged() { root.refresh() }
    }

    // A window APPEARING is the other event worth sampling immediately, and it
    // is the one the off-output filter rides on: a sandbox window is in the
    // toplevel list — and therefore in the taskbar — from its first frame, and
    // waiting up to a second for the next tick to hide it is a second of an
    // agent's test window on the user's bar.
    Connections {
        target: ToplevelManager.toplevels
        function onValuesChanged() { root.refresh() }
    }

    // Monitors and clients in ONE spawn: the minimized test needs the monitor's
    // logical geometry, and two hyprctl processes a second to answer one
    // question is one too many. `hyprctl -j` emits a bare array for each, so
    // they are separated by a sentinel rather than being expected to combine.
    // Every mapped window's FRAME — the outer edge a person sees, decorations
    // and border included. `hyprctl clients` reports the CONTENT box; hyprvtb's
    // titlebar column (two cells of plugin:hyprvtb:bar_width) hangs off ONE edge
    // — the one plugin:hyprvtb:titlebar_edge names (right/left/top/bottom) — and
    // Hyprland's own border outside that. So the edge carrying the titlebar is
    // content ± (2*barWidth + border) and the other three are content ± border.
    // Measured, not assumed: with the titlebar on the right, a window Hyprland
    // had laid flush against the panel's reserved area read content-right 2252,
    // border at 2316 — 64px of chrome, = 2*31 + 2. Reading the edge from the
    // plugin (not hardcoding "right") is what stopped the notch's flush test
    // firing at a window 64px away when the bar is on the right but the titlebar
    // hangs off the bottom.
    //
    // Published for whatever the panel draws AGAINST a window: the notch's seam
    // (NotchSeam.qml) is the first, and it is the reason the monitor name is
    // carried rather than the id (a per-monitor widget holds a ShellScreen).
    property var frames: []

    // ---- the world, split in two -----------------------------------------
    // MONITORS and the plugin's bar width change when hardware or config does;
    // CLIENTS change whenever a window so much as moves. They used to be read
    // and parsed together, once a second, which set the pace of everything that
    // watches a window — and hyprvtb's maximize is a plain resize+move on a
    // floating window, so the compositor emits NO event for it and a poll tick
    // was the ONLY way to learn about it. That is what "sometimes it waits way
    // too long" was.
    //
    // So the monitor half stays on the 1s hyprctl poll, and `applyClients` is a
    // public entry point: HyprEvents.qml pumps it from Hyprland's own request
    // socket several times a second, which costs a socket round trip rather
    // than three process spawns.
    property var _shown: ({})
    property var _box: ({})
    property var _monName: ({})
    property var _virt: ({})
    property int _barW: 31
    // Which window edge hyprvtb hangs the titlebar off (plugin:hyprvtb:titlebar_edge:
    // right/left/top/bottom, default right). The chrome (2 cells of bar_width)
    // extends the frame on THAT edge only — the other three are just the border.
    // Read from the plugin so the frame maths tracks a retitled bar, not a guess.
    property string _tbEdge: "right"
    property bool _monsReady: false

    function applyMonitors(mons) {
        // The workspaces actually on screen, and each monitor's logical
        // box. Hyprland reports monitor width/height in DEVICE pixels
        // and window positions in LOGICAL ones, hence the divide.
        const shown = {};
        const box = {};
        // monitor id -> name, for the frames published below.
        const monName = {};
        // monitor id -> true when the compositor has NO hardware
        // identity for that output, i.e. it is virtual (see above).
        const virt = {};
        for (const m of mons) {
            if (m.activeWorkspace) shown[m.activeWorkspace.id] = true;
            const s = m.scale > 0 ? m.scale : 1;
            box[m.id] = { x: m.x, right: m.x + Math.round(m.width / s) };
            const identified = m.physicalWidth > 0 || m.physicalHeight > 0
                || (m.make || "") !== "" || (m.model || "") !== ""
                || (m.serial || "") !== "" || (m.description || "") !== "";
            virt[m.id] = !identified
                || String(m.name || "").indexOf("HEADLESS-") === 0;
            monName[m.id] = m.name || "";
        }
        root._shown = shown;
        root._box = box;
        root._monName = monName;
        root._virt = virt;
        root._monsReady = true;
    }

    function applyClients(clients) {
        if (!root._monsReady || !clients)
            return;
        const shown = root._shown, box = root._box;
        const monName = root._monName, virt = root._virt, barW = root._barW;
        const tbEdge = root._tbEdge;
        // Titlebar chrome (2 cells of bar_width) hangs off exactly one edge.
        const bw = Theme.windowBorderWidth;
        const chL = tbEdge === "left" ? 2 * barW : 0;
        const chR = tbEdge === "right" ? 2 * barW : 0;
        const chT = tbEdge === "top" ? 2 * barW : 0;
        const chB = tbEdge === "bottom" ? 2 * barW : 0;

        const next = {};
        const addrs = {};
        const frames = [];
        let fs = false;
        // key -> {v: on a virtual output, r: on a real one}. A key is
        // only off-screen when NOTHING under it is on a real output.
        const tally = {};
        for (const c of clients) {
            if (!c.mapped) continue;
            // Before the state branches below, which skip most windows:
            // this one is about every mapped client, not just the
            // rolled and minimized ones. An unknown monitor id (-1 on a
            // special workspace) counts as real — fail visible.
            const tk = root.keyOf(c.class, c.title);
            const t = tally[tk] || (tally[tk] = { v: 0, r: 0 });
            if (virt[c.monitor]) t.v++; else t.r++;

            // A fullscreen window the user is actually in front of — not one
            // parked on a workspace he has switched away from, and not one on
            // the agents' sandbox output.
            if (!c.hidden && c.fullscreen === 2 && !virt[c.monitor]
                    && (!c.workspace || shown[c.workspace.id]))
                fs = true;

            // Frames: everything mapped and actually on screen. A rolled
            // (hidden) window is not something anything can be flush
            // against, and a window on a workspace that is not showing
            // is not there at all.
            if (!c.hidden && c.at && c.size
                    && (!c.workspace || shown[c.workspace.id]))
                frames.push({
                    mon: monName[c.monitor] || "",
                    l: c.at[0] - bw - chL,
                    r: c.at[0] + c.size[0] + bw + chR,
                    t: c.at[1] - bw - chT,
                    b: c.at[1] + c.size[1] + bw + chB,
                    // Hyprland's fullscreen mode: 0 none, 1 MAXIMIZED,
                    // 2 fullscreen. A maximized window is laid out
                    // against the reserved area BY DEFINITION, which is
                    // a far sturdier answer to "is it flush with the
                    // panel" than measuring chrome — a window with no
                    // hyprvtb titlebar (a rule, a layer-ish client)
                    // makes the arithmetic below 64px wrong. A
                    // FULLSCREEN one covers the panel entirely and is
                    // deliberately not this.
                    max: c.fullscreen === 1
                });

            const b = box[c.monitor];
            // 4px of slack: the park position is the monitor's right
            // edge, and width/scale can round a pixel or two off it.
            const parked = b && c.at && c.at[0] >= b.right - 4;
            const k = tk;
            if (!c.hidden && parked)
                next[k] = "minimized";
            else if (c.hidden && c.workspace && shown[c.workspace.id])
                next[k] = "rolled";
            else
                continue;
            addrs[k] = c.address || "";
        }

        const off = {};
        for (const tk in tally)
            if (tally[tk].v > 0 && tally[tk].r === 0) off[tk] = true;

        root.byKey = next;
        root.addrByKey = addrs;
        root.offOutputByKey = off;
        root.frames = frames;
        root.fullscreenShown = fs;
    }

    // The fast half: one persistent process on Hyprland's request socket,
    // printing the client list only when it CHANGES (see scripts/win-watch.py
    // for why this is not just a shorter Timer). It never touches the monitor
    // half, so `_monsReady` gates it until the first full poll has landed.
    Process {
        id: winWatch
        running: true
        command: [Quickshell.shellDir + "/scripts/win-watch.py"]
        stdout: SplitParser {
            splitMarker: "\n"
            onRead: line => {
                try {
                    root.applyClients(JSON.parse(line));
                } catch (e) {
                    // A partial line is a dropped sample, not a reason to stop.
                }
            }
        }
    }

    Process {
        id: clientsProc
        onRunningChanged: if (!running && root._pending) pendingKick.restart()
        command: ["sh", "-c", "hyprctl -j monitors; echo '#--#'; hyprctl -j clients; echo '#--#'; hyprctl -j getoption plugin:hyprvtb:bar_width; echo '#--#'; hyprctl -j getoption plugin:hyprvtb:titlebar_edge"]
        stdout: StdioCollector {
            onStreamFinished: {
                const halves = this.text.split("#--#");
                if (halves.length < 2) return;
                let mons = [], clients = [], vtb = null, tbe = null;
                try {
                    mons = JSON.parse(halves[0]) || [];
                    clients = JSON.parse(halves[1]) || [];
                    if (halves.length > 2) vtb = JSON.parse(halves[2]);
                    if (halves.length > 3) tbe = JSON.parse(halves[3]);
                } catch (e) { return; }
                // The plugin's own bar width, so the frame maths is the
                // plugin's number and not a copy of it. Its shipped default is
                // the fallback for the moment before the plugin answers.
                root._barW = (vtb && vtb.int > 0) ? vtb.int : 31;
                // Which edge the titlebar hangs off, same source, same reason.
                if (tbe && tbe.str) root._tbEdge = tbe.str;
                root.applyMonitors(mons);
                root.applyClients(clients);
            }
        }
    }
}

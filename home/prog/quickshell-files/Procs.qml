pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// The running-process table behind the task manager: scripts/proc-list.py
// sampled every 2s while something is watching.
//
// CPU% is instantaneous (two /proc samples 0.4s apart), NOT ps's lifetime
// average — see the script's header for why that distinction is the whole point
// of a task manager. The cost of that is a 0.4s round trip per refresh, which is
// exactly why this is `watch`-gated like Disks and Media: nothing samples /proc
// when nobody is looking at the list.
Singleton {
    id: root

    // [{pid, name, cpu, mem, rss}] as produced, i.e. already busiest-first.
    property var rows: []
    // Which column the user last clicked. Persisted rather than local, so it
    // survives both a panel reload and a logout — a heading the user chose is a
    // setting, not scratch state.
    readonly property string sortKey: SettingsStore.d.procSort
    // save() is not optional: SettingsStore's reader poll re-reads the file
    // every ~350ms, so an assignment that is never written is undone within the
    // second — which is why the heading used to forget what you clicked.
    function setSort(k) { SettingsStore.d.procSort = k; SettingsStore.save(); }
    readonly property int count: rows.length

    // ---- the filter box above the table ----------------------------------
    // Substring match on the process name, case-insensitive. NOT persisted to
    // settings.json: a sort column is a preference, but a filter is a question
    // you are asking right now, and coming back to a table that silently hides
    // most of the machine would be a trap. It IS carried across a panel reload
    // (see stateJson), because a reload is not the user putting it down.
    property string filter: ""
    function setFilter(t) { root.filter = t || ""; }
    // Whether the filter box holds the keyboard. The bar's layer surface only
    // takes keyboard focus while this is true (shell.qml) — an always-focusable
    // panel would swallow a keystroke meant for the window you were typing in.
    property bool filterFocus: false
    readonly property int total: rows.length

    property var _watchers: []
    readonly property bool live: _watchers.length > 0
    function watch(obj, on) {
        const i = _watchers.indexOf(obj);
        if (on === (i >= 0)) return;
        let w = _watchers.slice();
        if (on) w.push(obj); else w.splice(i, 1);
        _watchers = w;
        if (on) refresh();
    }

    readonly property var sorted: {
        const f = root.filter.trim().toLowerCase();
        const r = f === ""
            ? rows.slice()
            : rows.filter(p => p.name.toLowerCase().indexOf(f) >= 0
                            || String(p.pid).indexOf(f) >= 0);
        if (sortKey === "mem") r.sort((a, b) => b.mem - a.mem);
        else if (sortKey === "name") r.sort((a, b) => a.name.localeCompare(b.name));
        // pid ascending is start order, which is the only reading of a pid that
        // means anything — descending would just be "newest first" spelled oddly.
        else if (sortKey === "pid") r.sort((a, b) => Number(a.pid) - Number(b.pid));
        else r.sort((a, b) => b.cpu - a.cpu);
        return r;
    }

    function refresh() { listProc.running = true; }

    // ---- reload continuity (see shell.qml's `persist` block) --------------
    // A reload would otherwise empty the table and refill it 0.4s later, which
    // in a fixed-height tile reads as the whole list blinking out.
    property int stateRev: 0
    function stateJson() { return JSON.stringify({ r: rows, f: filter }); }
    function restoreState(str) {
        if (!str) return;
        try {
            const d = JSON.parse(str);
            // Tolerate the older shape (a bare rows array), so a reload across
            // this change doesn't drop the table on the floor.
            if (Array.isArray(d)) { root.rows = d; return; }
            root.rows = d.r || [];
            root.filter = d.f || "";
        } catch (e) {}
    }

    Process {
        id: listProc
        command: [Quickshell.shellDir + "/scripts/proc-list.py", "60"]
        stdout: StdioCollector {
            onStreamFinished: {
                let out = [];
                for (const ln of this.text.trim().split("\n")) {
                    if (!ln) continue;
                    const f = ln.split("|");
                    if (f.length < 5) continue;
                    out.push({ pid: f[0], name: f[1],
                               cpu: parseFloat(f[2]) || 0,
                               mem: parseFloat(f[3]) || 0,
                               rss: parseInt(f[4], 10) || 0 });
                }
                root.rows = out;
                root.stateRev++;
            }
        }
    }
    // 2s, against a sampler that itself takes 0.4s — fast enough to watch a
    // spike, slow enough that the list is readable while it updates.
    Timer {
        interval: 2000
        running: root.live
        repeat: true
        onTriggered: root.refresh()
    }

    // SIGTERM by default: "click the [x]", not "shoot it". force=true is SIGKILL
    // and is the right-click, so it can't be reached by a mis-click on a row
    // whose position just shifted under the cursor.
    function kill(pid, force) {
        Quickshell.execDetached(["kill", force ? "-KILL" : "-TERM", String(pid)]);
        // reflect it immediately rather than at the next poll
        refreshSoon.restart();
    }
    Timer { id: refreshSoon; interval: 300; onTriggered: root.refresh() }

    function fmtMem(kb) {
        if (kb >= 1024 * 1024) return (kb / 1024 / 1024).toFixed(1) + "G";
        if (kb >= 1024) return Math.round(kb / 1024) + "M";
        return kb + "K";
    }
}

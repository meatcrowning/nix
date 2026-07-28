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

    // [{pid, name, cpu, mem, rss, state, nice, mine}] as produced, i.e. already
    // busiest-first. The last three feed the row's context menu, not the table.
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
    // Whether the filter box holds the keyboard, and whether the pointer is
    // over it. The bar's layer surface only offers keyboard focus while one of
    // these is true (shell.qml) — an always-focusable panel would swallow a
    // keystroke meant for the window you were typing in. `filterHover` is what
    // ARMS it: measured in a nested Hyprland, an on-demand layer surface is
    // granted the keyboard by the compositor on the next pointer MOTION over it
    // — not on a click — so the surface has to already be focusable before the
    // pointer gets there.
    property bool filterFocus: false
    property bool filterHover: false
    // Bumped to ask the box to give the keyboard back — clicking anywhere else
    // in the panel. The box watches this rather than being reached into,
    // because it lives inside an asynchronous Loader in the dock grid.
    property int blurSeq: 0
    function blurFilter() { root.blurSeq++; }

    // ---- letting go of the keyboard ----------------------------------------
    //
    // Taking the keyboard and giving it back are NOT symmetrical, and there is
    // exactly one place it is unsafe to give it back: **with the pointer still
    // over the panel.** Dropping the surface from on-demand to none there runs
    // Hyprland's `CLayerSurface::commit` -> `refocusLastWindow`, which looks
    // for a window UNDER THE POINTER, finds this panel, and gives up — the
    // compositor is left focused on nothing at all (`activewindow>>,` on the
    // event socket) and with `input:follow_mouse = 2` nothing later puts it
    // back. Measured, all three cases, in a nested compositor:
    //
    //     disarm, pointer over the PANEL     -> activewindow>>,  keyboard: NOBODY
    //     disarm, pointer over a WINDOW      -> clean, the window gets it
    //     disarm, pointer over the WALLPAPER -> clean, the last window gets it
    //
    // (the wallpaper is safe because `refocusLastWindow` only searches the
    // OVERLAY and TOP layers, so a Background surface under the pointer is not
    // found and it falls through to the last focused window.)
    //
    // **There is no explicit hand-back to reach for instead** — that was tried
    // and measured. `hl.dsp.focus({window = X})` reports `ok` and does nothing
    // in this state: `CA::focus` passes a null surface to
    // `CFocusState::rawWindowFocus`, which early-returns on
    // `pWindow == m_focusWindow && surface == m_focusSurface` — and a layer
    // surface taking the keyboard leaves `m_focusWindow` naming the window
    // while `rawSurfaceFocus(nullptr)` has reset `m_focusSurface`, so both
    // halves match and the call is a no-op.
    //
    // So `filterLatch` holds the surface focusable from the hover until the
    // pointer has LEFT THE BAR (shell.qml's HoverHandler clears it), which is
    // the only moment the hand-back is the compositor's to get right.
    //
    // THE CARET IS A SEPARATE QUESTION, and that separation is the whole
    // design. "Click anywhere outside the box and it stops taking the
    // keyboard" is about the caret: `blurFilter` clears it the instant the
    // click lands, wherever it lands, so the box stops receiving keystrokes
    // immediately. The surface goes on offering itself for a moment longer —
    // until the pointer leaves — because that is the compositor's constraint,
    // not the user's.
    property bool filterLatch: false
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
                    // Glyphs.px on the NAME only. It is display + filter text;
                    // the pid beside it is what kill() signals, and that stays
                    // exactly as the sampler reported it.
                    // Fields past rss are APPENDED and optional: a table
                    // restored from an older reload's stateJson has only five,
                    // and the menu must degrade rather than throw on it.
                    out.push({ pid: f[0], name: Glyphs.px(f[1]),
                               cpu: parseFloat(f[2]) || 0,
                               mem: parseFloat(f[3]) || 0,
                               rss: parseInt(f[4], 10) || 0,
                               state: f.length > 5 ? f[5] : "?",
                               nice: f.length > 6 ? (parseInt(f[6], 10) || 0) : 0,
                               mine: f.length > 7 ? f[7] === "1" : true });
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

    // ---- what a row can be asked to do -----------------------------------
    //
    // Everything here is a fire-and-forget `execDetached`: there is no exit
    // code and no stderr, so a signal the kernel refuses (EPERM on somebody
    // else's process) is a perfect silent no-op. That is why the sampler
    // reports `mine` and the menu refuses to offer these on a row we do not
    // own — the check has to happen BEFORE the call, because nothing after it
    // can tell success from failure.

    // SIGTERM by default: "click the [x]", not "shoot it". force=true is
    // SIGKILL, which the row offers only through the context menu — an
    // unrecoverable action must not be one mis-timed click away on a table
    // that re-sorts under the cursor every 2s.
    function kill(pid, force) { signal(pid, force ? "KILL" : "TERM"); }

    // SIGSTOP/SIGCONT are the interesting pair beyond ending a process: a
    // runaway can be frozen and inspected rather than lost.
    function signal(pid, sig) {
        Quickshell.execDetached(["kill", "-" + sig, String(pid)]);
        // reflect it immediately rather than at the next poll
        refreshSoon.restart();
    }

    // Niceness only ever goes UP without privilege, so this is one-way and the
    // menu says so ("Lower Priority", never "restore"). renice is util-linux
    // on both hosts, i.e. on the bare Fedora PATH book's panel has.
    function renice(pid, n) {
        Quickshell.execDetached(["renice", "-n", String(n), "-p", String(pid)]);
        refreshSoon.restart();
    }

    // -n: wl-copy appends a newline to argv content otherwise, and a pid pasted
    // into a shell should not carry one. `--` so a process name that begins
    // with a dash is text, not options.
    function copyText(s) { Quickshell.execDetached(["wl-copy", "-n", "--", String(s)]); }

    Timer { id: refreshSoon; interval: 300; onTriggered: root.refresh() }

    function fmtMem(kb) {
        if (kb >= 1024 * 1024) return (kb / 1024 / 1024).toFixed(1) + "G";
        if (kb >= 1024) return Math.round(kb / 1024) + "M";
        return kb + "K";
    }
}

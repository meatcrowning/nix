pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

// Book-only: mirrors `top`'s CPU/mem/network stats over the tailnet, so the
// system-info popup can show top's proc graphs beneath book's own (see
// TopProcDrawer.qml / CpuPanel.qml). It reaches top by ssh to the MagicDNS name
// `top` — sys/net/tailscale.nix opens 22 on tailscale0 and lam is the operator,
// so it is passwordless — and runs the SAME scripts/sysinfo.sh the local
// SysInfo polls. That script's pipe line is parsed here into ring buffers shaped
// like SysInfo's own, so MetricChart draws them with no special-casing.
//
// No new listener anywhere: this is an OUTBOUND ssh with a persistent
// ControlMaster, exactly the loopback/tailnet-only rule the comfy tunnel
// follows. And it polls ONLY while something watches — watch(obj, on), the same
// registry Media/Procs gate their pollers on — so a closed drawer spawns no ssh
// and top is never touched when nobody is looking.
//
// `reachable` is false until a poll succeeds and after any failed connection;
// the drawer reads it and says so rather than drawing a blank chart (a machine
// that is asleep, off the tailnet, or has no key set up yet must fail VISIBLY —
// docs/DESIGN.md §10.2).
Singleton {
    id: root

    property int  cpuUsage: -1
    property int  cpuTemp: -1
    property int  memUsage: -1
    property real rxSpeed: 0            // bytes/s
    property real txSpeed: 0
    // Did the last poll connect? Cleared on any non-zero ssh exit.
    property bool reachable: false
    // Has a poll EVER completed? Separates "connecting…" from "unreachable".
    property bool everReached: false

    // Same 90-sample window as SysInfo's hover charts (90 * 2s = 3 min).
    readonly property int chartLen: 90
    property var cpuHist: []
    property var tempHist: []
    property var memHist: []

    // Cumulative counters the next poll diffs against, exactly as SysInfo does —
    // cpu total/idle and the network byte totals are counters, not rates.
    property real _prevCpuTotal: -1
    property real _prevCpuIdle: -1
    property real _prevRx: -1
    property real _prevTx: -1
    property real _prevAt: 0

    readonly property real intervalSec: SettingsStore.d.monPollSec

    // ---- on-screen registry: poll only while watched ---------------------
    property var _watchers: []
    // Air-only by construction: the poll command names `top`, and this mirror is
    // book watching top, so nothing here ever runs on top itself.
    readonly property bool live: _watchers.length > 0 && Host.name === "air"
    function watch(obj, on) {
        const i = _watchers.indexOf(obj);
        if (on === (i >= 0)) return;
        let w = _watchers.slice();
        if (on) w.push(obj); else w.splice(i, 1);
        _watchers = w;
        if (on && live) poll.running = true;
    }

    function _pushHist(arr, v) {
        const h = arr.slice();
        h.push(v);
        while (h.length > chartLen) h.shift();
        return h;
    }

    function parse(text) {
        const line = (text || "").trim();
        if (line === "") return;
        const f = line.split("|");
        if (f.length < 9) return;

        const now = Date.now();
        // Real elapsed time, floored so a fast double-poll can't divide by ~0 —
        // the same denominator reasoning as SysInfo's throughput counters.
        const dt = _prevAt > 0 ? Math.max(0.25, (now - _prevAt) / 1000) : intervalSec;

        const rx = parseFloat(f[0]) || 0;
        const tx = parseFloat(f[1]) || 0;
        if (_prevRx >= 0) {
            rxSpeed = Math.max(0, (rx - _prevRx) / dt);
            txSpeed = Math.max(0, (tx - _prevTx) / dt);
        }
        _prevRx = rx;
        _prevTx = tx;

        const cpuTotal = parseFloat(f[6]) || 0;
        const cpuIdle  = parseFloat(f[7]) || 0;
        if (_prevCpuTotal >= 0) {
            const dTotal = cpuTotal - _prevCpuTotal;
            const dIdle  = cpuIdle - _prevCpuIdle;
            cpuUsage = dTotal > 0 ? Math.round(100 * (1 - dIdle / dTotal)) : 0;
        }
        _prevCpuTotal = cpuTotal;
        _prevCpuIdle  = cpuIdle;

        const rawTemp = parseInt(f[8]);
        cpuTemp = isNaN(rawTemp) || rawTemp < 0 ? -1 : Math.round(rawTemp / 1000);

        // Mem was appended for the task manager (f[13]/f[14]); guarded so a line
        // from an older/foreign sysinfo.sh still parses the cpu half.
        if (f.length >= 15) {
            const mt = parseInt(f[13]) || 0;
            const ma = parseInt(f[14]) || 0;
            memUsage = mt > 0 ? Math.round(100 * (mt - ma) / mt) : -1;
        }

        _prevAt = now;
        if (cpuUsage >= 0) cpuHist = _pushHist(cpuHist, cpuUsage);
        if (cpuTemp >= 0) tempHist = _pushHist(tempHist, cpuTemp);
        if (memUsage >= 0) memHist = _pushHist(memHist, memUsage);
        stateRev++;
    }

    // The ssh transport. Through `sh -c` only so the local shell expands
    // $XDG_RUNTIME_DIR for the ControlPath; the command itself is the SYSTEM ssh
    // (/usr/bin/ssh), because a nix ssh cannot resolve the tailnet name `top`
    // (book: nix binaries can't resolve mDNS/MagicDNS). BatchMode so a missing
    // key fails fast instead of hanging the poll on a password prompt;
    // ControlMaster+ControlPersist so 2s polls reuse one connection rather than a
    // fresh handshake each time. `$HOME` inside the single quotes is top's home,
    // resolved remotely.
    Process {
        id: poll
        command: ["sh", "-c",
            "exec /usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=4"
            + " -o ControlMaster=auto"
            + " -o ControlPath=\"${XDG_RUNTIME_DIR:-/tmp}/qs-topstats-ssh\""
            + " -o ControlPersist=30 top"
            + " 'sh \"$HOME/.config/quickshell/scripts/sysinfo.sh\" / auto'"]
        stdout: StdioCollector { onStreamFinished: root.parse(this.text) }
        onExited: (code) => {
            root.reachable = (code === 0);
            if (code === 0) root.everReached = true;
        }
    }

    Timer {
        interval: root.intervalSec * 1000
        running: root.live
        repeat: true
        triggeredOnStart: true
        onTriggered: if (!poll.running) poll.running = true
    }

    // ---- reload continuity (see shell.qml's `persist` block) --------------
    // Same contract as SysInfo: shell.qml snapshots this on stateRev and hands
    // it back before the first frame, so a reload with the drawer open keeps its
    // chart instead of emptying and refilling one poll later.
    property int stateRev: 0

    function stateJson() {
        return JSON.stringify({
            cu: cpuUsage, ct: cpuTemp, mu: memUsage, rx: rxSpeed, tx: txSpeed,
            re: reachable, er: everReached,
            ch: cpuHist, th: tempHist, mh: memHist,
            pct: _prevCpuTotal, pci: _prevCpuIdle,
            prx: _prevRx, ptx: _prevTx, pat: _prevAt,
        });
    }
    function restoreState(s) {
        if (!s) return;
        let d;
        try { d = JSON.parse(s); } catch (e) { return; }
        cpuUsage = d.cu; cpuTemp = d.ct; memUsage = d.mu;
        rxSpeed = d.rx || 0; txSpeed = d.tx || 0;
        reachable = !!d.re; everReached = !!d.er;
        cpuHist = d.ch || []; tempHist = d.th || []; memHist = d.mh || [];
        _prevCpuTotal = d.pct === undefined ? -1 : d.pct;
        _prevCpuIdle  = d.pci === undefined ? -1 : d.pci;
        _prevRx = d.prx === undefined ? -1 : d.prx;
        _prevTx = d.ptx === undefined ? -1 : d.ptx;
        _prevAt = d.pat || 0;
    }
}

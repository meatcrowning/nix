pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

// Book-only: mirrors `top`'s full system stats over the tailnet, so the
// dock's system-info tile can roll out a copy of top's OWN square-card grid
// beneath book's own (see TopProcDrawer.qml / MetricCardGrid.qml). It reaches
// top by ssh to the MagicDNS name `top` — sys/net/tailscale.nix opens 22 on
// tailscale0 and lam is the operator, so it is passwordless — and runs the SAME
// scripts/sysinfo.sh the local SysInfo polls. That script's pipe line is parsed
// here into ring buffers shaped exactly like SysInfo's own, and this singleton
// exposes the SAME property/method surface MetricCardGrid reads off SysInfo, so
// the grid draws top with no special-casing.
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

    // ---- cpu -------------------------------------------------------------
    property int  cpuUsage: -1
    property int  cpuTemp: -1
    property var  cpuHist: []
    property var  tempHist: []

    // ---- gpu (top has an nvidia card) ------------------------------------
    property int  gpuUsage: -1
    property int  gpuTemp: -1
    property var  gpuHist: []
    property var  gpuTempHist: []
    property int  gpuFanPct: -1
    property int  gpuMemUsedMb: -1
    property int  gpuMemTotalMb: -1
    readonly property int gpuMemUsage: gpuMemTotalMb > 0
        ? Math.round(100 * gpuMemUsedMb / gpuMemTotalMb) : -1
    property var  vramHist: []

    // ---- memory / swap ---------------------------------------------------
    property int  memTotalKb: 0
    property int  memAvailKb: 0
    readonly property int memUsedKb: Math.max(0, memTotalKb - memAvailKb)
    readonly property int memUsage: memTotalKb > 0
        ? Math.round(100 * memUsedKb / memTotalKb) : -1
    property var  memHist: []
    property int  swapTotalKb: 0
    property int  swapFreeKb: 0
    readonly property int swapUsage: swapTotalKb > 0
        ? Math.round(100 * (swapTotalKb - swapFreeKb) / swapTotalKb) : -1
    property var  swapHist: []

    // ---- network ---------------------------------------------------------
    property real rxSpeed: 0            // bytes/s
    property real txSpeed: 0
    property var  rxHist: []
    property var  txHist: []

    // ---- load ------------------------------------------------------------
    property real load1: -1
    property var  loadHist: []

    // ---- fans (parsed from fanDetail + the gpu fan) ----------------------
    property var  fans: []
    property var  fanPctHist: ({})
    property var  fanVaried: ({})
    property var  fanHadRpm: ({})
    // No remote alarm: a stopped fan on top is top's own notification to raise,
    // not book's. The grid tolerates this being "".
    readonly property string fanAlarm: ""

    // ---- inert on the mirror: book's psi/io/batt substitute cards are
    //      instantiated but hidden (noGpu=false), so their bindings still
    //      evaluate and need somewhere to read. Never populated. ------------
    readonly property real psiCpu: -1
    readonly property real psiIo: -1
    readonly property real psiMem: -1
    readonly property var  psiCpuHist: []
    readonly property var  psiIoHist: []
    readonly property var  psiMemHist: []
    readonly property real dskRead: -1
    readonly property real dskWrite: -1
    readonly property var  dskRHist: []
    readonly property var  dskWHist: []
    readonly property int  batteryPct: -1
    readonly property int  batteryStatus: 0
    readonly property string batteryLabel: ""
    readonly property var  batteryHist: []

    // Did the last poll connect? Cleared on any non-zero ssh exit.
    property bool reachable: false
    // Has a poll EVER completed? Separates "connecting…" from "unreachable".
    property bool everReached: false

    // Same 90-sample window as SysInfo's hover charts (90 * 2s = 3 min).
    readonly property int chartLen: 90

    // Cumulative counters the next poll diffs against, exactly as SysInfo does —
    // cpu total/idle and the network byte totals are counters, not rates.
    property real _prevCpuTotal: -1
    property real _prevCpuIdle: -1
    property real _prevRx: -1
    property real _prevTx: -1
    property real _prevAt: 0

    readonly property real intervalSec: SettingsStore.d.monPollSec

    // ---- the same human-readable helpers SysInfo exposes -----------------
    function fmtSpeed(bps) {
        if (bps < 1024) return "0";
        if (bps < 1024 * 1024) return Math.round(bps / 1024) + "K";
        return (bps / 1024 / 1024).toFixed(1) + "M";
    }
    function fmtSize(kb) {
        if (kb < 1024 * 1024) return Math.round(kb / 1024) + "M";
        return (kb / 1024 / 1024).toFixed(0) + "G";
    }

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

    // Parse sysinfo.sh's fanDetail ("name:rpm:pct,…") plus the gpu fan into
    // `fans`, and push this poll's sample onto each fan's own history keyed by
    // NAME. A simplified mirror of SysInfo._setFans: no stopped-fan re-emission
    // and no alarm — those are the watched machine's own to raise.
    function _setFans(raw) {
        const out = [];
        if (raw) {
            for (const e of String(raw).split(",")) {
                if (!e) continue;
                const p = e.split(":");
                if (p.length < 3) continue;
                const rpm = parseInt(p[1]);
                const pct = parseInt(p[2]);
                out.push({
                    name: p[0],
                    rpm: isNaN(rpm) ? -1 : rpm,
                    pct: isNaN(pct) || pct < 0 ? -1 : pct,
                });
            }
        }
        if (gpuFanPct >= 0)
            out.push({ name: "gpu", rpm: -1, pct: gpuFanPct });

        const h = {};
        const varied = {};
        for (const name in fanVaried) varied[name] = fanVaried[name];
        for (const fan of out) {
            if (fan.pct < 0) continue;
            const prev = fanPctHist[fan.name] || [];
            if (prev.length > 0 && prev[prev.length - 1] !== fan.pct)
                varied[fan.name] = true;
            h[fan.name] = _pushHist(prev, fan.pct);
        }
        const hadRpm = {};
        for (const name in fanHadRpm) hadRpm[name] = fanHadRpm[name];
        for (const fan of out)
            if (fan.rpm > 0) hadRpm[fan.name] = true;

        fans = out;
        fanPctHist = h;
        fanVaried = varied;
        fanHadRpm = hadRpm;
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

        const gu = parseInt(f[9]);
        gpuUsage = isNaN(gu) || gu < 0 ? -1 : gu;
        const gt = parseInt(f[10]);
        gpuTemp = isNaN(gt) || gt < 0 ? -1 : gt;

        // The task-manager block (mem/swap/load/gpu extras/fans), guarded so a
        // line from an older/foreign sysinfo.sh still parses the cpu half.
        if (f.length >= 23) {
            memTotalKb  = parseInt(f[13]) || 0;
            memAvailKb  = parseInt(f[14]) || 0;
            swapTotalKb = parseInt(f[15]) || 0;
            swapFreeKb  = parseInt(f[16]) || 0;
            const l1 = parseFloat(f[17]);
            load1 = isNaN(l1) ? -1 : l1;
            const gf = parseInt(f[19]);
            gpuFanPct = isNaN(gf) || gf < 0 ? -1 : gf;
            const gmu = parseInt(f[21]);
            gpuMemUsedMb = isNaN(gmu) || gmu < 0 ? -1 : gmu;
            const gmt = parseInt(f[22]);
            gpuMemTotalMb = isNaN(gmt) || gmt < 0 ? -1 : gmt;
            if (f.length >= 33)
                _setFans(f[32]);

            if (memUsage >= 0) memHist = _pushHist(memHist, memUsage);
            if (load1 >= 0) loadHist = _pushHist(loadHist, load1);
            if (swapUsage >= 0) swapHist = _pushHist(swapHist, swapUsage);
            if (gpuMemUsage >= 0) vramHist = _pushHist(vramHist, gpuMemUsage);
        }

        _prevAt = now;
        if (cpuUsage >= 0) cpuHist = _pushHist(cpuHist, cpuUsage);
        if (cpuTemp >= 0) tempHist = _pushHist(tempHist, cpuTemp);
        if (gpuUsage >= 0) gpuHist = _pushHist(gpuHist, gpuUsage);
        if (gpuTemp >= 0) gpuTempHist = _pushHist(gpuTempHist, gpuTemp);
        if (_prevRx >= 0 && _prevAt > 0) {
            rxHist = _pushHist(rxHist, rxSpeed);
            txHist = _pushHist(txHist, txSpeed);
        }
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
    //
    // ServerAlive*+`timeout` are the recovery path for the ControlMaster going
    // half-dead (book sleeping/waking or roaming off the tailnet leaves the
    // shared master's TCP connection gone with no FIN ever received): measured
    // live, a poll wedged on the stale mux socket for 19h8m with `reachable`
    // frozen at its last value and NOTHING in `qs log` — `ConnectTimeout` only
    // bounds the initial TCP handshake, not a session request over an already
    // -established master. ServerAliveInterval/CountMax make the MASTER itself
    // detect the dead link (~10s) and tear down, so a wedged mux client fails
    // fast instead of hanging forever; the local `timeout` is a backstop for a
    // dead link a NAT keeps acking, which ServerAlive alone cannot see.
    Process {
        id: poll
        command: ["sh", "-c",
            "exec /usr/bin/timeout 15 /usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=4"
            + " -o ServerAliveInterval=5 -o ServerAliveCountMax=2"
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
    // grid instead of emptying and refilling one poll later.
    property int stateRev: 0

    function stateJson() {
        return JSON.stringify({
            cu: cpuUsage, ct: cpuTemp, ch: cpuHist, th: tempHist,
            gu: gpuUsage, gt: gpuTemp, gh: gpuHist, gth: gpuTempHist,
            gf: gpuFanPct, gmu: gpuMemUsedMb, gmt: gpuMemTotalMb, vh: vramHist,
            mt: memTotalKb, ma: memAvailKb, mh: memHist,
            st: swapTotalKb, sf: swapFreeKb, sh: swapHist,
            rx: rxSpeed, tx: txSpeed, rxh: rxHist, txh: txHist,
            l1: load1, lh: loadHist,
            fns: fans, fph: fanPctHist, fvd: fanVaried, fhr: fanHadRpm,
            re: reachable, er: everReached,
            pct: _prevCpuTotal, pci: _prevCpuIdle,
            prx: _prevRx, ptx: _prevTx, pat: _prevAt,
        });
    }
    function restoreState(s) {
        if (!s) return;
        let d;
        try { d = JSON.parse(s); } catch (e) { return; }
        cpuUsage = d.cu; cpuTemp = d.ct; cpuHist = d.ch || []; tempHist = d.th || [];
        gpuUsage = d.gu === undefined ? -1 : d.gu;
        gpuTemp = d.gt === undefined ? -1 : d.gt;
        gpuHist = d.gh || []; gpuTempHist = d.gth || [];
        gpuFanPct = d.gf === undefined ? -1 : d.gf;
        gpuMemUsedMb = d.gmu === undefined ? -1 : d.gmu;
        gpuMemTotalMb = d.gmt === undefined ? -1 : d.gmt;
        vramHist = d.vh || [];
        memTotalKb = d.mt || 0; memAvailKb = d.ma || 0; memHist = d.mh || [];
        swapTotalKb = d.st || 0; swapFreeKb = d.sf || 0; swapHist = d.sh || [];
        rxSpeed = d.rx || 0; txSpeed = d.tx || 0;
        rxHist = d.rxh || []; txHist = d.txh || [];
        load1 = d.l1 === undefined ? -1 : d.l1; loadHist = d.lh || [];
        fans = d.fns || []; fanPctHist = d.fph || ({});
        fanVaried = d.fvd || ({}); fanHadRpm = d.fhr || ({});
        reachable = !!d.re; everReached = !!d.er;
        _prevCpuTotal = d.pct === undefined ? -1 : d.pct;
        _prevCpuIdle  = d.pci === undefined ? -1 : d.pci;
        _prevRx = d.prx === undefined ? -1 : d.prx;
        _prevTx = d.ptx === undefined ? -1 : d.ptx;
        _prevAt = d.pat || 0;
    }
}

pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Drive list (df + lsblk) and SMART, hoisted out of DiskPanel.qml.
//
// It had to leave the popup because the popup is no longer the only thing that
// draws it: the same widget also renders as a dock tile, and two copies of the
// view meant two copies of the scripts, two 5s timers, and two different answers
// to `qs ipc call state carried`. The view components (DiskContent.qml) are now
// stateless readers of this.
//
// WHO IS LOOKING drives the polling. `watch(obj, on)` is a SET, not a counter,
// so a consumer that re-registers (a binding re-evaluating, a reload restoring)
// cannot leak a reference and leave the scripts running against nobody. SMART in
// particular can spin an idle disk up, so it must never be on a free-running
// timer.
Singleton {
    id: root

    property var drives: []   // [{src,label,mount,size,used,rota,model,fstype}]
    property var smart: ({})  // "/dev/sdX" -> {health,temp,wear,poh}

    property var _watchers: []
    readonly property bool live: _watchers.length > 0
    function watch(obj, on) {
        const i = _watchers.indexOf(obj);
        if (on === (i >= 0)) return;
        let w = _watchers.slice();
        if (on) w.push(obj); else w.splice(i, 1);
        _watchers = w;
        // a new viewer gets fresh numbers immediately rather than up to 5s late
        if (on) refresh();
    }

    function refresh() {
        usageProc.running = true;
        smartProc.running = true;
    }

    // ---- reload continuity (see shell.qml's `persist` block) --------------
    // This widget is the loudest thing on screen during a reload if left alone.
    // It comes back with no drives, i.e. the one-line "reading…" height; then
    // disk-usage.sh lands and it grows several rows; then smartctl lands and it
    // grows again. It is bottom-anchored, so each growth walks its top edge up
    // the screen — and every in-place stackable above it (gpu/cpu/eth) chases it
    // via Popups.stackObstacleTop. Carrying drives+smart across means it is laid
    // out at its true height before the first frame; the scripts still re-run
    // underneath, they just confirm what is already drawn.
    property int stateRev: 0
    function stateJson() { return JSON.stringify({ d: drives, s: smart }); }
    function restoreState(str) {
        if (!str) return;
        try {
            const o = JSON.parse(str);
            root.drives = o.d || [];
            root.smart = o.s || ({});
        } catch (e) {}
    }

    // Pre-warm the fast (df+lsblk) list at startup so the widget already knows
    // its real height before it is ever revealed — otherwise it maps at the
    // one-line "reading…" height and whatever is stacked above it freezes too
    // low. SMART stays on-demand.
    Component.onCompleted: usageProc.running = true

    function baseName(mount) {
        if (mount === "/") return "root";
        const p = mount.split("/");
        return p[p.length - 1] || mount;
    }
    function fmtG(bytes) {
        const g = bytes / 1e9;
        if (g >= 1000) return (g / 1000).toFixed(1) + "T";
        return Math.round(g) + "G";
    }
    // SMART record for a partition's parent physical drive, or null
    function smartFor(src) {
        for (const dev in root.smart)
            if (src.indexOf(dev) === 0) return root.smart[dev];
        return null;
    }

    // ---- relabel a filesystem via the root helper, then refresh -----------
    property string renaming: ""   // src currently being relabeled inline
    Process {
        id: labelProc
        onExited: { root.renaming = ""; usageProc.running = true; }
    }
    function relabel(src, fstype, newLabel) {
        // resolve the wrapper's real store path so the NOPASSWD sudo rule
        // (which lists that path) matches — same reason as disk-smart.sh.
        labelProc.command = ["sh", "-c",
            'exec sudo -n "$(readlink -f "$(command -v drive-label)")" "$1" "$2" "$3"',
            "_", src, fstype, newLabel];
        labelProc.running = true;
    }

    // The scripts are installed beside the QML (see quickshell.nix); resolve
    // relative to this file so it works from either machine's config dir.
    readonly property string _scripts:
        Qt.resolvedUrl("scripts/").toString().replace("file://", "")

    Process {
        id: usageProc
        command: ["sh", root._scripts + "disk-usage.sh"]
        stdout: StdioCollector {
            onStreamFinished: {
                let out = [];
                for (const ln of this.text.trim().split("\n")) {
                    if (!ln) continue;
                    const f = ln.split("|");
                    if (f.length < 7) continue;
                    out.push({ src: f[0], label: f[1], mount: f[2],
                               size: parseFloat(f[3]) || 0, used: parseFloat(f[4]) || 0,
                               rota: f[5] === "1", model: f[6], fstype: f[7] || "" });
                }
                root.drives = out;
                root.stateRev++;
            }
        }
    }
    Process {
        id: smartProc
        command: ["sh", root._scripts + "disk-smart.sh"]
        stdout: StdioCollector {
            onStreamFinished: {
                let m = {};
                for (const ln of this.text.trim().split("\n")) {
                    if (!ln) continue;
                    const f = ln.split("|");
                    if (f.length < 5) continue;
                    m[f[0]] = { health: f[1], temp: f[2], wear: f[3], poh: f[4] };
                }
                root.smart = m;
                root.stateRev++;
            }
        }
    }
    Timer {
        interval: 5000
        running: root.live
        repeat: true
        onTriggered: root.refresh()
    }
}

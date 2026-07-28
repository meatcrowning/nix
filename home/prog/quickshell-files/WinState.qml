pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Which windows are rolled up, minimized, or on an output the user cannot see —
// for the taskbar cells and for everything else that reads the toplevel list.
//
// The Wayland foreign-toplevel list the taskbar is built on (ToplevelManager)
// carries appId, title and activated — and nothing else. Roll-up and minimize
// are hyprvtb's, not the protocol's, so their state has to come from the
// compositor. This polls `hyprctl clients -j` (measured at ~4ms per call) and
// derives the two from what the plugin actually does to a window:
//
//   ROLLED UP   the plugin calls setHidden(true) and leaves the geometry alone,
//               so the window reads hidden=true where it stands. `hidden` is
//               also true for a window on a workspace that isn't showing, so a
//               window only counts as rolled if its workspace is the active one
//               on some monitor.
//   MINIMIZED   the plugin parks the window at the monitor's right edge
//               (x = monitor.x + monitor width, in LOGICAL pixels) and does not
//               hide it. So: not hidden, and its left edge is at or past that
//               edge. Verified live — a minimized window on this 2560px/1.67
//               screen sits at x=1536.
//
// Both signatures were measured on a real window rather than reasoned about,
// and neither is a heuristic about "off-screen-ish" coordinates: they are the
// exact two things vtbDeco.cpp does (rollUp -> setHidden, minimizeWindow ->
// move to PMONITOR->m_position.x + PMONITOR->m_size.x).
//
// Keyed by class + title, since that is all the toplevel list gives us to join
// on — this build has no Hyprland window-mapping protocol (see Taskbar.qml).
// Two windows of the same app with the SAME title are indistinguishable here
// and will show each other's state; anything else resolves exactly.
//
// ---- OUTPUTS THE USER CANNOT SEE ------------------------------------------
//
// `tools/sandbox.sh` gives agents a monitor to test on: `hyprctl output create
// headless` makes a real output in every way the compositor cares about, except
// that no cable leads anywhere. Its whole promise is that nothing an agent opens
// reaches the user's screen — and the WAYLAND TOPLEVEL LIST BROKE THAT PROMISE,
// because it carries no monitor at all. Every test window an agent launched
// appeared in his taskbar, three feet from his face, which is how this was
// found. The compositor knows; the protocol does not — the same shape of problem
// as roll-up and minimize above, so it is answered from the same poll.
//
// A monitor is PHYSICAL if the compositor has any hardware identity for it: a
// non-zero physical size, or a make, model, serial or description. A headless
// output has none of those — every one of those fields is empty (verified live:
// DP-5 carries "Dell Inc. DELL P2422HE 5XP45L3" and 530x300mm, HEADLESS-6
// carries "" and 0x0). That test, not the name, is the discriminator, because
// the user may legitimately attach a SECOND REAL MONITOR one day and its windows
// must still appear. Hyprland's `HEADLESS-n` naming is ORed in as corroboration
// only: it can add virtual outputs but never subtract one, and no DRM connector
// is ever named that (they are eDP/DP/HDMI-A/DVI/VGA), so it cannot cost a real
// monitor its taskbar.
//
// The join is fail-VISIBLE, which is the direction that matters: a key counts as
// off-screen only if EVERY mapped client under it is on a virtual output. Two
// windows of one app with the same title are indistinguishable here (see above),
// and hiding one of the user's own windows from his taskbar is far worse than
// showing one of an agent's for the ~1s it takes the next poll to land.
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

    function refresh() { if (!clientsProc.running) clientsProc.running = true; }

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
    Process {
        id: clientsProc
        command: ["sh", "-c", "hyprctl -j monitors; echo '#--#'; hyprctl -j clients"]
        stdout: StdioCollector {
            onStreamFinished: {
                const halves = this.text.split("#--#");
                if (halves.length < 2) return;
                let mons = [], clients = [];
                try {
                    mons = JSON.parse(halves[0]) || [];
                    clients = JSON.parse(halves[1]) || [];
                } catch (e) { return; }

                // The workspaces actually on screen, and each monitor's logical
                // box. Hyprland reports monitor width/height in DEVICE pixels
                // and window positions in LOGICAL ones, hence the divide.
                const shown = {};
                const box = {};
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
                }

                const next = {};
                const addrs = {};
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
            }
        }
    }
}

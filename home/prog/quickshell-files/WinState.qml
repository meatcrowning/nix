pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Which windows are rolled up or minimized, for the taskbar cells.
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

    function keyOf(appId, title) { return (appId || "") + "\n" + (title || ""); }
    // Reading root.byKey inside the call is what registers the binding
    // dependency, so cells recolour when a poll changes something.
    function stateOf(appId, title) { return root.byKey[keyOf(appId, title)] || ""; }
    function addrOf(appId, title) { return root.addrByKey[keyOf(appId, title)] || ""; }

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
                for (const m of mons) {
                    if (m.activeWorkspace) shown[m.activeWorkspace.id] = true;
                    const s = m.scale > 0 ? m.scale : 1;
                    box[m.id] = { x: m.x, right: m.x + Math.round(m.width / s) };
                }

                const next = {};
                const addrs = {};
                for (const c of clients) {
                    if (!c.mapped) continue;
                    const b = box[c.monitor];
                    // 4px of slack: the park position is the monitor's right
                    // edge, and width/scale can round a pixel or two off it.
                    const parked = b && c.at && c.at[0] >= b.right - 4;
                    const k = root.keyOf(c.class, c.title);
                    if (!c.hidden && parked)
                        next[k] = "minimized";
                    else if (c.hidden && c.workspace && shown[c.workspace.id])
                        next[k] = "rolled";
                    else
                        continue;
                    addrs[k] = c.address || "";
                }
                root.byKey = next;
                root.addrByKey = addrs;
            }
        }
    }
}

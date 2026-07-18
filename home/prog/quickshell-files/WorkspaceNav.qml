pragma Singleton
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// Dynamic workspace creation, shared by mainMod+scroll (hypr/hyprland.lua,
// via `qs ipc call workspace next|prev` — see shell.qml's IpcHandler) and
// BackgroundScroll.qml (same process, calls go() directly — no IPC round
// trip needed). Landing on an existing workspace is always allowed;
// creating a NEW one beyond the current frontier requires the workspace
// you're leaving to already have at least one window in it, so a direction
// only grows the stack one workspace at a time, gated on actually having
// used the last one. Anchored on workspace 50 (hyprland.lua's startup
// dispatch) so growth has room to go both up (49, 48, ...) and down
// (51, 52, ...) from that centre.
Singleton {
    id: root

    function go(dir) {
        const list = Hyprland.workspaces.values || [];
        let current = null;
        for (let i = 0; i < list.length; i++) {
            if (list[i].active) { current = list[i]; break; }
        }
        if (!current) return;

        const targetId = current.id + dir;
        const exists = list.some(w => w.id === targetId);
        if (exists) {
            Hyprland.dispatch("hl.dsp.focus({ workspace = " + targetId + " })");
            return;
        }

        // Target doesn't exist yet — only create it if the workspace we're
        // leaving actually has a window in it.
        clientsCheck.targetId = targetId;
        clientsCheck.currentId = current.id;
        clientsCheck.running = true;
    }

    Process {
        id: clientsCheck
        property int targetId: 0
        property int currentId: 0
        command: ["hyprctl", "clients", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                let occupied = false;
                try {
                    const arr = JSON.parse(text);
                    for (let i = 0; i < arr.length; i++) {
                        if (arr[i].workspace && arr[i].workspace.id === clientsCheck.currentId) {
                            occupied = true;
                            break;
                        }
                    }
                } catch (e) { /* ignore transient parse errors */ }
                if (occupied) {
                    Hyprland.dispatch("hl.dsp.focus({ workspace = " + clientsCheck.targetId + " })");
                }
            }
        }
    }
}

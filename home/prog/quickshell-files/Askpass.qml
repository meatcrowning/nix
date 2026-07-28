pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Wayland

// Is the sudo password dialog on screen?
//
// The `vista-askpass` app is given `dim_around` by a window rule in
// hyprland.lua, which dims the desktop and every window — but NOT this panel.
// `qs-bar` is a layer-shell surface on the `top` layer, and Hyprland renders
// that ABOVE the dim it draws for the window pass (`hyprctl layers`: "Layer
// level 2 (top): namespace: qs-bar"). So the bar stayed at full brightness
// beside a dimmed desktop. shell.qml paints its own scrim over barBody at the
// same strength instead, and this singleton is the switch.
//
// The detection is deliberately SELF-OBSERVED, off the Wayland foreign-toplevel
// list the taskbar already runs on (appId is all it carries that we need, and
// it costs no poll). No hyprctl poll, and — the important half — no IPC call
// FROM the askpass app INTO the panel: a dead or wedged panel must never be
// able to break `sudo -A`. The worst this can do is leave the bar undimmed.
Singleton {
    id: root

    // A dialog on an agent's sandbox monitor must NOT dim the bar: the window
    // it belongs to is invisible to the user, so the scrim would be the only
    // thing he saw of it — the panel darkening for no reason he can point at.
    // Same rule as the taskbar cells (WinState's OUTPUTS block).
    readonly property bool active: {
        const t = ToplevelManager.toplevels;
        const v = t ? t.values : null;
        if (!v) return false;
        for (let i = 0; i < v.length; i++)
            if ((v[i].appId || "") === "vista-askpass"
                && !WinState.offOutput(v[i].appId, v[i].title)) return true;
        return false;
    }
}

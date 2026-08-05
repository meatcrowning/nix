import QtQuick
import Quickshell.Hyprland

// THE SUPER-TAP THAT OPENS THE RUNNER, taken straight off the compositor
// instead of through a process.
//
// The bind used to be `hl.dsp.exec_cmd("qs ipc call launcher toggle")`, which
// makes Hyprland fork a shell, exec Quickshell's CLI, have it connect to the
// panel's IPC socket and exit — measured at 20-30ms on book, every tap, before
// the panel has been told anything. hyprland-global-shortcuts-v1 delivers the
// press to the running panel directly: `hl.dsp.global("quickshell:launcher")`
// in hyprland.lua, and nothing is spawned.
//
// A SEPARATE FILE BEHIND A LOADER, like HyprEvents.qml and for the same reason:
// `Quickshell.Hyprland` is an optional module, and an import of it in shell.qml
// or Launcher.qml would cost the whole panel rather than this one shortcut on a
// build without it. The IPC call it replaces is still there and still works —
// it is the scriptable/debuggable path.
QtObject {
    id: root

    signal triggered()

    // FIRE ON EITHER EVENT, and that is not belt-and-braces — it is the bug
    // that made the Meta key dead for a session. Hyprland's `global` action
    // sends the client `pressed` or `released` according to the state of the
    // KEY that ran the bind (`ConfigActions.cpp`: `sendGlobalShortcutEvent(...,
    // m_passPressed)`, and `KeybindManager.cpp`: `m_passPressed = pressed`), so
    // a `{ release = true }` bind — which is what a bare Super TAP has to be,
    // or every Super chord would open the runner — dispatches at key-up and the
    // client is told `released`. Handling only `onPressed` is a shortcut that
    // registers, binds, reports itself in `hyprctl globalshortcuts`, and never
    // once fires.
    //
    // The coalesce is for the other case: a press-type bind sends `pressed`
    // then `released`, and without it the runner would open and immediately
    // close. Our bind produces exactly one event, so it never engages here.
    property bool armed: true
    function fire() {
        if (!armed)
            return;
        armed = false;
        rearm.restart();
        root.triggered();
    }
    property var rearmTimer: Timer {
        id: rearm
        interval: 250
        onTriggered: root.armed = true
    }

    // `appid:name` is what the bind names. Keep both halves in step with
    // hyprland.lua; a shortcut nothing binds is silently inert.
    property var shortcut: GlobalShortcut {
        appid: "quickshell"
        name: "launcher"
        description: "Open the program runner"
        onPressed: root.fire()
        onReleased: root.fire()
    }
}

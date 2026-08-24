// Push KWin's own activation state down to the window's process.
//
// WHY THIS EXISTS. A window is drawn by two programs: KWin paints the
// decoration, the app paints everything below it. They decide "am I focused?"
// from different facts — KWin from the window it made active, Qt from
// wl_keyboard focus — and a screenshot tool splits the two by taking the
// keyboard without becoming the active window. Measured on `top` 2026-08-24
// off a Spectacle capture of a FOCUSED chatter: the client painted Oxygen's
// background in the INACTIVE colour group (44,62,97 at the top of the menubar)
// while the decoration painted the ACTIVE one (54,63,84 at the bottom of the
// titlebar) — one gradient, two groups, a hard seam through the middle.
//
// Nothing in Qt can see the decoration's opinion, and KWin does not advertise
// `org_kde_plasma_window_management` to ordinary clients (checked: it is absent
// from the registry a normal app sees), so an app cannot go and ask. A KWin
// script can: it has `workspace.windowActivated` and `callDBus`.
//
// The address is derived from the pid, so nothing has to be discovered and no
// daemon has to own a well-known name: a window's process either has
// `org.kde.lam.winactive.p<pid>` on the bus or the call falls on the floor,
// which is what every window that is not one of ours does. See
// apps/pylib/kwinactive.py for the receiving half.

var last = 0;

function tell(pid, active) {
    if (!pid) {
        return;
    }
    callDBus("org.kde.lam.winactive.p" + pid, "/WinActive",
             "org.kde.lam.WinActive", "setActive", active);
}

function onActivated(window) {
    var pid = window ? window.pid : 0;
    if (last && last !== pid) {
        tell(last, false);
    }
    if (pid) {
        tell(pid, true);
    }
    last = pid;
}

workspace.windowActivated.connect(onActivated);
// Whoever is active when the script loads never gets an `activated` signal.
onActivated(workspace.activeWindow);

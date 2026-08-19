// Roll up ("windowshade") the active window in a Plasma session.
//
// KWin has no shading any more: there is no shade operation in libkwin, no
// Shade entry in the window-decoration KCM's button list (verified on 6.5.5,
// 6.7.3 and 6.7.4), and no `Shade` value for the titlebar mouse commands. All
// that survives upstream is the KDecoration3 API surface with nothing behind
// it. So this cannot be a titlebar BUTTON — the decoration's button set is a
// fixed KDecoration enum the KCM builds itself from, and a script cannot add
// to it. A global shortcut is the whole of what the scripting API can reach.
//
// The emulation: remember the frame height, then resize the frame down to the
// decoration's top border, so only the titlebar is left. Rolling down restores
// the remembered height at the window's CURRENT position and width, so moving
// or side-resizing it while rolled up survives.
//
// Measured in a nested kwin 6.7.4 (virtual backend, kwrite): 648x510 frame
// rolls to 648x31 — the 26px titlebar plus the bottom border, client surface
// 1px — and back to exactly 648x510 at the same position. A scripted
// moveResize is not clamped by the window's minimum size, so kwrite's declared
// 508x150 minimum did not stop it; an X11 client with hard size hints still
// might, in which case the roll simply stops short rather than failing.
//
// A client-side-decorated window has no top border to leave behind, so it is
// skipped rather than shrunk to nothing.
//
// The Hyprland session has the real thing (hyprvtb's `rollup`, the `>>`
// titlebar button, Meta+R) — same key here on purpose.

// Below this, the "titlebar" we would leave on screen is not a titlebar.
const MIN_BAR = 4;

function barHeight(w) {
    // Decoration top border = where the client's content starts inside the
    // frame. Zero for CSD windows.
    return Math.round(w.clientGeometry.y - w.frameGeometry.y);
}

function eligible(w) {
    return !!w && w.normalWindow && w.resizeable && !w.minimized && !w.fullScreen;
}

// Geometry has to be handed over as a fresh object literal. Reading
// frameGeometry, mutating the returned copy and assigning it back is silently
// a no-op (measured in a nested kwin 6.7.4: the window never moved), and
// `Qt.rect` does not exist in KWin's script engine at all — there is no Qt
// global. An {x, y, width, height} literal is the one form that lands.
function setHeight(w, h) {
    const f = w.frameGeometry;
    w.frameGeometry = { x: f.x, y: f.y, width: f.width, height: h };
}

function rollUp(w) {
    const bar = barHeight(w);
    if (bar < MIN_BAR) {
        return; // CSD / undecorated: nothing would be left on screen
    }
    w.rollupHeight = w.frameGeometry.height;
    setHeight(w, bar);
    w.rolledUp = true;
}

function rollDown(w) {
    // A stale mark with no remembered height (script reloaded under a rolled-up
    // window) is cleared rather than obeyed — better than resizing to junk.
    if (w.rollupHeight) {
        setHeight(w, w.rollupHeight);
    }
    delete w.rolledUp;
    delete w.rollupHeight;
}

function toggleRollup() {
    const w = workspace.activeWindow;
    if (!eligible(w)) {
        return;
    }
    if (w.rolledUp) {
        rollDown(w);
    } else {
        rollUp(w);
    }
}

// Maximizing or going fullscreen while rolled up would fight the saved height;
// drop the mark instead and let the window be whatever the user just made it.
function forget(w) {
    if (w.rolledUp) {
        delete w.rolledUp;
        delete w.rollupHeight;
    }
}

function watch(w) {
    w.maximizedChanged.connect(() => forget(w));
    w.fullScreenChanged.connect(() => forget(w));
}

workspace.windowAdded.connect(watch);
workspace.windowList().forEach(watch);

registerShortcut("RollUpWindow", "Roll Up Window (Shade)", "Meta+R", toggleRollup);

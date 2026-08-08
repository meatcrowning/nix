import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Spectacle-style screenshot / screen-recording overlay (Meta+Shift+S ->
// `qs ipc call screenshot toggle`): dims the whole screen, drag a box to
// capture/record that region. A small menu at the bottom picks region (drag),
// window (windows highlight under the cursor), or fullscreen; a leftmost
// toggle flips the whole overlay between "shot" and "rec".
//
//   shot: region drag / window click / fullscreen click captures immediately.
//         Saved to the configured screenshot dir, and (optionally) copied to
//         the clipboard.
//   rec:  region / window / fullscreen only SELECT a target; a "record"
//         button (right of exit) then starts wf-recorder on it. Audio,
//         framerate and the output dir come from settings; the file goes
//         to the configured recording dir. A separate top-right toast
//         (RecordingToast.qml, driven by root.recording) is clicked to stop.
//
// The overlay itself must not appear in the shot, so capture/record closes
// the overlay first and runs grim / wf-recorder after a short settle in a
// detached shell — same fire-and-forget idiom as shell.qml's reload toast.
PanelWindow {
    id: root

    property bool open: false
    visible: open

    // Short-freeze tooltips while this overlay is up. A visible, hover-driven
    // tooltip retracts the instant this full-screen overlay steals the pointer
    // — so the capture always missed it. Hold TooltipState.frozen from open,
    // through the capture settle, then release (immediately on a plain exit).
    property bool freezePending: false
    Timer {
        id: freezeRelease
        onTriggered: TooltipState.frozen = false
    }
    function holdTools() {
        TooltipState.frozen = true;
        freezeRelease.stop();
    }
    // ms <= 0 releases now; otherwise release after a delay (the capture
    // settle + grim's own sleep) so the chip is still out when the frame grabs.
    function releaseTools(ms) {
        if (ms <= 0) {
            TooltipState.frozen = false;
            freezeRelease.stop();
        } else {
            freezeRelease.interval = ms;
            freezeRelease.start();
        }
    }
    color: "transparent"

    anchors { top: true; bottom: true; left: true; right: true }
    exclusiveZone: -1 // cover the panel bar too — the whole output dims

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-screenshot"
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    property string action: "screenshot" // "screenshot" | "record"
    property bool recording: false        // true while wf-recorder is running
    property string mode: "region" // "region" | "window" | "fullscreen"
    property int delaySec: 0       // cycles 0 -> 3 -> 5 (screenshot only)
    property var rawClients: []    // client rects straight from hyprctl (global)

    // How far the visible FRAME reaches past the client rect, read live from the
    // compositor — never a pixel literal. hyprvtb's titlebar is VERTICAL on the
    // window's RIGHT edge and is DOUBLE-wide: two columns of `bar_width`
    // (vtbDeco.cpp totalBarW() = bar_width * 2), the inner one carrying the
    // app's own buttons and the outer one the system controls. Hyprland's border
    // then wraps window + bar as a single frame (the deco's priority is above
    // the border's), so `border_size` is added on every side.
    //
    // This was `+ 32` — ONE column — so "window" mode cut the outer bar off the
    // shot, which is the whole reason these are read from `hyprctl getoption`
    // now. Same reconstruction as scripts/push-windows.py's frame_extents().
    property int vtbBarPx: 64  // fallbacks = the plugin's own defaults
    property int borderPx: 2
    property bool vtbEnabled: true
    readonly property int barPx: vtbEnabled ? vtbBarPx : 0

    // Visible window frames (global coords): the client rect grown by the border
    // on all four sides and by the bar on the right, for the windows that have
    // one. The bottom-left drop shadow is deliberately NOT included — it is cast
    // ON the desktop rather than part of the window, so a shot containing it
    // would carry a strip of whatever is behind.
    readonly property var clients: rawClients.map(c => Qt.rect(
        c.x - borderPx, c.y - borderPx,
        c.width + 2 * borderPx + (c.bar ? barPx : 0),
        c.height + 2 * borderPx))

    // Focused monitor's refresh rate + name, read from hyprctl on open — the
    // recording framerate (-r) and fullscreen output (-o) come from here.
    property int fps: 60
    property string outputName: ""

    // region-mode drag state (local coords)
    property bool selecting: false
    property real selX1: 0
    property real selY1: 0
    property real selX2: 0
    property real selY2: 0
    readonly property rect sel: Qt.rect(Math.min(selX1, selX2), Math.min(selY1, selY2),
                                        Math.abs(selX2 - selX1), Math.abs(selY2 - selY1))
    readonly property bool hasSel: sel.width > 4 && sel.height > 4

    // window-mode hover (local coords; width 0 = none)
    property rect hoverRect: Qt.rect(0, 0, 0, 0)
    readonly property bool hasHover: hoverRect.width > 0
    // In record mode a window is *picked* by clicking (it stops following the
    // cursor); this is the locked rect the "record" button then uses.
    property rect pickedRect: Qt.rect(0, 0, 0, 0)
    readonly property bool hasPick: pickedRect.width > 0

    // The dim "hole" rect currently active for the mode, or width 0.
    readonly property rect hole: mode === "region" ? (selecting || hasSel ? sel : Qt.rect(0, 0, 0, 0))
                               : mode === "window"  ? (hasPick ? pickedRect : (hasHover ? hoverRect : Qt.rect(0, 0, 0, 0)))
                                                    : Qt.rect(0, 0, 0, 0) // fullscreen: whole output, no hole

    readonly property real screenX: root.screen ? root.screen.x : 0
    readonly property real screenY: root.screen ? root.screen.y : 0

    onOpenChanged: {
        if (open) {
            // Freeze visible tooltips now, before the surface maps and steals
            // the pointer (see holdTools / TooltipState.frozen).
            holdTools();
            // A fresh invocation always starts in screenshot mode; an
            // in-flight recording keeps running independently (its toast lives
            // in RecordingToast.qml, outside this window's visibility).
            action = "screenshot";
            mode = "region";
            delaySec = 0;
            selecting = false;
            selX1 = selY1 = selX2 = selY2 = 0;
            hoverRect = Qt.rect(0, 0, 0, 0);
            pickedRect = Qt.rect(0, 0, 0, 0);
            clientsProc.running = true;
            optsProc.running = true;     // frame extents for window mode
            monitorsProc.running = true; // refresh rate + output for recording
            grab.forceActiveFocus();
        } else if (!freezePending) {
            // Plain exit (Escape / the exit button / startRecording): no
            // capture follows, so release the freeze straight away. A capture
            // keeps it armed through the settle (see capture()).
            releaseTools(0);
        }
    }

    // wf-recorder outlives quickshell reloads — a wallpaper/theme change
    // rewrites Theme.qml and recreates this whole tree, wiping `recording`
    // while the recorder keeps running. Re-detect a live recording on startup
    // so the toast comes back instead of silently vanishing mid-record.
    Component.onCompleted: recCheckProc.running = true
    Process {
        id: recCheckProc
        command: ["pgrep", "-x", "wf-recorder"]
        stdout: StdioCollector {
            onStreamFinished: root.recording = this.text.trim().length > 0
        }
    }

    // Window rects for window mode, from hyprctl (global coordinates).
    // Offscreen (minimized) windows are naturally unreachable — their rects
    // are outside the output.
    Process {
        id: clientsProc
        command: ["hyprctl", "clients", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const all = JSON.parse(this.text);
                    // The client rect, plus which classes carry a titlebar; the
                    // chrome itself is added by the `clients` binding, so the
                    // two can land in either order. A FULLSCREEN window has no
                    // bar drawn either, and its client rect already fills the
                    // output.
                    root.rawClients = all
                        .filter(c => c.mapped && !c.hidden && c.size[0] > 0)
                        .map(c => ({
                            x: c.at[0], y: c.at[1],
                            width: c.size[0], height: c.size[1],
                            // hyprvtb decorates everything except its own
                            // scratchpad, the askpass dialog (vtbNeverDecorates)
                            // and a fullscreen window.
                            bar: c.class !== "hyprvtb-scratch"
                              && c.class !== "vista-askpass"
                              && !c.fullscreen
                        }));
                } catch (e) {
                    root.rawClients = [];
                }
            }
        }
    }

    // The frame extents, from the compositor rather than from a literal. Three
    // separate `getoption` calls because it takes one key at a time; each line
    // of output is its own JSON object, so they can be parsed in any order.
    Process {
        id: optsProc
        command: ["sh", "-c",
            "hyprctl getoption -j general:border_size; " +
            "hyprctl getoption -j plugin:hyprvtb:enabled; " +
            "hyprctl getoption -j plugin:hyprvtb:bar_width"]
        stdout: StdioCollector {
            onStreamFinished: {
                const lines = this.text.trim().split("\n");
                for (let i = 0; i < lines.length; i++) {
                    let o;
                    try { o = JSON.parse(lines[i]); } catch (e) { continue; }
                    if (o.option === "general:border_size" && o.int >= 0)
                        root.borderPx = o.int;
                    else if (o.option === "plugin:hyprvtb:bar_width" && o.int > 0)
                        root.vtbBarPx = o.int * 2; // totalBarW(): inner + outer column
                    else if (o.option === "plugin:hyprvtb:enabled")
                        root.vtbEnabled = o.bool === true;
                }
            }
        }
    }

    // Focused monitor's refresh rate (-> recording framerate) and name (->
    // fullscreen output). Fractional rates (59.951) round to the nearest int.
    Process {
        id: monitorsProc
        command: ["hyprctl", "monitors", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const mons = JSON.parse(this.text);
                    const m = mons.find(x => x.focused) || mons[0];
                    if (m) {
                        root.fps = Math.max(1, Math.round(m.refreshRate));
                        root.outputName = m.name;
                    }
                } catch (e) {
                    root.fps = 60;
                    root.outputName = "";
                }
            }
        }
    }

    // Start wf-recorder on the current mode's target, then close the overlay.
    // Audio (-a) and framerate (-r) come from settings; so does the output
    // dir (~ expands to $HOME in the shell). The file is finalised when
    // RecordingToast stops us with SIGINT.
    function startRecording() {
        // -g "x,y WxH" region, or -o <output> for fullscreen.
        let flag, val;
        if (mode === "fullscreen") {
            if (!outputName) { notifyRec("no output detected"); return; }
            flag = "-o"; val = outputName;
        } else {
            let r;
            if (mode === "region") {
                if (!hasSel) { notifyRec("drag a region first"); return; }
                r = Qt.rect(screenX + sel.x, screenY + sel.y, sel.width, sel.height);
            } else { // window
                if (!hasPick) { notifyRec("click a window first"); return; }
                r = Qt.rect(screenX + pickedRect.x, screenY + pickedRect.y, pickedRect.width, pickedRect.height);
            }
            flag = "-g";
            val = Math.round(r.x) + "," + Math.round(r.y) + " " + Math.round(r.width) + "x" + Math.round(r.height);
        }

        root.open = false;
        root.recording = true;
        // fps/flag/geometry/audio/dir go through argv, never interpolated.
        // $4 (audio) is intentionally unquoted so "" contributes no argument.
        const audio = SettingsStore.d.recordingAudio ? "-a" : "";
        // Same "copy to clipboard" setting the screenshot path reads (its label
        // says "captures", plural). Raw video is not universally pasteable, so a
        // recording is copied as a text/uri-list file:// URI — that pastes as the
        // FILE into a file manager or chat, not as bytes.
        const copy = SettingsStore.d.screenshotCopy ? "1" : "0";
        Quickshell.execDetached(["sh", "-c",
            'sleep 0.2; ' +
            'd="$5"; case "$d" in "~"*) d="$HOME${d#"~"}";; esac; mkdir -p "$d"; ' +
            'f="$d/Recording_$(date +%Y%m%d_%H%M%S).mp4"; ' +
            'if wf-recorder $4 -r "$1" "$2" "$3" -f "$f"; then ' +
            '  msg="saved"; ' +
            '  if [ "$6" = "1" ]; then wl-copy --type text/uri-list "$(printf %s "file://$f" | sed "s/ /%20/g")"; msg="saved + copied"; fi; ' +
            // A poster frame for the toast thumbnail (QML Image cannot decode an
            // mp4): first frame -> a PNG in the runtime dir, handed to the panel
            // in x-download-image. x-open-path points the card's click at the
            // VIDEO, not the poster. If ffmpeg is missing/fails, the toast still
            // lands with just the open hint (no thumbnail box).
            '  t="${XDG_RUNTIME_DIR:-/tmp}/qs-rec-thumb-$(date +%s).png"; ' +
            '  if ffmpeg -y -loglevel error -i "$f" -frames:v 1 "$t" </dev/null && [ -s "$t" ]; then ' +
            '    notify-send -a recording -h "string:x-download-image:$t" -h "string:x-open-path:$f" Recording "$(basename "$f") $msg"; ' +
            '  else notify-send -a recording -h "string:x-open-path:$f" Recording "$(basename "$f") $msg"; fi; ' +
            'else notify-send -u critical -a recording Recording "recording failed"; fi',
            "_", String(SettingsStore.d.recordingFps), flag, val, audio, SettingsStore.d.recordingDir, copy]);
    }

    // Stop the running recording: SIGINT lets wf-recorder flush and finalise
    // the container (SIGKILL would corrupt it). -x matches the exact name.
    function stopRecording() {
        root.recording = false;
        Quickshell.execDetached(["pkill", "-INT", "-x", "wf-recorder"]);
    }

    function notifyRec(msg) {
        Quickshell.execDetached(["notify-send", "-a", "recording", "Recording", msg]);
    }

    // Capture a GLOBAL-coordinate region: close the overlay, settle + delay,
    // grim, save, copy, toast. Geometry goes through argv (the "$1" splice),
    // never string-interpolated into the script.
    function capture(gx, gy, gw, gh) {
        const g = Math.round(gx) + "," + Math.round(gy) + " " + Math.round(gw) + "x" + Math.round(gh);
        const wait = 0.2 + delaySec;
        const copy = SettingsStore.d.screenshotCopy ? "1" : "0";
        // The overlay must not appear in the shot, so it closes before grim —
        // but that close must not drop the tooltip freeze until the frame is
        // actually grabbed (grim runs `sleep wait` then captures). freezePending
        // stops onOpenChanged from releasing on this close; we release on a
        // timer past the settle instead.
        root.freezePending = true;
        root.open = false;
        root.freezePending = false;
        holdTools();
        releaseTools(Math.round(wait * 1000) + 600);
        Quickshell.execDetached(["sh", "-c",
            'sleep ' + wait + '; ' +
            'd="$1"; case "$d" in "~"*) d="$HOME${d#"~"}";; esac; mkdir -p "$d"; ' +
            'f="$d/Screenshot_$(date +%Y%m%d_%H%M%S).png"; ' +
            // On success, copy the PNG as an image (--type image/png, so it
            // pastes into an image editor rather than as raw text), and hand the
            // panel the file path in x-download-image so its notification card
            // draws the same 48px thumbnail + click-to-open surfer downloads get.
            'if grim -g "$2" "$f"; then ' +
            '  if [ "$3" = "1" ]; then wl-copy --type image/png < "$f"; msg="saved + copied"; else msg="saved"; fi; ' +
            '  notify-send -a screenshot -h "string:x-download-image:$f" Screenshot "$(basename "$f") $msg"; ' +
            'else notify-send -u critical -a screenshot Screenshot "capture failed"; fi',
            "_", SettingsStore.d.screenshotDir, g, copy]);
    }

    function captureLocalRect(r) {
        capture(screenX + r.x, screenY + r.y, r.width, r.height);
    }

    // Smallest visible window under a local point (smallest = the one on
    // top in the common overlap case of a dialog over its parent).
    //
    // The result is CLIPPED to this output. A frame can legitimately reach past
    // the screen edge — a window dragged half off it, or a fullscreen window
    // whose reserved extents were not applied — and `grim -g` outside the output
    // captures nothing there, so the honest region is the intersection. Clipping
    // the returned rect (rather than the ones we hit-test against) keeps the
    // pick itself unaffected, and the dim hole shows exactly what will be shot.
    function windowAt(lx, ly) {
        const gx = screenX + lx, gy = screenY + ly;
        let best = Qt.rect(0, 0, 0, 0), bestArea = -1;
        for (let i = 0; i < clients.length; i++) {
            const c = clients[i];
            if (gx >= c.x && gx <= c.x + c.width && gy >= c.y && gy <= c.y + c.height) {
                const area = c.width * c.height;
                if (bestArea < 0 || area < bestArea) {
                    const l = Math.max(0, c.x - screenX);
                    const t = Math.max(0, c.y - screenY);
                    const r = Math.min(root.width, c.x - screenX + c.width);
                    const b = Math.min(root.height, c.y - screenY + c.height);
                    // A degenerate box is a Wayland protocol error to grim and a
                    // renderRect abort to the compositor: never return one.
                    if (r - l < 1 || b - t < 1)
                        continue;
                    best = Qt.rect(l, t, r - l, b - t);
                    bestArea = area;
                }
            }
        }
        return best;
    }

    // ---- input: drag-select / window-pick, Escape exits --------------------
    MouseArea {
        id: grab
        anchors.fill: parent
        hoverEnabled: root.mode === "window"
        cursorShape: Qt.CrossCursor
        focus: true

        Keys.onEscapePressed: root.open = false

        onPressed: mouse => {
            if (root.mode !== "region")
                return;
            root.selecting = true;
            root.selX1 = root.selX2 = mouse.x;
            root.selY1 = root.selY2 = mouse.y;
        }
        onPositionChanged: mouse => {
            if (root.mode === "region" && root.selecting) {
                root.selX2 = mouse.x;
                root.selY2 = mouse.y;
            } else if (root.mode === "window") {
                root.hoverRect = root.windowAt(mouse.x, mouse.y);
            }
        }
        onReleased: {
            if (root.mode !== "region")
                return;
            root.selecting = false;
            if (!root.hasSel) {
                root.selX1 = root.selY1 = root.selX2 = root.selY2 = 0;
                return;
            }
            // screenshot: capture now. record: keep the box as the target.
            if (root.action === "screenshot")
                root.captureLocalRect(root.sel);
        }
        onClicked: {
            if (root.mode !== "window" || !root.hasHover)
                return;
            if (root.action === "screenshot")
                root.captureLocalRect(root.hoverRect);
            else
                root.pickedRect = root.hoverRect; // lock the record target
        }
    }

    // ---- dim with a hole: four bands around the active rect ----------------
    readonly property color dimColor: Qt.rgba(0, 0, 0, 0.45)
    Rectangle { color: root.dimColor; x: 0; y: 0; width: parent.width; height: root.hole.y }
    Rectangle { color: root.dimColor; x: 0; y: root.hole.y + root.hole.height; width: parent.width; height: parent.height - (root.hole.y + root.hole.height) }
    Rectangle { color: root.dimColor; x: 0; y: root.hole.y; width: root.hole.x; height: root.hole.height }
    Rectangle { color: root.dimColor; x: root.hole.x + root.hole.width; y: root.hole.y; width: parent.width - (root.hole.x + root.hole.width); height: root.hole.height }

    // selection / hover outline + size readout
    Rectangle {
        visible: root.hole.width > 0
        x: root.hole.x; y: root.hole.y
        width: root.hole.width; height: root.hole.height
        color: "transparent"
        border.color: Theme.accent
        border.width: 2

        PixelText {
            visible: root.hole.height > 24
            anchors { top: parent.top; left: parent.left; margins: 6 }
            text: Math.round(root.hole.width) + "x" + Math.round(root.hole.height)
            color: Theme.accent
            style: Text.Outline
            styleColor: Theme.bg
        }
    }

    // hint when nothing is selected yet
    PixelText {
        visible: root.hole.width === 0
        anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 40 }
        readonly property string verb: root.action === "record" ? " to record" : ""
        text: root.mode === "fullscreen" ? (root.action === "record" ? "fullscreen - press record" : "fullscreen")
            : root.mode === "region"     ? "drag to select a region" + verb
                                         : "click a window" + verb
        color: Theme.text
        style: Text.Outline
        styleColor: Theme.bg
    }

    // ---- bottom menu --------------------------------------------------------
    Rectangle {
        id: menu
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 24 }
        width: menuRow.width + 20
        height: 42
        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        // menu clicks must never fall through and start a selection
        MouseArea { anchors.fill: parent }

        Row {
            id: menuRow
            anchors.centerIn: parent
            spacing: 8

            component MenuButton: Rectangle {
                property string label
                property bool active: false
                signal clicked()
                width: t.implicitWidth + 20
                height: 28
                color: active ? Theme.bgAlt : "transparent"
                radius: Theme.windowRounding
                border.width: active ? Theme.ctrlBorder + 1 : Theme.ctrlBorder
                border.color: active ? Theme.accent : Theme.border
                PixelText { id: t; anchors.centerIn: parent; text: parent.label; color: parent.active ? Theme.accent : Theme.text }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: parent.clicked()
                }
            }

            // Flip the whole overlay between capturing a shot and a recording.
            MenuButton {
                label: root.action === "screenshot" ? "shot" : "rec"
                active: true
                onClicked: root.action = root.action === "screenshot" ? "record" : "screenshot"
            }
            MenuButton {
                label: "region"
                active: root.mode === "region"
                onClicked: {
                    root.mode = "region";
                    root.hoverRect = Qt.rect(0, 0, 0, 0);
                    root.pickedRect = Qt.rect(0, 0, 0, 0);
                }
            }
            MenuButton {
                label: "window"
                active: root.mode === "window"
                onClicked: {
                    root.mode = "window";
                    root.selecting = false;
                    root.selX1 = root.selY1 = root.selX2 = root.selY2 = 0;
                    root.pickedRect = Qt.rect(0, 0, 0, 0);
                    clientsProc.running = true; // fresh rects
                }
            }
            MenuButton {
                label: "fullscreen"
                active: root.mode === "fullscreen"
                // screenshot: capture the whole output now. record: just select
                // it as the target for the record button.
                onClicked: {
                    if (root.action === "screenshot") {
                        root.capture(root.screenX, root.screenY, root.width, root.height);
                    } else {
                        root.mode = "fullscreen";
                        root.selecting = false;
                        root.selX1 = root.selY1 = root.selX2 = root.selY2 = 0;
                        root.hoverRect = Qt.rect(0, 0, 0, 0);
                        root.pickedRect = Qt.rect(0, 0, 0, 0);
                    }
                }
            }
            MenuButton {
                visible: root.action === "screenshot"
                label: "delay: " + root.delaySec + "s"
                active: root.delaySec > 0
                onClicked: root.delaySec = root.delaySec === 0 ? 3 : (root.delaySec === 3 ? 5 : 0)
            }
            MenuButton {
                label: "exit"
                onClicked: root.open = false
            }
            // Right of exit, record mode only: start wf-recorder on the target.
            MenuButton {
                visible: root.action === "record"
                label: "record"
                active: true
                onClicked: root.startRecording()
            }
        }
    }
}

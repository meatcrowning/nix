import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Spectacle-style screenshot overlay (Meta+Shift+S -> `qs ipc call
// screenshot toggle`): dims the whole screen, drag a box to capture that
// region. A small menu at the bottom switches between region (drag) and
// window mode (windows highlight under the cursor, click captures one),
// cycles a capture delay, and exits. Shots are saved to
// ~/Pictures/Screenshots/ AND copied to the clipboard (wl-copy).
//
// The overlay itself must not appear in the shot, so capture closes the
// overlay first and runs grim after a short settle (plus the chosen delay)
// in a detached shell — same fire-and-forget idiom as shell.qml's reload
// toast.
PanelWindow {
    id: root

    property bool open: false
    visible: open
    color: "transparent"

    anchors { top: true; bottom: true; left: true; right: true }
    exclusiveZone: -1 // cover the panel bar too — the whole output dims

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-screenshot"
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    property string mode: "region" // "region" | "window"
    property int delaySec: 0       // cycles 0 -> 3 -> 5
    property var clients: []       // visible window rects (global coords)

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

    // The dim "hole" rect currently active for the mode, or width 0.
    readonly property rect hole: mode === "region" ? (selecting || hasSel ? sel : Qt.rect(0, 0, 0, 0))
                                                   : (hasHover ? hoverRect : Qt.rect(0, 0, 0, 0))

    readonly property real screenX: root.screen ? root.screen.x : 0
    readonly property real screenY: root.screen ? root.screen.y : 0

    onOpenChanged: {
        if (open) {
            mode = "region";
            delaySec = 0;
            selecting = false;
            selX1 = selY1 = selX2 = selY2 = 0;
            hoverRect = Qt.rect(0, 0, 0, 0);
            clientsProc.running = true;
            grab.forceActiveFocus();
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
                    // Expand the client rect to the full visual frame: 2px
                    // border all around plus the 32px hyprvtb titlebar on the
                    // right (the scratchpad has no titlebar).
                    root.clients = all
                        .filter(c => c.mapped && !c.hidden && c.size[0] > 0)
                        .map(c => {
                            const bar = c.class === "hyprvtb-scratch" ? 0 : 32;
                            return Qt.rect(c.at[0] - 2, c.at[1] - 2, c.size[0] + 4 + bar, c.size[1] + 4);
                        });
                } catch (e) {
                    root.clients = [];
                }
            }
        }
    }

    // Capture a GLOBAL-coordinate region: close the overlay, settle + delay,
    // grim, save, copy, toast. Geometry goes through argv (the "$1" splice),
    // never string-interpolated into the script.
    function capture(gx, gy, gw, gh) {
        const g = Math.round(gx) + "," + Math.round(gy) + " " + Math.round(gw) + "x" + Math.round(gh);
        const wait = 0.2 + delaySec;
        root.open = false;
        Quickshell.execDetached(["sh", "-c",
            'sleep ' + wait + '; ' +
            'dir="$HOME/Pictures/Screenshots"; mkdir -p "$dir"; ' +
            'f="$dir/Screenshot_$(date +%Y%m%d_%H%M%S).png"; ' +
            'if grim -g "$1" "$f"; then ' +
            '  wl-copy < "$f"; ' +
            '  notify-send -a screenshot Screenshot "$(basename "$f") saved + copied"; ' +
            'else notify-send -u critical -a screenshot Screenshot "capture failed"; fi',
            "_", g]);
    }

    function captureLocalRect(r) {
        capture(screenX + r.x, screenY + r.y, r.width, r.height);
    }

    // Smallest visible window under a local point (smallest = the one on
    // top in the common overlap case of a dialog over its parent).
    function windowAt(lx, ly) {
        const gx = screenX + lx, gy = screenY + ly;
        let best = Qt.rect(0, 0, 0, 0), bestArea = -1;
        for (let i = 0; i < clients.length; i++) {
            const c = clients[i];
            if (gx >= c.x && gx <= c.x + c.width && gy >= c.y && gy <= c.y + c.height) {
                const area = c.width * c.height;
                if (bestArea < 0 || area < bestArea) {
                    best = Qt.rect(c.x - screenX, c.y - screenY, c.width, c.height);
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
            if (root.hasSel)
                root.captureLocalRect(root.sel);
            else
                root.selX1 = root.selY1 = root.selX2 = root.selY2 = 0;
        }
        onClicked: {
            if (root.mode === "window" && root.hasHover)
                root.captureLocalRect(root.hoverRect);
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
        text: root.mode === "region" ? "drag to select a region" : "click a window"
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
                border.width: active ? 2 : 1
                border.color: active ? Theme.accent : Theme.border
                PixelText { id: t; anchors.centerIn: parent; text: parent.label; color: parent.active ? Theme.accent : Theme.text }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        Sounds.play("Windows Navigation Start.wav");
                        parent.clicked();
                    }
                }
            }

            MenuButton {
                label: "region"
                active: root.mode === "region"
                onClicked: { root.mode = "region"; root.hoverRect = Qt.rect(0, 0, 0, 0); }
            }
            MenuButton {
                label: "window"
                active: root.mode === "window"
                onClicked: {
                    root.mode = "window";
                    root.selecting = false;
                    root.selX1 = root.selY1 = root.selX2 = root.selY2 = 0;
                    clientsProc.running = true; // fresh rects
                }
            }
            MenuButton {
                label: "delay: " + root.delaySec + "s"
                active: root.delaySec > 0
                onClicked: root.delaySec = root.delaySec === 0 ? 3 : (root.delaySec === 3 ? 5 : 0)
            }
            MenuButton {
                label: "exit"
                onClicked: root.open = false
            }
        }
    }
}

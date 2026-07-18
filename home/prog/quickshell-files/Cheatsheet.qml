import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// A keybinding cheatsheet that slides out from the right, alongside the bar.
// Toggled from Hyprland via `qs ipc call cheatsheet toggle` (see shell.qml).
//
// The list is read LIVE from `hyprctl binds -j` (parsed once at startup and
// re-read on each open), so it can never drift from hypr/hyprland.lua —
// whatever binds Hyprland actually knows about are what you see. Single
// instance (like the Launcher); the card slides in horizontally from the right
// edge so it reads as pulling out from behind the panel.
PanelWindow {
    id: root

    property bool open: false

    // Stay mapped through the slide-out so the close animation can play out,
    // then hide once the card has travelled back off the right edge.
    visible: open || card.x < card.hidden - 1
    color: "transparent"

    // Fill the workspace (the bar's exclusive zone keeps the right edge off the
    // panel); the card inside is what sizes and slides.
    anchors { top: true; bottom: true; left: true; right: true }
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-cheatsheet"
    // OnDemand: accept the Escape key without permanently stealing focus,
    // matching the Launcher. Tie this to `visible` (not `open`) so the layer
    // keeps keyboard focus through the slide-out and only releases it at the
    // instant it unmaps — that unmap-while-focused is what makes Hyprland hand
    // focus back to the previous window. Releasing early (on `open`) leaves the
    // keyboard in limbo until you manually re-focus a window.
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    // ----- data -----
    property var binds: []
    // Binds bucketed by function; recomputed whenever `binds` changes.
    property var groups: buildGroups(binds)

    // Hyprland modmask bits (see wlr/xkb): SHIFT=1, CTRL=4, ALT=8, SUPER=64.
    function mods(m) {
        let s = [];
        if (m & 64) s.push("Super");
        if (m & 4)  s.push("Ctrl");
        if (m & 8)  s.push("Alt");
        if (m & 1)  s.push("Shift");
        return s;
    }

    function prettyKey(k) {
        switch ((k || "").toLowerCase()) {
        case "left":  return "←";
        case "right": return "→";
        case "up":    return "↑";
        case "down":  return "↓";
        case "":      return "•";
        }
        // Single letters read better uppercased ("q" -> "Q").
        return k.length === 1 ? k.toUpperCase() : k;
    }

    function combo(b) {
        return root.mods(b.modmask).concat([root.prettyKey(b.key)]).join(" + ");
    }

    // The readable label. Binds defined through Hyprland's Lua API report their
    // dispatcher as "__lua" with an opaque index for an arg, so the only useful
    // text is the `description` set on the bind in hyprland.lua — which is why
    // this only lists binds that carry one (see refresh()).
    function action(b) {
        return b.description || "";
    }

    // Bucket binds into functional groups off their description text, in the
    // order the categories should appear. Anything unmatched lands in "Other".
    function buildGroups(list) {
        const defs = [
            { title: "Apps",       test: d => /terminal|file manager|launcher|cheatsheet/i.test(d) },
            { title: "Window",     test: d => /close|floating|fullscreen|pseudo|toggle split|focus window|resize|move window/i.test(d) },
            { title: "Workspaces", test: d => /workspace|scratchpad/i.test(d) },
        ];
        let groups = defs.map(g => ({ title: g.title, items: [] }));
        let other = { title: "Other", items: [] };
        for (let i = 0; i < list.length; i++) {
            const b = list[i];
            const d = b.description || "";
            let placed = false;
            for (let j = 0; j < defs.length; j++) {
                if (defs[j].test(d)) { groups[j].items.push(b); placed = true; break; }
            }
            if (!placed) other.items.push(b);
        }
        let out = groups.filter(g => g.items.length > 0);
        if (other.items.length > 0) out.push(other);
        return out;
    }

    // Re-read the binds. Note we DON'T clear `binds` first: keeping the old
    // list up while the (async) reparse runs holds the card height steady, so
    // the drop-down animation has a fixed target and doesn't skip/jump.
    function refresh() {
        readProc.running = false;
        readProc.running = true;
    }

    function close() {
        open = false;
    }

    // Populate once at startup so the very first open already has a stable
    // height (and therefore a clean slide-down).
    Component.onCompleted: refresh()

    onOpenChanged: {
        if (open) {
            refresh();
            keys.forceActiveFocus();
        }
    }

    Process {
        id: readProc
        command: ["hyprctl", "binds", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                let list = [];
                try {
                    const arr = JSON.parse(this.text || "[]");
                    for (let i = 0; i < arr.length; i++) {
                        const b = arr[i];
                        // Only list binds that carry a description in hyprland.lua
                        // — that's the curated, human-readable set. (Lua binds
                        // give no other readable action text; see action().)
                        if (b.mouse || b.catch_all) continue;
                        if (!b.has_description) continue;
                        list.push(b);
                    }
                } catch (e) {
                    // leave the list empty; the card will just show its header
                }
                root.binds = list;
            }
        }
    }

    Item {
        id: keys
        anchors.fill: parent
        focus: true
        Keys.onPressed: (event) => {
            if (event.key === Qt.Key_Escape) {
                root.close();
                event.accepted = true;
            }
        }
    }

    // Clicking anywhere outside the card dismisses it.
    MouseArea {
        anchors.fill: parent
        onClicked: root.close()
    }

    Rectangle {
        id: card
        // Full workspace height, ~2/3 of its width, docked to the right — the
        // edge it slides out from — with a gap all around it.
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: Theme.gap
        anchors.bottomMargin: Theme.gap
        // Size and slide endpoints derive from the SCREEN width, not parent.width.
        // The window is only mapped (so parent.width only becomes real) on the
        // first open — one frame AFTER `open` flips true. On that very first
        // toggle parent.width is still its unmapped placeholder, which put `shown`
        // near the left edge and made the card slide in from the LEFT that once.
        // screen.width (minus the bar's exclusive zone) is known from the start,
        // so the endpoints are right on frame one and it always slides in from
        // the right. Falls back to parent.width only if screen isn't assigned yet.
        readonly property real avail: root.screen ? root.screen.width - Theme.barWidth
                                                  : parent.width
        width: Math.round(avail * 2 / 3)

        // Slide in horizontally from the right edge — out from behind the bar.
        // Open: docked at the right with a gap. Closed: fully off the right.
        readonly property real shown: avail - width - Theme.gap
        readonly property real hidden: avail
        x: root.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        // Swallow clicks on the card itself so they don't dismiss it.
        MouseArea { anchors.fill: parent }

        Column {
            id: pad
            anchors { left: parent.left; right: parent.right; top: parent.top }
            anchors.margins: 12
            spacing: 10

            // header
            PixelText {
                id: header
                text: "keybindings"
                color: Theme.accent
                font.pixelSize: Theme.fontSize + 2
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            // binds, grouped by function into wrapping columns
            Flow {
                width: parent.width
                spacing: 24

                Repeater {
                    model: root.groups
                    delegate: Column {
                        required property var modelData
                        width: 300
                        spacing: 4

                        PixelText {
                            text: modelData.title
                            color: Theme.accent
                        }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }

                        Repeater {
                            model: modelData.items
                            delegate: Row {
                                required property var modelData
                                width: 300
                                spacing: 8

                                PixelText {
                                    width: 130
                                    text: root.combo(modelData)
                                    color: Theme.text
                                    elide: Text.ElideRight
                                }
                                PixelText {
                                    width: parent.width - 138
                                    text: root.action(modelData)
                                    color: Theme.textDim
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

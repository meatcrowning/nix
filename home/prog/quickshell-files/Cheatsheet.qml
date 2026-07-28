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

    // True only for the length of a close animation, so the card's slide
    // Behavior can be gated to "opening or closing" — see the note on it. At
    // rest the card must snap to its endpoint rather than animate, or a panel
    // resize drags the shut sheet across the screen.
    property bool _closing: false
    // Mirrors the card's slide-out and must outlast it at any animScale or
    // animSpeed — hence ms(slideMs) plus a fixed frame, never a literal.
    Timer { id: closeAnim; interval: ViewMode.ms(ViewMode.slideMs) + 20; onTriggered: root._closing = false }

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
        case "left":  return "<-";
        case "right": return "->";
        case "up":    return "^";
        case "down":  return "v";
        case "":      return "*";
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
        } else {
            // arm the slide-out; see the _closing note above
            _closing = true;
            closeAnim.restart();
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
        // ViewMode.barWidth, not Theme.barWidth: the bar is only 48px wide in
        // classic mode, and in dock mode it takes a third of the screen — so
        // sizing off the fixed setting would run the card under the panel.
        //
        // Sized off ViewMode.screenWidth and NOTHING belonging to this window —
        // not parent.width, and not root.screen either. Both are properties of
        // where the window is MAPPED, and mapping depends on `visible`, which is
        // derived from card.x, which is derived from this: Qt reported it as
        // "Binding loop detected for property avail" with each of them in turn.
        // (This is a single instance, not one per monitor, so root.screen was
        // never load-bearing here anyway.)
        readonly property real avail: ViewMode.screenWidth - ViewMode.barWidth
        width: Math.round(avail * 2 / 3)

        // Slide in horizontally from the right edge — out from behind the bar.
        // Open: docked at the right with a gap. Closed: fully off the right.
        readonly property real shown: avail - width - Theme.gap
        readonly property real hidden: avail
        x: root.open ? shown : hidden
        // A CLOSED card must never animate. `hidden` is derived from `avail`,
        // which changes every time the panel is resized — and with the Behavior
        // unconditionally on, that change animated the closed card from its old
        // resting place to its new one over 220ms. Because the window's
        // `visible` is derived from `x < hidden`, that mapped the surface and
        // drew the card mid-slide, now left of the panel's edge: the keybindings
        // sheet visibly swept across the desktop on every panel resize.
        //
        // Gated to opening/closing only, the resting x tracks `hidden` instantly
        // and the window never maps. General rule for these slide popups: if an
        // endpoint can move while the popup is shut, the Behavior has to be
        // gated, or the popup will animate itself into view.
        Behavior on x {
            enabled: root.open || root._closing
            NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
        }

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
                        // kitty-exact line packing: no gap between keybinding rows
                        spacing: 0

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

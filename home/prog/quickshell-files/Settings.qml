import QtQuick
import Quickshell
import Quickshell.Io

// The Settings program — its own bespoke Quickshell instance, run from the same
// config directory as the panel:
//
//     qs -p ~/.config/quickshell/Settings.qml
//
// It reuses the panel's singletons — Theme (so it recolours with the wallpaper),
// PixelText, SettingsStore (the on-disk JSON model) — with zero duplication. It
// stays resident and shows/hides via IPC (`qs ... ipc call settings toggle`) so
// toggling is instant.
//
// NAVIGATION LIVES IN THE TITLEBAR. Rather than an in-window tab strip, the page
// buttons are registered as hyprvtb inner-titlebar buttons (the same vertical
// button column filer/kitty use) — keyed by this process's PID over
// $XDG_RUNTIME_DIR/hyprvtb-buttons.sock. One button per page, plus reload and
// restore-defaults anchored to the bottom of the column. The plugin sends back
// `CLICK <id>` on press; we switch pages / reload / reset from that.
Scope {
    id: root

    // NON-RESIDENT by design. A hidden FloatingWindow does not reliably re-map
    // in Quickshell (setting visible=true after a hide leaves it unmapped —
    // that was the "can't reopen Settings without logging out" bug), so instead
    // of keeping one instance resident and toggling its visibility, we run one
    // instance PER open: the window is shown for the whole life of the process,
    // and closing it (the titlebar X, Escape, or the toggle keybind) QUITS the
    // process. The launcher starts a fresh instance next time — a freshly
    // created window always maps. Launch is a fraction of a second.

    // this quickshell process's PID (== the window's getPID() hyprvtb reads) and
    // the button socket path, both discovered once at startup below.
    property string myPid: ""
    property string sockPath: ""

    // the pages, in order. `glyph` is the 1-2 char titlebar label; `src` is a
    // sibling QML file loaded on demand.
    readonly property var pages: [
        { key: "appearance", label: "appearance", glyph: "ap", src: "SetPgAppearance.qml" },
        { key: "panel",      label: "panel",      glyph: "pn", src: "SetPgPanel.qml" },
        { key: "widgets",    label: "widgets",    glyph: "wg", src: "SetPgWidgets.qml" },
        { key: "audio",      label: "audio",      glyph: "au", src: "SetPgAudio.qml" },
        { key: "notifs",     label: "notifs",     glyph: "nf", src: "SetPgNotifs.qml" },
        { key: "apps",       label: "apps",       glyph: "ut", src: "SetPgApps.qml" },
        { key: "session",    label: "session",    glyph: "ss", src: "SetPgSession.qml" },
        { key: "system",     label: "system",     glyph: "sy", src: "SetPgSystem.qml" },
        { key: "display",    label: "display",    glyph: "ds", src: "SetPgDisplay.qml" }
    ]
    property string current: "appearance"
    function srcFor(k) {
        for (const p of pages) if (p.key === k) return p.src;
        return pages[0].src;
    }
    function labelFor(k) {
        for (const p of pages) if (p.key === k) return p.label;
        return k;
    }
    onCurrentChanged: sendButtons()

    IpcHandler {
        target: "settings"
        // An IPC call only reaches us when we're already running, so toggle and
        // hide both mean "close" -> quit; a fresh launch is what re-opens us.
        // show is a no-op (the window is already up).
        function toggle(): void { Qt.quit(); }
        function show(): void {}
        function hide(): void { Qt.quit(); }
    }

    // ---- hyprvtb titlebar buttons ----------------------------------------
    // Discover our PID and the socket path in one shot. $PPID of this sh is the
    // quickshell process (Process children are spawned by it directly), which is
    // exactly the PID hyprvtb keys button registrations on.
    Process {
        running: true
        command: ["sh", "-c",
            "printf '%s\\n%s' \"$PPID\" \"${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hyprvtb-buttons.sock\""]
        stdout: StdioCollector {
            onStreamFinished: {
                const t = (this.text || "").split("\n");
                root.myPid = (t[0] || "").trim();
                root.sockPath = (t[1] || "").trim();
                if (root.sockPath) { vtb.path = root.sockPath; vtb.connected = true; }
            }
        }
    }

    // percent-encode the wire separators so a label/tip may hold any char
    // (mirrors pylib/vtbclient.py _enc — "%" must be escaped first).
    function _enc(s) {
        return String(s).replace(/%/g, "%25").replace(/:/g, "%3A")
            .replace(/\|/g, "%7C").replace(/\n/g, "%0A").replace(/\r/g, "%0D");
    }
    // Build one REGISTER line: every page (lit when current), then
    // restore-defaults pinned to the bottom of the column (the 6th field = 1).
    // No reload/apply button: edits apply live (see the header note), so a
    // reload would only flash the window for no gain.
    function buildRegister() {
        const parts = [];
        for (const p of pages)
            parts.push(_enc(p.key) + ":" + _enc(p.glyph) + ":" + (current === p.key ? 1 : 0)
                       + ":" + _enc(p.label) + ":0:0");
        parts.push("reset:rd:0:" + _enc("restore defaults") + ":0:1");
        return "REGISTER " + myPid + " " + parts.join("|");
    }
    function sendButtons() {
        if (vtb.connected && myPid) { vtb.write(buildRegister() + "\n"); vtb.flush(); }
    }
    function onVtbLine(line) {
        const s = (line || "").trim();
        if (s.indexOf("CLICK ") === 0) {
            const id = s.substring(6).trim();
            if (id === "reset") { confirmReset.open(); return; }
            for (const p of pages) if (p.key === id) { root.current = id; return; }
        } else if (s === "WAKE") {
            sendButtons();   // window un-hidden — re-assert our buttons
        }
    }

    Socket {
        id: vtb
        parser: SplitParser { onRead: (line) => root.onVtbLine(line) }
        onConnectedChanged: if (connected) root.sendButtons()
    }
    // hyprvtb may load/reload after us; keep trying to (re)connect.
    Timer {
        interval: 3000
        repeat: true
        running: true
        onTriggered: if (!vtb.connected && root.sockPath) vtb.connected = true;
    }

    FloatingWindow {
        id: win
        title: "settings"
        implicitWidth: 640
        implicitHeight: 580
        minimumSize: Qt.size(460, 380)
        visible: true
        color: Theme.bg

        onClosed: Qt.quit()
        onVisibleChanged: if (visible) content.forceActiveFocus()

        Item {
            id: content
            anchors.fill: parent
            focus: true
            Keys.onEscapePressed: Qt.quit()

            // slim page-name header (orientation only — navigation is in the
            // titlebar). Not a button row.
            Rectangle {
                id: header
                anchors { top: parent.top; left: parent.left; right: parent.right }
                height: 30
                color: Theme.bgAlt
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: 1
                    color: Theme.border
                }
                PixelText {
                    anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
                    text: root.labelFor(root.current)
                    color: Theme.accent
                }
            }

            // ---- page body: scrollable, fills the rest ----
            KineticFlickable {
                id: scroller
                anchors { top: header.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
                anchors.margins: 16
                contentWidth: width
                contentHeight: pageLoader.item ? pageLoader.item.implicitHeight : 0
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Loader {
                    id: pageLoader
                    width: scroller.width
                    source: root.srcFor(root.current)
                }
            }

            // thin scroll indicator on the right edge of the body
            Rectangle {
                visible: scroller.contentHeight > scroller.height
                width: 3
                color: Theme.dim
                anchors.right: scroller.right
                anchors.rightMargin: -10
                y: scroller.y + (scroller.contentHeight > 0 ? scroller.contentY / scroller.contentHeight * scroller.height : 0)
                height: scroller.contentHeight > 0 ? Math.max(24, scroller.height * scroller.height / scroller.contentHeight) : 0
            }

            // confirm before wiping every setting (reuses the file browser's
            // confirm dialog); opened by the titlebar's restore-defaults button.
            BrowserConfirm {
                id: confirmReset
                text: "restore all settings to defaults?"
                onConfirmed: SettingsStore.restoreDefaults()
            }
        }
    }
}

import QtQuick
import Quickshell
import Quickshell.Wayland

// Session power menu: logout / sleep / reboot / poweroff. Slides out from
// behind the panel near the bottom — same dock point and slide behaviour as
// the OSD (OsdWindow.qml) — but wide enough to hold the option labels instead
// of the OSD's narrow numeric card. Single instance, toggled from Hyprland via
// `qs ipc call powermenu toggle` (see shell.qml).
PanelWindow {
    id: root

    property bool open: false
    property int selected: 0

    readonly property var items: [
        // Each command is user-configurable via SettingsStore; run through
        // `sh -c` so the stored string can be an arbitrary shell command.
        // Logout kills the compositor directly (`pkill Hyprland`), NOT via
        // hyprctl or loginctl — both proved to fail SILENTLY under
        // Quickshell.execDetached (which surfaces no stderr, so it reads as
        // "does nothing"):
        //   - `hyprctl dispatch exit` (classic string) is rejected by this
        //     Lua-config build (same restriction Workspaces.qml hit for
        //     workspace switching); the Lua form `hyprctl dispatch
        //     hl.dsp.exit()` worked for a while but later regressed to a
        //     silent no-op (pinned here after direct testing).
        //   - `loginctl terminate-user/-session` needs polkit `login1.manage`,
        //     which is `auth_admin_keep` here (pkcheck → challenge), so it
        //     would pop an admin prompt that execDetached can't answer.
        // A plain SIGTERM to the process is dispatch- and polkit-free; nixpkgs
        // wraps the binary (comm `.Hyprland-wrapped`), and pkill's default
        // comm-substring match hits exactly that one process — robust to the
        // wrapper/version name and it won't match the `sh -c` running it.
        // endSession: run scripts/session-exit.sh FIRST (snapshot the session +
        // "click the [x]" on every window so apps save and the next login
        // restores their positions — see confirm()). sleep is NOT an
        // end-of-session: windows stay open across suspend, so it runs bare.
        { label: "logout",   cmd: SettingsStore.d.cmdLogout,   endSession: true },
        { label: "sleep",    cmd: SettingsStore.d.cmdSleep,    endSession: false },
        { label: "reboot",   cmd: SettingsStore.d.cmdReboot,   endSession: true },
        { label: "poweroff", cmd: SettingsStore.d.cmdPoweroff, endSession: true },
    ]

    // Stay mapped through the slide-out, then hide once the card has travelled
    // back off the right edge (matching the OSD / Launcher / Cheatsheet).
    visible: open || card.x < card.hidden - 1
    color: "transparent"

    // Dock to the bottom-right, just left of the bar — reads as pulling out
    // from behind the panel near the clock.
    anchors { right: true; bottom: true }
    margins.right: Theme.gap
    margins.bottom: Theme.gap

    implicitWidth: 110
    implicitHeight: 214
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-powermenu"
    // OnDemand: accept keyboard nav without permanently stealing focus,
    // matching the Launcher / Cheatsheet. Tied to `visible` (not `open`) so
    // the layer keeps focus through the slide-out and only releases it at the
    // instant it unmaps.
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    function close() {
        open = false;
    }

    function confirm(index) {
        const item = items[index];
        if (!item) return;
        let cmd = item.cmd;
        if (item.endSession) {
            // Snapshot the session + gracefully close every window (blocks until
            // they're gone, so apps get to save), THEN run the power action.
            // Chained with `;` not `&&`: the power action MUST fire even if the
            // save/close step hiccups — logout/poweroff can never silently do
            // nothing (session-exit.sh exits 0 anyway; this is belt-and-braces).
            const exitScript = Qt.resolvedUrl("scripts/session-exit.sh").toString().replace("file://", "");
            cmd = "'" + exitScript + "' ; " + item.cmd;
        }
        // Vista's end-of-session sounds. Fired before the command because the
        // endSession path runs session-exit.sh first (it blocks until every
        // window is gone), which is exactly the gap the sound plays in; the
        // player is detached and pipewire outlives the compositor, so a logout
        // does not cut it short. Sleep gets none — it is not an end of session.
        if (item.endSession)
            Sounds.play(item.label === "logout" ? SettingsStore.d.soundLogout
                                                : SettingsStore.d.soundShutdown);
        Quickshell.execDetached(["sh", "-c", cmd]);
        close();
    }

    onOpenChanged: {
        if (open) {
            selected = 0;
            keys.forceActiveFocus();
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
            } else if (event.key === Qt.Key_Down) {
                root.selected = Math.min(root.selected + 1, root.items.length - 1);
                event.accepted = true;
            } else if (event.key === Qt.Key_Up) {
                root.selected = Math.max(root.selected - 1, 0);
                event.accepted = true;
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                root.confirm(root.selected);
                event.accepted = true;
            }
        }
    }

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        // Slide in horizontally from the right edge — out from behind the bar.
        readonly property real shown: 0
        readonly property real hidden: width
        x: root.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        Column {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            // header
            PixelText {
                id: header
                text: "power"
                color: Theme.accent
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            Repeater {
                model: root.items
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: parent.width
                    height: 32
                    color: index === root.selected ? Theme.bgAlt : "transparent"
                    radius: Theme.windowRounding
                    border.width: index === root.selected ? Theme.ctrlBorder + 1 : Theme.ctrlBorder
                    border.color: index === root.selected ? Theme.accent : Theme.border

                    PixelText {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        color: index === root.selected ? Theme.text : Theme.textDim
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        hoverEnabled: true
                        onEntered: root.selected = index
                        onClicked: root.confirm(index)
                    }
                }
            }
        }
    }
}

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
        // Root cause, finally confirmed directly: `hyprctl dispatch exit`
        // (the classic dispatch string) is rejected outright by this
        // Lua-config build — same restriction Workspaces.qml already found
        // for workspace switching (see Hyprland.dispatch calls there) — it
        // just fails silently under Quickshell.execDetached, which doesn't
        // surface stderr anywhere, so it read as "does nothing". Needs the
        // Lua dispatcher form like every other dispatch in this config.
        { label: "logout",   cmd: ["hyprctl", "dispatch", "hl.dsp.exit()"] },
        { label: "sleep",    cmd: ["systemctl", "suspend"] },
        { label: "reboot",   cmd: ["systemctl", "reboot"] },
        { label: "poweroff", cmd: ["systemctl", "poweroff"] },
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
        Quickshell.execDetached(item.cmd);
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
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

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
                    border.width: index === root.selected ? 2 : 1
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

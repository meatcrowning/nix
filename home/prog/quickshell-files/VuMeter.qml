import QtQuick
import Quickshell
import Quickshell.Io

// Stereo output VU: two thin vertical bars, left and right channel levels.
// Driven by cava in raw-ascii mode configured for 2 bars in stereo — that's
// one low-frequency bucket per channel, which tracks per-channel loudness
// closely enough to read as a VU meter. cava streams "L;R;\n" frames on
// stdout at the configured framerate; see scripts/cava-vu.conf.
Item {
    id: root

    // hovering the VU bar activates the media widget popup (wired in StatusPanel)
    signal hovered(bool h)

    property int levelL: 0 // 0-100
    property int levelR: 0

    readonly property int barW: 5
    readonly property int barH: 68
    readonly property int gapPx: 4
    readonly property int meterW: barW * 2 + gapPx   // the visual meter's width

    // Full bar width so the click/drag/scroll band covers the whole module
    // section, not just the narrow pair of bars — same treatment as the
    // eth/cpu/disk/weather text modules. The bars + volume line stay centred.
    width: parent.width
    height: barH

    Process {
        id: cavaProc
        running: true
        command: ["sh", "-c", "exec cava -p \"$HOME/.config/quickshell/scripts/cava-vu.conf\""]
        stdout: SplitParser {
            onRead: data => {
                const parts = data.split(";");
                if (parts.length >= 2) {
                    root.levelL = Math.min(100, parseInt(parts[0], 10) || 0);
                    root.levelR = Math.min(100, parseInt(parts[1], 10) || 0);
                }
            }
        }
        // cava dying (e.g. pipewire restart) shouldn't leave dead bars
        onExited: restartTimer.restart()
    }
    Timer {
        id: restartTimer
        interval: 2000
        onTriggered: cavaProc.running = true
    }

    component Channel: Item {
        property int level: 0
        width: root.barW
        height: root.barH

        Rectangle { // track
            anchors.fill: parent
            color: "transparent"
            border.width: 1
            border.color: Theme.border
        }
        Rectangle { // fill, from the bottom
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
            anchors.margins: 1
            height: Math.round((parent.height - 2) * parent.level / 100)
            color: Theme.accent
            Behavior on height { NumberAnimation { duration: 30 } }
        }
    }

    // Centred visual meter: the two channel bars plus the volume-level line.
    Item {
        id: meter
        anchors.centerIn: parent
        width: root.meterW
        height: root.barH

        Row {
            anchors.centerIn: parent
            spacing: root.gapPx
            Channel { level: root.levelL }
            Channel { level: root.levelR }
        }

        // The volume level as a horizontal line across both bars — the bar's
        // always-visible volume indicator (the volume OSD is gone).
        Rectangle {
            visible: SysInfo.volume >= 0
            x: 0
            width: parent.width
            y: Math.max(0, Math.round(root.barH * (1 - Math.max(0, SysInfo.volume) / 100)) - 1)
            height: 2
            color: SysInfo.muted ? Theme.crit : Theme.text
        }
    }

    // Full-width interaction band: click or drag anywhere across the module to
    // set the level, scroll to nudge it — you don't have to land on the bars.
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        function setFromY(y) {
            SysInfo.setVolume(100 * (1 - y / height));
        }
        onEntered: root.hovered(true)
        onExited: root.hovered(false)
        onPressed: (mouse) => setFromY(mouse.y)
        onPositionChanged: (mouse) => { if (pressed) setFromY(mouse.y); }
        onWheel: (wheel) => SysInfo.adjustVolume(wheel.angleDelta.y > 0 ? 5 : -5)
    }
}

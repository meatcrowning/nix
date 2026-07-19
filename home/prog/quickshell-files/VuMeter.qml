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

    property int levelL: 0 // 0-100
    property int levelR: 0

    readonly property int barW: 5
    readonly property int barH: 34
    readonly property int gapPx: 4

    width: barW * 2 + gapPx
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
            Behavior on height { NumberAnimation { duration: 60 } }
        }
    }

    Row {
        anchors.centerIn: parent
        spacing: root.gapPx
        Channel { level: root.levelL }
        Channel { level: root.levelR }
    }
}

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

    readonly property int barH: 68
    // Unchanged overall width, so the panel's layout doesn't move: what used to
    // be 5px + 4px gap + 5px is now one 14px track box holding two gapless
    // fills. Deliberately still ONE bucket per channel — cava's stereo mode is
    // mirrored, so asking it for 4 bars yields [L-low, L-high, R-high, R-low]
    // and the two inner (high-frequency) bars measured medians of 17/22 against
    // the outer pair's 61/69: permanent stubs, and a frequency split rather
    // than the channel level meter this is meant to be.
    readonly property int meterW: 14

    // Full bar width so the click/drag/scroll band covers the whole module
    // section, not just the narrow pair of bars — same treatment as the
    // eth/cpu/disk/weather text modules. The bars + volume line stay centred.
    width: parent.width
    height: barH

    Process {
        id: cavaProc
        running: true
        // quickshell is launched from the Fedora session with a bare PATH that
        // omits ~/.nix-profile/bin, where cava (a nix pkg) lives — so prepend it
        // or every spawn dies with "cava: not found" and the bars go dead.
        command: ["sh", "-c", "export PATH=\"$HOME/.nix-profile/bin:$PATH\"; exec cava -p \"$HOME/.config/quickshell/scripts/cava-vu.conf\""]
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

    // Centred visual meter: the two channel fills plus the volume-level line.
    Item {
        id: meter
        anchors.centerIn: parent
        width: root.meterW
        height: root.barH

        // ONE track box around both channels. Per-channel borders would put two
        // 1px lines back to back down the middle — a 2px seam, i.e. the gap this
        // was meant to close. With a shared box the fills genuinely touch.
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: 1
            border.color: Theme.border
        }

        // Fill area inside the border. Split on the shared edge (same trick as
        // MediaPanel's spectrum) so the two halves meet exactly and always add
        // up to the full inner width, whatever the rounding.
        Item {
            anchors.fill: parent
            anchors.margins: 1

            Repeater {
                model: 2
                Rectangle {
                    required property int index
                    readonly property int x0: Math.round(parent.width * index / 2)
                    readonly property int lvl: index === 0 ? root.levelL : root.levelR
                    x: x0
                    width: Math.round(parent.width * (index + 1) / 2) - x0
                    // No gamma curve here, unlike the spectrum: one bucket per
                    // channel spans the whole range, so this already sits at a
                    // measured median of 55 and p90 93. Curving it would just
                    // pin it near the ceiling and destroy the headroom.
                    height: Math.round(parent.height * lvl / 100)
                    y: parent.height - height
                    color: Theme.accent
                    // Matches the spectrum's 25ms: long enough to absorb a
                    // dropped frame, short enough not to re-add the lag that
                    // the lower noise_reduction just removed.
                    Behavior on height { NumberAnimation { duration: 25 } }
                }
            }
        }

        // The volume level as a horizontal line across both bars — the bar's
        // always-visible volume indicator (the volume OSD is gone).
        //
        // STATIC white, deliberately not a wal palette slot. The palette is
        // derived from the wallpaper and is monochromatic, so every slot in it
        // is a near-neighbour of `accent`: measured against the accent fill,
        // Theme.text contrasts 1.40:1, crit 1.49:1, ok 1.20:1 — all invisible
        // on top of a bar. That went unnoticed while the bars were 5px with a
        // 4px gap, because most of the line's length crossed background
        // (10.2:1); making them gapless put the whole line on accent. White is
        // 2.88:1 against the fill and 21:1 against the background, so it reads
        // in both places and on any wallpaper. Same precedent as
        // Theme.windowBorderInactive: a state indicator that must not recolour.
        // Muted keeps Theme.crit — muting silences the output, so the bars fall
        // to zero and that line lands on background, where crit reads 10.9:1.
        Rectangle {
            visible: SysInfo.volume >= 0
            x: 0
            width: parent.width
            y: Math.max(0, Math.round(root.barH * (1 - Math.max(0, SysInfo.volume) / 100)) - 1)
            height: 2
            color: SysInfo.muted ? Theme.crit : "#ffffff"
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
        onWheel: (wheel) => SysInfo.adjustVolume(wheel.angleDelta.y > 0 ? SettingsStore.d.volumeStep : -SettingsStore.d.volumeStep)
    }
}

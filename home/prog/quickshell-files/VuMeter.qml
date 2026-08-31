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

    // 0-100 per channel. Backed by SysInfo rather than held locally so the
    // levels survive a config reload: the bar is instantiated per-monitor
    // inside a Variants and has no stable id, whereas the SysInfo singleton is
    // reachable from shell.qml's reload-continuity wiring. Without this the
    // bars drop to the floor the instant a reload starts and spring back up
    // when cava respawns ~200ms later — the exact re-entry this is avoiding.
    // (read-only mirrors — the cava parser below writes SysInfo directly; an
    // `alias` can't target a singleton's property, only an id in this file)
    readonly property int levelL: SysInfo.vuL
    readonly property int levelR: SysInfo.vuR

    // Settable, not readonly: on a top/bottom bar the meter is only as tall as
    // the strip is (StatusPanel.vuHeight).
    property int barH: 68
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
    // The click/drag/scroll band: the whole panel width. Set explicitly rather
    // than read off `parent`, because the status panel is a positioner now and
    // its width is its content's on a horizontal bar — where this meter is not
    // drawn at all (the spectrum takes its place; StatusPanel.qml).
    property real bandWidth: -1
    width: bandWidth >= 0 ? bandWidth : parent.width
    height: barH

    // The cava process itself lives in SysInfo, NOT here. This item is
    // instantiated per MONITOR (StatusPanel is inside a Variants), so a Process
    // in this file is one cava per screen: a second display silently doubled the
    // feed, and a stale sandbox monitor was enough to do it. The levels were
    // already in the singleton for reload continuity; the reader belongs there
    // with them.

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
            border.width: Theme.ctrlBorder
            border.color: Theme.border
        }

        // Fill area inside the border. Split on the shared edge (same trick as
        // MediaPanel's spectrum) so the two halves meet exactly and always add
        // up to the full inner width, whatever the rounding.
        Item {
            anchors.fill: parent
            anchors.margins: Theme.ctrlBorder

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
                    // Theme.textDim, matching the spectrum's bars: the dim half
                    // of the palette is the level, the bright half (accent) is
                    // the marker riding on top of it.
                    color: Theme.textDim
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
        // Theme.accent, i.e. the colour the channel fills used to be — the
        // fills dropped to Theme.textDim so the line has the brighter half of
        // the palette to itself. That's what the earlier static white was
        // working around: while both were accent-adjacent the line vanished on
        // top of a bar (Theme.text measured 1.40:1 against the accent fill),
        // and gapless bars left it nowhere else to be. Against a dim fill the
        // separation comes from the palette itself, so the indicator can
        // recolour with the wallpaper again like the rest of the panel.
        // Muted keeps Theme.crit — muting silences the output, so the bars fall
        // to zero and that line lands on background, where crit reads 10.9:1.
        Rectangle {
            visible: SysInfo.volume >= 0
            x: 0
            width: parent.width
            y: Math.max(0, Math.round(root.barH * (1 - Math.max(0, SysInfo.volume) / 100)) - 1)
            height: 2
            color: SysInfo.muted ? Theme.crit : Theme.accent
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
        // Notch-based on purpose (a discrete control, see WheelNotch.qml), but
        // a notch is a fixed amount of scroll rather than one event — the old
        // sign test stepped the volume once per touchpad report.
        WheelNotch { id: notch }
        onWheel: (wheel) => {
            const n = notch.steps(wheel);
            if (n !== 0) SysInfo.adjustVolume(n * SettingsStore.d.volumeStep);
        }
    }
}

import QtQuick

// Book-only disclosure that sits UNDER the process list in the dock's
// system-info tile (TaskManagerContent gates it on Host.name === "air"). A thin
// "top v / top ^" button; a click rolls out a copy of the CPU graph sourced from
// `top` (TopStats), animated exactly like the media queue drawer — a CLIP whose
// height glides over ViewMode.slideMs on ViewMode.slideEasing, with this Item's
// implicitHeight following it so the process list above reflows up rather than
// the chart snapping in. (It lived under CpuContent in the cpu corner popup
// until 2026-08-09; moved to the dock so the reveal squishes the process list.)
//
// TopStats polls top only while this drawer is BOTH on screen and expanded, so a
// closed disclosure costs nothing (see TopStats.watch).
Item {
    id: root

    // The popup is open (hovered or pinned) — passed down by CpuPanel.
    property bool active: false
    property int pad: 10

    // PERSISTED, like the media queue's own open flag (mediaQueueOpen): a
    // disclosure the user opened should survive a panel reload and a logout, not
    // silently close on the next wallpaper change (quickshell-files/AGENTS.md —
    // anything the user changes by using a widget goes in SettingsStore).
    readonly property bool expanded: SettingsStore.d.topStatsOpen
    function setExpanded(v) { SettingsStore.d.topStatsOpen = v; SettingsStore.save(); }

    // Poll top only while visible AND open AND actually on air.
    readonly property bool wantData: active && expanded && Host.name === "air"
    onWantDataChanged: TopStats.watch(root, wantData)
    Component.onCompleted: TopStats.watch(root, wantData)
    Component.onDestruction: TopStats.watch(root, false)

    readonly property int discH: 18
    // The revealed chart's height. A MetricChart stretches to whatever it is
    // given; 150 leaves the chart body ~88px between title and legend.
    readonly property int drawerContentH: 150

    implicitWidth: 220
    implicitHeight: discH + clip.height

    // ---- the disclosure button -------------------------------------------
    Item {
        id: disc
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: root.discH

        // hairline separating the disclosure from the local chart above it
        Rectangle {
            anchors {
                left: parent.left; right: parent.right; top: parent.top
                leftMargin: root.pad; rightMargin: root.pad
            }
            height: 1
            color: Theme.border
        }
        // ASCII carets only — More Perfect DOS VGA has no triangle glyphs, and a
        // PixelText that falls back for one loses ~5px of ascent and clips.
        PixelText {
            anchors.centerIn: parent
            text: "top " + (root.expanded ? "^" : "v")
            color: (discMa.containsMouse || root.expanded) ? Theme.accent : Theme.textDim
        }
        MouseArea {
            id: discMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.setExpanded(!root.expanded)
        }
    }

    // ---- the roll-out drawer ----------------------------------------------
    Item {
        id: clip
        anchors { top: disc.bottom; left: parent.left; right: parent.right }
        height: root.expanded ? root.drawerContentH : 0
        clip: true
        // The media queue's glide, same duration and easing — and SNAPPED during
        // the settle window, so a reload that comes up with the drawer already
        // open lands in place instead of rolling out (AGENTS.md: a reload must
        // look like a state change IN PLACE, not a re-entry; gate any Behavior
        // that follows a persisted value on ViewMode.settling).
        Behavior on height {
            enabled: !ViewMode.settling
            NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
        }

        // top's CPU graph, drawn identically to the local CpuContent but bound to
        // TopStats' ring buffers. Anchored to the drawer's FULL content height
        // (not the clipped height) so it does not reflow as the clip opens.
        MetricChart {
            id: mirror
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: root.drawerContentH
            active: root.active && TopStats.reachable
            title: "top cpu"
            series: [
                { data: TopStats.tempHist, color: Theme.crit },   // temperature
                { data: TopStats.cpuHist,  color: Theme.accent }, // usage, on top
            ]

            Row {
                spacing: 12
                PixelText {
                    text: "use " + (TopStats.cpuUsage < 0 ? "--" : TopStats.cpuUsage + "%")
                    color: Theme.accent
                }
                PixelText {
                    text: "tmp " + (TopStats.cpuTemp < 0 ? "--" : TopStats.cpuTemp + "C")
                    color: Theme.crit
                }
                PixelText {
                    text: "mem " + (TopStats.memUsage < 0 ? "--" : TopStats.memUsage + "%")
                    color: Theme.text
                }
            }
        }

        // Reachability overlay — an honest message instead of a blank chart when
        // top is asleep, off the tailnet, or has no key set up yet
        // (docs/DESIGN.md §10.2: refuse visibly, never silently no-op).
        Rectangle {
            anchors.fill: parent
            visible: root.expanded && !TopStats.reachable
            color: Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: TopStats.everReached ? "top unreachable" : "connecting to top..."
                color: Theme.textDim
            }
        }
    }
}

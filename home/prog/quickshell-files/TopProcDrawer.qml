import QtQuick

// Book-only disclosure that sits UNDER the local graphs in the dock's
// system-info tile (TaskManagerContent gates it on Host.name === "air"). A thin
// "top v / top ^" button; a click rolls out a MIRROR of top's OWN square-card
// grid (MetricCardGrid sourced from TopStats — cpu, gpu, mem, net, load, vram,
// swap and fan, exactly what top shows), animated like the media queue drawer:
// a CLIP whose height glides over ViewMode.slideMs on ViewMode.slideEasing, with
// this Item's implicitHeight following it so the process list BELOW reflows down
// rather than the grid snapping in. (It dropped down under the graphs — not the
// process list — as of 2026-08-09, and mirrors top's full grid rather than just
// its cpu chart.)
//
// TopStats polls top only while this drawer is BOTH on screen and expanded, so a
// closed disclosure costs nothing (see TopStats.watch).
Item {
    id: root

    // The tile is active (dock visible / popup open) — passed down.
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
    // The revealed grid's height — the mirror's own implicit height plus a pad,
    // so it presents at exactly the size top's tile draws the same block at.
    readonly property int drawerContentH: mirror.implicitHeight + pad

    implicitWidth: 220
    implicitHeight: discH + clip.height

    readonly property color discColor:
        (discMa.containsMouse || root.expanded) ? Theme.accent : Theme.textDim

    // ---- the disclosure button -------------------------------------------
    Item {
        id: disc
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: root.discH

        // hairline separating the disclosure from the local graphs above it
        Rectangle {
            anchors {
                left: parent.left; right: parent.right; top: parent.top
                leftMargin: root.pad; rightMargin: root.pad
            }
            height: 1
            color: Theme.border
        }
        // "top" plus a caret. More Perfect DOS VGA has no triangle glyphs, and
        // "^" is NOT "v" upside down in this font — it sits hard against the
        // ascender and clips a strip this short (measured, same finding as
        // MediaContent's queue chevron). So the open state is the SAME "v",
        // mirrored about its own centre: identical shape, identical band.
        Item {
            id: label
            anchors.centerIn: parent
            width: topT.implicitWidth + 4 + caret.implicitWidth
            height: parent.height
            PixelText {
                id: topT
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                text: "top"
                color: root.discColor
            }
            PixelText {
                id: caret
                text: "v"
                color: root.discColor
                x: topT.x + topT.implicitWidth + 4
                // Rounded origin keeps NativeRendering crisp across the flip
                // (see MediaContent's chevron): an integer y maps pixel centres
                // onto pixel centres so the mirrored glyph has no AA edge.
                y: Math.round((label.height - implicitHeight) / 2)
                transform: Scale {
                    yScale: root.expanded ? -1 : 1
                    origin.y: caret.implicitHeight / 2
                }
            }
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

        // top's OWN card grid, drawn by the same component book's tile uses, but
        // sourced from TopStats' ring buffers. noGpu is false — top has an nvidia
        // GPU, so it shows the gpu/vram/fan set. wheelTarget is null: scrolling
        // top's fan card must not touch book's backlight. Anchored to the FULL
        // content height so it does not reflow as the clip opens.
        MetricCardGrid {
            id: mirror
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: implicitHeight
            active: root.active && TopStats.reachable
            src: TopStats
            noGpu: false
            wheelTarget: null
        }

        // Reachability overlay — an honest message instead of a blank grid when
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

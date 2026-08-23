import QtQuick
import "../../qmlcommon"

// player's pseudo-settings drawer, the same idiom as surfer's dark-mode panel:
// the hyprvtb titlebar lives on the window's RIGHT edge and the "st" button is
// bottom-anchored in it, so the drawer docks bottom-right and slides in from
// that edge. A transparent scrim behind it closes it on an outside click.
//
// THE HYPRLAND ROOF ONLY. The rows themselves are `SettingsPage.qml`, which in
// a Plasma session is put in a real "Configure player…" dialog instead — there
// is no titlebar edge for a drawer to slide out of there, and a KDE program's
// settings are a dialog. This file is the frame, the slide and the scrim; it
// adds no setting of its own.
//
// Controlled, not stateful: it owns no setting. `columns` is a binding onto
// Main's value and the controls only emit requests; Main writes them back
// (and persists them), which flows in through the bindings.
Item {
    id: root
    property bool open: false
    property int columns: 7
    property int minColumns: 2
    property int maxColumns: 12
    property string scanStatus: ""
    property bool scanning: false
    // Foreground tones, handed in already faded by Main (docs/DESIGN.md §3.1.1).
    // The drawer's `Theme.windowBorder` frame does NOT fade: it is the frame
    // that makes this overlay read as a window at all, and Theme already carries
    // a separate `windowBorderInactive` for a genuinely inactive frame.
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    signal closeRequested()
    signal columnsRequested(int n)
    signal rescanRequested()
    signal replayGainRequested(string mode)
    signal rgPreampRequested(real db)

    // Nothing to hit-test while it is fully retracted.
    visible: drawer.slide > 0.001

    MouseArea {
        id: scrim
        anchors.fill: parent
        onClicked: root.closeRequested()
    }

    Motion { id: motion }

    Rectangle {
        id: drawer
        // slide 0 (hidden, fully off the right edge) -> 1 (docked at the edge)
        property real slide: root.open ? 1 : 0
        // The desktop's slide (qmlcommon/Motion.qml), not a local 200ms. This
        // drawer docks to the same edge the hyprvtb titlebar is on and opens
        // next to a window that rolls; at 200 it visibly beat the roll.
        Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing } }

        width: Math.min(248, root.width - 16)
        height: Math.min(col.implicitHeight + 24, root.height - 16)
        x: root.width - slide * width
        y: Math.max(8, root.height - height - 8)   // bottom-right, by the "st" button
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.windowBorder

        // Swallow clicks so they don't reach the scrim behind.
        MouseArea { anchors.fill: parent }

        Column {
            id: col
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 8

            Item {   // header: title + close
                width: parent.width
                height: title.implicitHeight
                PixelText {
                    id: title
                    anchors.left: parent.left
                    text: "settings"
                    color: root.fgAccent
                }
                HeaderButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    label: "x"
                    // Inert here — this drawer is the Hyprland roof and is
                    // never built in a Plasma session (the rows go into a real
                    // dialog there). Stated anyway, so the rule holds for every
                    // glyph button in the app rather than for the ones that
                    // happen to be reachable.
                    iconName: "window-close"; iconOnly: true
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.closeRequested()
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.border }

            SettingsPage {
                width: parent.width
                columns: root.columns
                minColumns: root.minColumns
                maxColumns: root.maxColumns
                scanStatus: root.scanStatus
                scanning: root.scanning
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onColumnsRequested: (n) => root.columnsRequested(n)
                onRescanRequested: root.rescanRequested()
                onReplayGainRequested: (m) => root.replayGainRequested(m)
                onRgPreampRequested: (db) => root.rgPreampRequested(db)
            }
        }
    }
}

import QtQuick
import Quickshell

// The panel's SHORTCUT NOTCH: a slab that protrudes from the bar's inner edge,
// centred on it, holding a column of small icons for the desktop's own
// programs. [his] "it should appear as if the panel has a protruding notch that
// holds the icons … in the middle of the left side of the panel", "and the
// focus colored outline would go around this notch, as well."
//
// IT IS PART OF THE PANEL, NOT A THING ON THE DESKTOP. It lives inside the
// bar's own layer surface (shell.qml) rather than in a surface of its own, so
// its outline and the bar's inner-edge strip share one coordinate space — two
// surfaces would have to agree across two commits, and during a panel-width
// drag they would disagree by a frame.
//
// THE OUTLINE IS THREE RECTANGLES, NOT A BORDER, and the slab is drawn OVER the
// bar's accent strip rather than beside it. The strip runs the full height of
// the panel, uncut; this slab's own fill hides the stretch of it that crosses
// the notch's mouth, so the line reads as detouring around the notch. The top
// and bottom pieces reach one strip-width PAST the panel's face, so the join is
// a painted overlap instead of two shapes abutting — abutting is what [his]
// "two sides touching without a corner piece" was, because at this fractional
// scale each shape rounds its own edge and the corner block belongs to neither.
// The rest of the slab past that (`overlap`) is bare fill on the bar's own
// background, which is what makes the notch OPEN into the panel rather than sit
// against it as a box.
//
// WINDOWS: the bar is on the BOTTOM layer and windows draw over it — what keeps
// them off is the exclusive zone, which reserves the bar's own width. The notch
// hangs past that, so the panel reserves `NotchModel.protrusion` too. [his]
// "reserve space when a window is maximized or the user disables floating mode
// globally or per window, yes" — a tiled or maximized window stops at the
// notch, a FLOATING one may still cover it, exactly as it may cover the bar.
// The seam where a flush window meets it is NotchSeam.qml.
Item {
    id: notch

    // Which side the bar hugs — the notch protrudes the other way, and the
    // outline-less edge (the overlap) is on the bar's side.
    property bool barLeft: false
    // This panel's screen, for the one question that depends on windows.
    property var screen: null

    // A window up against the notch changes where the seals sit: with nothing
    // there they take the same `gap` as every other inset; with a window flush
    // they centre in the notch's MOUTH, evenly between the window's border and
    // the panel's own. See NotchModel (columnInsetFlush, flushOn).
    readonly property bool flush: NotchModel.flushOn(notch.screen)

    // Content and metrics live in the singleton, so nothing here has to survive
    // a reload for the panel's reservation to be right. See NotchModel.qml.
    readonly property int overlap: NotchModel.overlap
    readonly property int lineW: Theme.windowBorderWidth

    visible: NotchModel.shown
    implicitWidth: NotchModel.slabW
    implicitHeight: NotchModel.slabH
    width: implicitWidth
    height: implicitHeight

    // The slab: the bar's background, all the way under the bar body.
    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    // ---- the outline: three sides, in the bar's accent --------------------
    // How far the horizontals run: to the panel's face plus one line width, so
    // the corner is painted rather than shared between two roundings.
    readonly property int armW: notch.width - notch.overlap + notch.lineW

    Rectangle {   // the desktop-facing side
        x: notch.barLeft ? notch.width - notch.lineW : 0
        y: 0
        width: notch.lineW
        height: notch.height
        color: Theme.accent
    }
    Rectangle {   // top
        x: notch.barLeft ? notch.overlap - notch.lineW : 0
        y: 0
        width: notch.armW
        height: notch.lineW
        color: Theme.accent
    }
    Rectangle {   // bottom
        x: notch.barLeft ? notch.overlap - notch.lineW : 0
        y: notch.height - notch.lineW
        width: notch.armW
        height: notch.lineW
        color: Theme.accent
    }

    // The seals, one gap apart. The column is the width of a SEAL, not of a
    // padded cell — the hover chip is drawn around each one instead of being
    // laid out with it, so the pointer's padding never lands in the spacing.
    Column {
        id: column
        spacing: NotchModel.gap
        width: NotchModel.iconSize
        readonly property int inset: notch.flush ? NotchModel.columnInsetFlush
                                                 : NotchModel.columnInset
        x: notch.barLeft ? notch.width - inset - width : inset
        // It moves with the window that caused it: the desktop's own slide
        // (docs/DESIGN.md §6.2), the one a window rolls at.
        Behavior on x {
            enabled: !ViewMode.settling
            NumberAnimation {
                duration: ViewMode.ms(ViewMode.slideMs)
                easing.type: ViewMode.slideEasing
            }
        }
        anchors.verticalCenter: parent.verticalCenter

        Repeater {
            model: NotchModel.apps

            delegate: Item {
                id: shortcut
                required property var modelData

                width: NotchModel.iconSize
                height: NotchModel.iconSize

                // Nothing at rest — the slab is the container, and a chip under
                // every icon would be a second frame inside it. The hover fill
                // is the runner's selected-row highlight, drawn AROUND the seal
                // (and so overlapping the gap a little) rather than being the
                // thing the layout spaces.
                Rectangle {
                    anchors.centerIn: parent
                    width: NotchModel.hitSize
                    height: NotchModel.hitSize
                    radius: Theme.windowRounding
                    visible: hover.containsMouse
                    color: Theme.highlight
                }

                AppIcon {
                    anchors.fill: parent
                    iconName: shortcut.modelData.icon
                    // The focus colour, like every other program icon on this
                    // desktop (docs/DESIGN.md §12.2.1).
                    color: Theme.accent
                }

                MouseArea {
                    id: hover
                    anchors.centerIn: parent
                    width: NotchModel.hitSize
                    height: NotchModel.hitSize
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // One click launches, like the runner's rows — this desktop
                    // has no double-click-to-open vocabulary anywhere else.
                    // NixPath.launch, never entry.execute(): that leaves the app
                    // inside quickshell-panel.service's cgroup, where the next
                    // panel restart kills it (see NixPath.launch).
                    onClicked: {
                        const e = shortcut.modelData;
                        if (!e)
                            return;
                        if (e.runInTerminal)
                            NixPath.launch([SettingsStore.d.launcherTerminal, "-e"].concat(e.command));
                        else
                            NixPath.launch(e.command);
                    }
                }

                // The name, on the usual dwell — the icons carry no labels (he
                // asked for a column of small icons, and a label column would
                // widen the notch into a second panel).
                Tooltip {
                    target: shortcut
                    show: hover.containsMouse
                    text: Glyphs.px(shortcut.modelData.name || "")
                }
            }
        }
    }
}

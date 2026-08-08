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
    // floored at 2 to stay flush with the panel strip it detours (shell.qml
    // binds the strip the same way — the join is a painted overlap and the
    // two must agree)
    readonly property int lineW: Math.max(2, Theme.windowBorderWidth)

    visible: NotchModel.shown
    implicitWidth: NotchModel.slabW
    implicitHeight: NotchModel.slabH
    width: implicitWidth
    height: implicitHeight

    // The slab: the bar's background, all the way under the bar body. Its
    // desktop-facing corners follow the global rounding; the bar side is
    // extended by the radius so the rounded far corners land invisibly on the
    // bar's own identical background instead of letting the accent strip peek
    // through the mouth's corners.
    Rectangle {
        // bar side: x=0 when the bar is LEFT, x=width when it is RIGHT — the
        // extension always reaches toward the bar.
        x: notch.barLeft ? -radius : 0
        y: 0
        width: notch.width + radius
        height: notch.height
        radius: Theme.windowRounding
        color: Theme.bg
    }

    // ---- the outline, in the bar's accent ---------------------------------
    // How far the horizontals run: to the panel's face plus one line width, so
    // the corner is painted rather than shared between two roundings.
    readonly property int armW: notch.width - notch.overlap + notch.lineW

    // One bordered, ROUNDED rect instead of the old three flat strips, so the
    // desktop-facing corners take Theme.windowRounding like every other
    // outline on the desktop. The bar-side edge (and its rounded corners)
    // must not exist — the mouth OPENS into the panel — so the rect extends
    // past this clip on the bar side by radius + line width and the clip cuts
    // the arms off square exactly where the old strips ended. At rounding 0
    // this paints pixel-identically to the three strips. The tee where the
    // arms meet the panel's own strip stays square on purpose: those are
    // CONCAVE corners, and nothing else on the desktop fillets those.
    Item {
        x: notch.barLeft ? notch.overlap - notch.lineW : 0
        y: 0
        width: notch.armW
        height: notch.height
        clip: true
        Rectangle {
            readonly property int over: Theme.windowRounding + notch.lineW
            x: notch.barLeft ? -over : 0
            y: 0
            width: parent.width + over
            height: parent.height
            radius: Theme.windowRounding
            color: "transparent"
            border.width: notch.lineW
            border.color: Theme.accent
        }
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

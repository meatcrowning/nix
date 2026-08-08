import QtQuick
import QtQuick.Shapes
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
// THE OUTLINE IS A CLIPPED, ROUNDED BORDER RECT (it was three flat strips
// until 2026-08-08), and the slab is drawn OVER the bar's accent strip rather
// than beside it. The strip runs the full height of the panel, uncut; the
// slab's own fill hides the stretch of it that crosses the notch's mouth, so
// the line reads as detouring around the notch. The outline reaches one
// strip-width PAST the panel's face, so the join is a painted overlap rather
// than two shapes abutting — and with rounding on, the tees where the arms
// meet the strip take concave quarter-arc fillets (the Shapes block at the
// bottom). The slab past the face (`overlap`) is bare fill on the bar's own
// background, which is what makes the notch OPEN into the panel rather than
// sit against it as a box.
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
    // extended by the radius so the rounded far corners stay square — and the
    // whole thing is CLIPPED to the notch's own bounds, because the first cut
    // let the extension paint over whatever panel content sat beside the
    // mouth (it cropped the media card's album art).
    Item {
        anchors.fill: parent
        clip: true
        Rectangle {
            // the extension always reaches toward the bar side
            x: notch.barLeft ? -radius : 0
            y: 0
            width: notch.width + radius
            height: notch.height
            radius: Theme.windowRounding
            color: Theme.bg
        }
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
    // this paints pixel-identically to the three strips. The tees where the
    // arms meet the panel's own strip get their concave fillets below.
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

    // ---- the INNER corners of the connection: concave fillets -------------
    // Where each arm tees into the panel's edge strip, the accent line now
    // TURNS through a quarter arc instead of a hard right angle. The straight
    // stubs the arc replaces are hidden with panel-background cover rects —
    // legal because everything on the panel side of the curve is flat
    // Theme.bg; the desktop side of the curve was never painted by us at all.
    // Fillet radius = the global rounding; at 0 nothing draws and the old
    // sharp tee remains, pixel-identical.
    readonly property int filletR: Theme.windowRounding
    // centerline of the panel's strip, in notch coords
    readonly property real strokeC: (notch.barLeft ? notch.overlap - notch.lineW : notch.width - notch.overlap) + notch.lineW / 2
    readonly property real armEndX: notch.barLeft ? notch.overlap - notch.lineW : notch.armW

    Repeater {
        model: notch.filletR > 0 ? 2 : 0   // 0 = top tee, 1 = bottom tee
        delegate: Item {
            required property int index
            readonly property bool isBottom: index === 1

            // hide the strip's straight stub beside the curve — exactly from
            // the arc's tangent point to the notch edge, so no strip pixel
            // above the curve is erased without the arc repainting it
            Rectangle {
                x: notch.strokeC - notch.lineW / 2
                y: isBottom ? notch.height : notch.lineW / 2 - notch.filletR
                width: notch.lineW
                height: Math.max(0, notch.filletR - notch.lineW / 2)
                color: Theme.bg
            }
            // ...and the arm's straight stub the arc replaces
            Rectangle {
                x: notch.barLeft ? notch.strokeC - notch.lineW / 2 - 0
                                 : notch.strokeC - notch.filletR
                y: isBottom ? notch.height - notch.lineW : 0
                width: notch.filletR + notch.lineW / 2 + (notch.barLeft ? notch.lineW / 2 : 0)
                height: notch.lineW
                color: Theme.bg
            }
            Shape {
                antialiasing: true
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeWidth: notch.lineW
                    strokeColor: Theme.accent
                    fillColor: "transparent"
                    capStyle: ShapePath.FlatCap
                    PathAngleArc {
                        centerX: notch.barLeft ? notch.strokeC + notch.filletR : notch.strokeC - notch.filletR
                        centerY: isBottom ? notch.height - notch.lineW / 2 + notch.filletR
                                        : notch.lineW / 2 - notch.filletR
                        radiusX: notch.filletR
                        radiusY: notch.filletR
                        // quarter turn from the strip's vertical into the
                        // arm's horizontal, concave toward the desktop
                        startAngle: notch.barLeft ? 180 : 0
                        sweepAngle: (isBottom ? -90 : 90) * (notch.barLeft ? -1 : 1)
                    }
                }
            }
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

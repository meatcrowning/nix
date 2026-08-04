import QtQuick
import Quickshell

// The panel's SHORTCUT NOTCH: a slab that protrudes from the bar's inner edge,
// centred on it, holding a column of small icons for the desktop's own
// programs. [his] "it should appear as if the panel has a protruding notch that
// holds the icons … in the middle of the left side of the panel", "and the
// focus colored outline would go around this notch, as well."
//
// IT IS PART OF THE PANEL, NOT A THING ON THE DESKTOP. It lives inside the
// bar's own layer surface (shell.qml) rather than in a surface of its own, and
// that is the whole design:
//
//   * one coordinate space, so the accent outline meets the bar's inner-edge
//     strip exactly. Two surfaces would have to agree across two commits, and
//     during a panel-width drag they would disagree by a frame — the lesson
//     shell.qml's barBody comment already records.
//   * the panel's own stacking, so it is the bar's material, not a card on a
//     different layer that happens to touch it.
//
// WINDOWS: the bar sits on the BOTTOM layer and windows draw over it — what
// keeps them off is the exclusive zone, which reserves the bar's own width. The
// notch hangs past that, so it publishes its protrusion (ViewMode.notchPx) and
// the panel reserves that too. [his] "reserve space when a window is maximized
// or the user disables floating mode globally or per window, yes" — so a tiled
// or maximized window stops at the notch, and a FLOATING one may still cover
// it, exactly as it may cover the bar. The zone is one scalar per edge, so the
// reserved strip runs the full height and the desktop shows through it above
// and below the notch.
//
// The right edge (the panel side) has no visible outline: the slab is drawn
// `overlap` px wider than it looks and that strip sits UNDER barBody's opaque
// background, so the notch opens into the bar instead of being a box glued to
// it. The bar's accent strip is cut for exactly this item's height (shell.qml),
// so the line runs down the panel, out around the notch, and back.
Item {
    id: notch

    // Which side the bar hugs — the notch protrudes the other way.
    property bool barLeft: false

    readonly property bool enabled: SettingsStore.d.desktopIcons

    // Small, per his ask, and derived from a cell rather than a literal
    // (docs/DESIGN.md §4): the workspace square, the smallest cell the panel
    // already uses, with the seal inset inside it.
    readonly property int cellSize: Theme.wsCell
    readonly property int iconSize: cellSize - 10
    readonly property int pad: 6
    // How far the slab reaches under the bar, hiding its panel-side border.
    readonly property int overlap: 6

    // Our own programs, alphabetical: the ones tagged `Keywords=bespoke;` in
    // their desktop entry — the same test the runner sorts by (Launcher.qml's
    // `rank`), so the notch, the runner and the seal set cannot disagree and a
    // tenth app joins by shipping the keyword. `noDisplay` entries stay out,
    // which keeps the askpass dialog (launched by the desktop, never by him)
    // off it. DesktopEntries scans lazily, so touching `.values` is what makes
    // this re-run once the scan lands (the trap TaskCell.qml documents).
    readonly property var apps: {
        const all = DesktopEntries.applications.values;
        let out = [];
        for (let i = 0; i < all.length; i++) {
            const a = all[i];
            if (a.noDisplay)
                continue;
            const kw = a.keywords || [];
            for (let k = 0; k < kw.length; k++) {
                if (String(kw[k]).toLowerCase() === "bespoke") {
                    out.push(a);
                    break;
                }
            }
        }
        out.sort((x, y) => (x.name || "").localeCompare(y.name || ""));
        return out;
    }

    visible: notch.enabled && notch.apps.length > 0
    implicitWidth: cellSize + pad * 2 + overlap
    implicitHeight: apps.length * cellSize
                    + Math.max(0, apps.length - 1) * Theme.gap + pad * 2
    width: implicitWidth
    height: implicitHeight

    // Tell the panel how far to reserve. The bar's exclusive zone covers its
    // own width; this is the part that hangs past it, and without it a tiled or
    // maximized window is laid out straight over the notch.
    Binding {
        target: ViewMode
        property: "notchPx"
        value: notch.visible ? notch.width - notch.overlap : 0
    }

    // The slab. Bar background, bar accent — the same two colours the panel
    // body is made of, so it reads as the panel and not as a card sitting on
    // it. Square, because the bar's edge is.
    Rectangle {
        anchors.fill: parent
        color: Theme.bg
        border.width: 2
        border.color: Theme.accent
        radius: 0
    }

    Column {
        id: column
        spacing: Theme.gap
        width: notch.cellSize
        x: notch.barLeft ? notch.overlap + notch.pad : notch.pad
        anchors.verticalCenter: parent.verticalCenter

        Repeater {
            model: notch.apps

            delegate: Rectangle {
                id: shortcut
                required property var modelData

                width: notch.cellSize
                height: notch.cellSize
                radius: Theme.windowRounding
                // Nothing at rest — the slab is the container, and a chip under
                // every icon would be a second frame inside it. The hover fill
                // is the runner's selected-row highlight.
                color: hover.containsMouse ? Theme.highlight : "transparent"

                AppIcon {
                    anchors.centerIn: parent
                    width: notch.iconSize
                    height: notch.iconSize
                    iconName: shortcut.modelData.icon
                    // The focus colour, like every other program icon on this
                    // desktop (docs/DESIGN.md §12.2.1).
                    color: Theme.accent
                }

                MouseArea {
                    id: hover
                    anchors.fill: parent
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

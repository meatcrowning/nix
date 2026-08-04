import QtQuick
import Quickshell
import Quickshell.Wayland

// Shortcuts to the desktop's OWN programs, as a single column of small icons
// down the right of the visible desktop. [his] "can we add shortcut icons for
// the bespoke programs here to the desktop? a single column on the right side.
// small icons."
//
// WHICH PROGRAMS: the ones tagged `Keywords=bespoke;` in their desktop entry —
// the same test the runner sorts by (Launcher.qml's `rank`), so the column is
// exactly the set of our own apps and a tenth app joins it by shipping the same
// keyword, with nothing here to edit. `noDisplay` entries stay out, which keeps
// the askpass dialog (a thing the desktop launches, never the user) off it.
//
// WHERE: the right edge of the VISIBLE desktop — the screen minus whatever the
// panel covers — not the right edge of the monitor, which in dock mode is a
// third of the way under the panel. Same reading as the wallpaper's recentring
// (WallpaperLayer.qml), and it follows the panel edge live for the same reason.
// The column tops out below the edge accent and grows DOWNWARD, leaving the
// bottom-right corner to the notification toasts.
PanelWindow {
    id: root
    required property var modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    // Reserve nothing and be pushed by nothing: this sits ON the desktop, like
    // the wallpaper under it (see WallpaperLayer.qml — a surface that takes an
    // exclusive zone is switched to "Normal" mode and shrunk).
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"

    // Bottom, not Background: above the wallpaper, below every window — a
    // shortcut that floated over the program it launched would be a bug. And
    // never keyboard focus: this must not take the keyboard from what he is
    // typing into (the whole surface is his desktop, not a dialog).
    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "qs-desktop"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    visible: SettingsStore.d.desktopIcons

    // Small, per his ask, and derived from a cell rather than a literal
    // (docs/DESIGN.md §4): the workspace-square cell, the smallest the panel
    // already uses, with the icon inset inside it.
    readonly property int cellSize: Theme.wsCell
    readonly property int iconSize: cellSize - 10

    readonly property bool barRight: SettingsStore.d.barEdge !== "left"

    // Our own programs, alphabetical. DesktopEntries scans lazily, so the
    // `.values` touch is what makes this re-run once the scan lands (the same
    // trap TaskCell.qml documents).
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

    // Input reaches the icons and NOTHING else: the rest of this surface covers
    // the whole desktop, and a click on the wallpaper must stay a click on the
    // wallpaper. Explicit coordinates, the form shell.qml's bar and EdgeGrip
    // both use.
    mask: Region {
        x: column.x
        y: column.y
        width: column.width
        height: column.height
    }

    Column {
        id: column
        spacing: Theme.gap
        width: root.cellSize
        // Inside the visible desktop's right edge, which is the panel edge when
        // the bar is over there.
        x: root.width - width - Theme.gap
           - (root.barRight ? ViewMode.liveWidth : 0)
        // Clear of the top edge accent, and of the panel's own top margin.
        y: Theme.gap * 2

        Repeater {
            model: root.apps

            delegate: Rectangle {
                id: shortcut
                required property var modelData

                width: root.cellSize
                height: root.cellSize
                radius: Theme.windowRounding
                // Nothing at rest — the wallpaper is the background, and a chip
                // under every icon would read as a second panel. The hover fill
                // is the one the runner's selected row uses.
                color: hover.containsMouse ? Theme.highlight : "transparent"
                border.width: hover.containsMouse ? 1 : 0
                border.color: Theme.border

                AppIcon {
                    anchors.centerIn: parent
                    width: root.iconSize
                    height: root.iconSize
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
                // asked for a column of small icons, and a label column would be
                // a second panel down the desktop).
                Tooltip {
                    target: shortcut
                    show: hover.containsMouse
                    text: Glyphs.px(shortcut.modelData.name || "")
                }
            }
        }
    }
}

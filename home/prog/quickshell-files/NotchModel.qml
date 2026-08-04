pragma Singleton
import Quickshell
import QtQuick

// Everything about the shortcut notch that ISN'T drawing: which programs are in
// it, and how big the slab therefore is. DesktopNotch.qml renders this;
// ViewMode reads it for the panel's reservation; NotchSeam.qml reads it for the
// span it has to cover.
//
// IT IS A SINGLETON ON PURPOSE, and the reason is a bug that came back twice.
// The notch used to publish its size INTO ViewMode with a `Binding`. A reload
// builds the new panel tree and then tears the old one down, and ViewMode
// survives both — so the outgoing notch wrote its dying value (0, its item
// going invisible during teardown) over the incoming one's, the panel then
// reserved nothing for the notch, and a maximized window covered the icon bar
// completely. `restoreMode: Binding.RestoreNone` does not fix it: the binding is
// live until it is destroyed, so it is not the RESTORE that writes the zero, it
// is the last evaluation.
//
// So nothing pushes. The numbers are DERIVED, here, from things that outlive a
// reload (the settings store, the desktop-entry index, the theme), and every
// consumer pulls. There is no window of time in which they can be wrong.
Singleton {
    id: root

    readonly property bool enabled: SettingsStore.d.desktopIcons

    // Small, per his ask, and derived from a cell rather than a literal
    // (docs/DESIGN.md §4): the workspace square, the smallest cell the panel
    // already uses, with the seal inset inside it.
    readonly property int cellSize: Theme.wsCell
    readonly property int iconSize: cellSize - 10
    // How far the slab reaches under the bar body, so its panel-side edge has
    // no outline and the notch opens INTO the panel.
    readonly property int overlap: 6
    readonly property int lineW: Theme.windowBorderWidth

    // THE TWO GAPS AROUND AN ICON ARE THE SAME GAP, and neither is measured to
    // the notch's own right edge — that edge is under the bar and nobody can
    // see it. [his] "can you make it so the space between the icons on the left
    // and right of the bar is the same? … based on the left edge of the bar,
    // and the edge of the widgets in the panel, not the right side of the bar."
    //
    // To the right of an icon the eye crosses the rest of the notch, then the
    // panel's face, and stops at the panel's own content — which is inset by
    // `Theme.gap` (shell.qml's dockLayout margins). So the right-hand gap is
    // `gapRight + panelInset`, and the left-hand one has to be that whole
    // distance for the icon to sit centred BETWEEN WHAT IS VISIBLE.
    readonly property int gapRight: 6
    readonly property int panelInset: Theme.gap
    readonly property int gapLeft: gapRight + panelInset
    // Where the column starts inside the slab, measured from the outlined side.
    readonly property int columnInset: lineW + gapLeft

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

    readonly property bool shown: enabled && apps.length > 0

    // The whole slab, overlap included...
    readonly property int slabW: columnInset + cellSize + gapRight + overlap
    // Vertically the notch is its own container, so the top and bottom insets
    // are the plain gap either end — there is no panel content to line up with.
    readonly property int padV: 6
    readonly property int slabH: shown
        ? apps.length * cellSize + Math.max(0, apps.length - 1) * Theme.gap + padV * 2
        : 0
    // ...and the part of it that sticks out past the bar, which is what the
    // panel has to reserve and what a window can be flush against.
    readonly property int protrusion: shown ? slabW - overlap : 0
}

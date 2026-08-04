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
    readonly property int pad: 6
    // How far the slab reaches under the bar body, so its panel-side edge has
    // no outline and the notch opens INTO the panel.
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

    readonly property bool shown: enabled && apps.length > 0

    // The whole slab, overlap included...
    readonly property int slabW: cellSize + pad * 2 + overlap
    readonly property int slabH: shown
        ? apps.length * cellSize + Math.max(0, apps.length - 1) * Theme.gap + pad * 2
        : 0
    // ...and the part of it that sticks out past the bar, which is what the
    // panel has to reserve and what a window can be flush against.
    readonly property int protrusion: shown ? slabW - overlap : 0
}

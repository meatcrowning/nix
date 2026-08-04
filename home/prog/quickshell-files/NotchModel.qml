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

    // ---- ONE GAP, EVERYWHERE, MEASURED ICON-BOX TO EDGE ------------------
    // [his] "the current padding between the top of the top icon and the top
    // edge of the bar, can you use that as a guide for the left and right
    // padding … and also for the padding between the icons themselves."
    //
    // THE UNIT IS `gap`, and everything is measured from the same two things:
    // the seal's own box, and the INNER edge of the bar's outline. That is the
    // fix as much as the number is — the top padding used to be measured from
    // the slab's OUTER edge and the left from the border's inner one, so
    // "6 and 6" drew as 9.6 and 11.4 (measured), and no amount of matching the
    // constants would have made them look equal.
    //
    // Every one of these is `gap`:
    //   the bar's top edge  -> the first seal's box
    //   seal box            -> seal box
    //   the bar's left edge -> a seal's box
    //   a seal's box        -> the panel's widgets  (§12.2.2: measured to what
    //                                                is visible, not to the
    //                                                notch's hidden edge)
    //
    // 9 is what the top padding already was in these units, so his guide is
    // preserved exactly and the others come to it.
    readonly property int iconSize: 22
    readonly property int gap: 9
    // The hover chip and click target, drawn around the seal rather than laid
    // out with it: a layout cell padded for the pointer would put its padding
    // into every gap twice, which is what made "equal spacing" impossible to
    // express before (two cell insets between seals, one against an edge).
    readonly property int hitSize: iconSize + 8

    // How far the slab reaches under the bar body, so its panel-side edge has
    // no outline and the notch opens INTO the panel.
    readonly property int overlap: 6
    readonly property int lineW: Theme.windowBorderWidth
    // The panel's own content margin (shell.qml's dockLayout anchors.margins)
    // is part of the right-hand gap. It is wider than the unit, so the seals
    // sit a hair past the panel's face for the gap to the WIDGETS to be `gap`.
    // Invisible: the notch's mouth opens into the panel there.
    readonly property int panelInset: Theme.gap
    readonly property int columnInset: lineW + gap
    readonly property int gapRight: gap - panelInset

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
    readonly property int protrusion0: columnInset + iconSize + gapRight
    readonly property int slabW: protrusion0 + overlap
    readonly property int slabH: shown
        ? apps.length * iconSize + Math.max(0, apps.length - 1) * gap
          + 2 * (lineW + gap)
        : 0
    // ...and the part of it that sticks out past the bar, which is what the
    // panel has to reserve and what a window can be flush against.
    readonly property int protrusion: shown ? protrusion0 : 0
}

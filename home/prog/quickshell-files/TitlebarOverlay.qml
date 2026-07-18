import QtQuick
import Quickshell
import Quickshell.Wayland

// ONE fullscreen, transparent, top-layer surface hosting every titlebar as
// a WindowTitlebar Item. One surface instead of one-per-window means a
// moving titlebar is just an Item.x/y change rendered on the next frame —
// no per-surface layer-shell configure round-trip, no map/unmap churn —
// which is what makes drag-follow feel attached.
//
// Because the surface covers the whole screen, its input region must be
// only the union of the titlebars' visible slices: everywhere else —
// including the parts of a titlebar covered by a window stacked above it —
// pointer events fall through to whatever is underneath. Region{item}
// tracks item geometry live, so the mask only needs rebuilding when the
// slice SET changes (windows opening/closing, occlusion intervals
// appearing/disappearing), not while things merely move.
PanelWindow {
    id: root

    // Single-monitor box (see CLAUDE.md) — same assumption
    // WindowTracker._monitorSize() makes.
    screen: Quickshell.screens[0]

    anchors { top: true; bottom: true; left: true; right: true }
    exclusiveZone: -1
    color: "transparent"

    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "qs-window-titlebars"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    property var maskRegions: []
    mask: Region { regions: root.maskRegions }

    Component {
        id: regionComp
        Region {}
    }

    function rebuildMask() {
        const regs = [];
        for (let i = 0; i < titlebars.count; i++) {
            const tb = titlebars.itemAt(i);
            if (!tb) continue;
            for (let j = 0; j < tb.sliceCount(); j++) {
                const s = tb.sliceAt(j);
                if (s) regs.push(regionComp.createObject(root, { item: s }));
            }
        }
        const old = root.maskRegions;
        root.maskRegions = regs;
        for (let i = 0; i < old.length; i++) old[i].destroy();
    }
    // Slice add/remove signals arrive in bursts (one per slice); coalesce.
    function scheduleMaskRebuild() { Qt.callLater(root.rebuildMask); }

    Repeater {
        id: titlebars
        model: WindowTracker.windows

        WindowTitlebar {
            onSlicesChanged: root.scheduleMaskRebuild()
        }
    }
}

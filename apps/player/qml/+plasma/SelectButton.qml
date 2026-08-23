import QtQuick
import QtQuick.Controls

// SelectButton, in a Plasma session: a real ComboBox, drawn and popped by the
// live KStyle — Oxygen's own frame, its own arrow and its own dropdown at its
// own metrics.
//
// It was a Button with a hand-drawn "▾" glyph in a Text indicator until
// 2026-08-23, under a comment claiming the style drew the arrow. It did not:
// that character was the app painting a control affordance in a session whose
// whole point is that it does not (apps/AGENTS.md → kdeshell — "we do not
// imitate the system theme; we let the system theme paint"). There is no QQC2
// primitive that hands out the style's arrow on its own — Oxygen draws it as
// part of the whole combo — so the answer is the whole combo, which is what a
// KDE program's pick-one-of-N is anyway. Same choice painter's
// `+plasma/Picker.qml` already made.
//
// §7.2's "no combo box anywhere on this desktop" is the HYPRLAND rule and the
// sibling still keeps it; this face is the other session's, where the desktop's
// own vocabulary is KDE's.
//
// Same API as ../SelectButton.qml — `label` is what the box shows, `options` is
// the list, `chose(value)` is the pick — so no call site changes. `picked` is
// never emitted here: there is no shared CtxMenu to open, the style's popup IS
// the menu, and §7.3's one-popup-at-a-time is the toolkit's problem.
Item {
    id: root
    property string face: "plasma"
    property string label: ""
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property var options: []

    signal picked(real sceneX, real sceneY, var items)
    signal chose(var value)

    function menuItems() { return []; }

    // The labels, for the model; the values are read back out of `options` by
    // the index the style hands back.
    readonly property var _labels: {
        var out = [], list = root.options || [];
        for (var i = 0; i < list.length; i++) {
            var o = list[i];
            out.push((o !== null && typeof o === "object" && o.label !== undefined)
                     ? String(o.label) : String(o));
        }
        return out;
    }
    function _valueAt(i) {
        var list = root.options || [];
        if (i < 0 || i >= list.length) return "";
        var o = list[i];
        return (o !== null && typeof o === "object" && o.value !== undefined)
             ? o.value : String(o);
    }

    implicitWidth: 110
    implicitHeight: box.implicitHeight
    height: implicitHeight

    ComboBox {
        id: box
        anchors.fill: parent
        model: root._labels
        // CONTROLLED, like every other control in this app: the owner binds
        // `label` to the live setting and the combo only reports. `currentIndex`
        // is derived from that label rather than owned, so a value the owner
        // refuses (or rewrites) shows what the owner actually holds — and
        // `displayText` covers the case where nothing in the list matches.
        currentIndex: {
            var labels = root._labels;
            for (var i = 0; i < labels.length; i++)
                if (labels[i] === root.label) return i;
            return -1;
        }
        displayText: root.label
        onActivated: (i) => root.chose(root._valueAt(i))
    }
}

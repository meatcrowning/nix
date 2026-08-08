import QtQuick

// A closed dropdown: a label, a `v`, and a `CtxMenu` under it.
//
// There are TWO of these in the column beside the box he types in — which model
// orchestrates, and how many agents may run at once — and they are ONE
// component because they are one control. [his, 2026-07-29] the second one is
// *"another drop down"* in the same idiom as the first, and a second hand-rolled
// copy of the chrome is how two controls that must look identical stop being
// identical (docs/DESIGN.md §19.1 — the four scrollbars, folded).
//
// Everything about how it LOOKS is here and nothing about it is the call site's:
// §7.2 says menus on this desktop are ours and are `CtxMenu`, so this is that
// menu with a resting label, never a combo box. The tick beside the live entry
// is the caller's — it comes from the store the control writes, so the control
// cannot disagree with what will actually happen.
Item {
    id: pick

    //: what the closed control reads. Prose, never a wire value (§2).
    property string label: ""
    //: the line its TOOLTIP shows while the pointer is on it. It says what
    //  changes AND when it takes effect — the second half is the whole promise.
    //
    //  It used to be written into the window's `status`, which is the footer the
    //  hyprvtb bar draws — so hovering this control made text appear in the
    //  inner titlebar, his *"stray text ... in the inner sidebar"*. §8 is where
    //  a hover explanation belongs; the footer is for a REPORT of something that
    //  happened (§10), and this control's own comment already said so.
    property string hint: ""
    //: `[{label, trigger}]`, built by the caller. Called on every open, so the
    //  tick is read fresh rather than cached.
    property var items: () => []
    //: the menu to open it in (named `popup` so a call site can write
    //  `popup: menu` without the id resolving to this property instead) — the window's one `CtxMenu` (§7.3).
    property var popup: null

    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    //: pad the label out to this many characters, so that two of these stacked
    //  put their `v` in the SAME COLUMN. They are centred and the font is
    //  monospace, so a label one character shorter than its neighbour's moved
    //  the arrow half a cell — measured offscreen at 845 against 849, which is
    //  [his] *"the down arrows of the two dropdowns are not vertically aligned"*.
    //  The caller knows both labels and so owns the number; 0 means no padding
    //  and one of these on its own needs none.
    property int padTo: 0
    readonly property string pad: {
        var s = "";
        for (var i = pick.label.length; i < pick.padTo; i++)
            s += " ";
        return s;
    }

    // One font cell plus the padding every small control here uses, so the two
    // of them stack as equal rungs.
    implicitWidth: pickText.implicitWidth + 16
    implicitHeight: Theme.lineHeight + 6
    width: implicitWidth
    height: implicitHeight

    // The hover STATE is a `HoverHandler`, not the MouseArea's `containsMouse`:
    // the tooltip below is a `MouseArea` too and sits on top, so it would take
    // the hover off a `containsMouse` and the border would never light. A
    // handler is passive and the two do not fight — `UsageMeter` pairs them the
    // same way for the same reason.
    HoverHandler { id: hov }

    Rectangle {
        anchors.fill: parent
        radius: 3
        color: hov.hovered ? Theme.highlight : "transparent"
        border.width: 1
        border.color: hov.hovered ? Theme.accent : Theme.border
    }
    PixelText {
        id: pickText
        anchors.centerIn: parent
        // `v` is the one glyph this font does have for "opens downward" - §2.3
        // rules out the triangles, and the section bands already use this ASCII
        // vocabulary.
        text: pick.label + pick.pad + "  v"
        color: hov.hovered ? pick.fgAccent : pick.fgDim
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            // Under the control's bottom-left, in window coordinates - the menu
            // fills the window and clamps itself back into view.
            var p = mapToItem(null, 0, height);
            if (pick.popup)
                pick.popup.open(p.x, p.y, pick.items());
        }
    }
    ToolTipArea {
        anchors.fill: parent
        text: pick.hint
    }
}

import QtQuick

// A colour picker as a swatch + text field. `value` is a "#rrggbb" string,
// two-way; changed(hex) fires when a valid colour is committed. The field takes
// a hex OR a colour name ("tomato", "rebeccapurple") — a name is normalised to
// hex before it is emitted, so every consumer still stores and reads hex.
// Invalid text just doesn't apply.
//
// With `picker` on, clicking the swatch opens a grid of colours to pick from
// instead of re-committing the field. The grid is parented to the WINDOW's
// contentItem for the same reason SetSelect's menu is: the settings pages live
// in a clipped Flickable and a child popup would be cut off at the viewport.
Row {
    id: root
    property string value: "#000000"
    property bool picker: false
    signal changed(string hex)

    // `enabled` is the built-in Item property — it already blocks the swatch
    // and the field (input cascades); this adds the greyed look, so a caller
    // gating on a sibling setting gets both halves of "greyed out" (§10.1).
    opacity: enabled ? 1.0 : 0.4

    spacing: 8

    function _hex(s) { return /^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.test((s || "").trim()); }

    // Names go through Qt's own table. An unknown name yields an invalid
    // QColor, which stringifies to #000000 — indistinguishable from real black,
    // so black is the one name that is matched literally rather than parsed.
    function _norm(s) {
        const t = (s || "").trim();
        if (!t.length) return "";
        if (root._hex(t)) return Qt.color(t).toString();
        const l = t.toLowerCase();
        if (!/^[a-z]+$/.test(l)) return "";
        if (l === "black") return "#000000";
        const c = Qt.color(l).toString();
        return (c === "#000000") ? "" : c;
    }

    function _commit(t) {
        const h = root._norm(t);
        if (h.length) root.changed(h);
    }

    Rectangle {
        id: chip
        width: 22
        height: 22
        anchors.verticalCenter: parent.verticalCenter
        color: root._hex(root.value) ? root.value : Theme.bgAlt
        radius: Theme.windowRounding
        border.width: Theme.ctrlBorder
        border.color: (sw.containsMouse || root._grid) ? Theme.accent : Theme.border
        MouseArea {
            id: sw
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (root.picker) root.openGrid()
        }
    }

    SetTextField {
        id: field
        anchors.verticalCenter: parent.verticalCenter
        fieldWidth: 90
        value: root.value
        placeholder: root.picker ? "hex or name" : "#rrggbb"
        // Controlled: emit only; `value` stays bound to the store.
        onCommitted: (t) => root._commit(t)
    }

    // ---- the swatch grid -------------------------------------------------
    property var _grid: null
    function openGrid() {
        if (_grid) return;
        const win = root.Window.window;
        if (!win) return;
        _grid = gridComp.createObject(win.contentItem, { prevFocus: win.activeFocusItem });
    }

    // 12 hues across, 5 values down, plus a greyscale row — enough to land on a
    // colour by eye, with the field beside it for anything exact.
    readonly property var _hues: [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]
    readonly property var _levels: [0.95, 0.78, 0.60, 0.42, 0.26]
    function _cell(col, rowIdx) {
        if (rowIdx === root._levels.length)
            return Qt.hsla(0, 0, col / (root._hues.length - 1), 1);
        return Qt.hsla(root._hues[col] / 360, 0.62, root._levels[rowIdx], 1);
    }

    Component {
        id: gridComp
        FocusScope {
            id: overlay
            property Item prevFocus: null
            anchors.fill: parent
            z: 1000
            focus: true
            Component.onCompleted: forceActiveFocus()

            function dismiss() {
                root._grid = null;
                if (prevFocus && prevFocus.forceActiveFocus) prevFocus.forceActiveFocus();
                overlay.destroy();
            }
            Keys.onEscapePressed: dismiss()

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                onClicked: overlay.dismiss()
                onWheel: (w) => { w.accepted = true; }
            }

            Rectangle {
                id: gbox
                readonly property int cell: 18
                readonly property int cols: root._hues.length
                readonly property int rows: root._levels.length + 1
                readonly property point at: chip.mapToItem(overlay, 0, chip.height + 1)
                x: Math.max(0, Math.min(at.x, overlay.width - width))
                y: Math.max(0, Math.min(at.y, overlay.height - height))
                width: cols * cell + 2
                height: rows * cell + 2
                color: Theme.bgAlt
                border.width: Theme.ctrlBorder
                border.color: Theme.border
                radius: Math.max(3, Theme.windowRounding)

                HoverHandler {
                    id: hov
                    onHoveredChanged: hovered ? leave.stop() : leave.restart()
                }
                Timer {
                    id: leave
                    interval: 400
                    onTriggered: if (!hov.hovered) overlay.dismiss()
                }

                Repeater {
                    model: gbox.cols * gbox.rows
                    Rectangle {
                        id: cellRect
                        required property int index
                        readonly property int col: index % gbox.cols
                        readonly property int rowIdx: Math.floor(index / gbox.cols)
                        readonly property color c: root._cell(col, rowIdx)
                        x: 1 + col * gbox.cell
                        y: 1 + rowIdx * gbox.cell
                        width: gbox.cell
                        height: gbox.cell
                        color: c
                        // The hovered cell is named by a border, not by a size
                        // change — a grid that reflows under the pointer is
                        // impossible to aim at.
                        border.width: cma.containsMouse ? Theme.ctrlBorder : 0
                        border.color: Theme.text
                        MouseArea {
                            id: cma
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                root.changed(cellRect.c.toString());
                                overlay.dismiss();
                            }
                        }
                    }
                }
            }
        }
    }
}

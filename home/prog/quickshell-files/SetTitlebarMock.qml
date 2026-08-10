import QtQuick

// An interactive mock of the hyprvtb titlebar (docs/DESIGN.md §12): a preview
// window you shape by direct manipulation, wired to the three GLOBAL bar knobs
// and nothing else. There is no global config key for WHICH buttons show or
// their order/side — the inner column is each app declaring its own cells over
// the vtbclient socket — so this control is deliberately the three global knobs
// only (the board decision of 2026-08-09: build the picker for edge/orientation/
// compact, no per-button show/hide).
//
//   click a SIDE of the window  -> titlebar side    (right/left/top/bottom)
//   click the CELLS end of bar  -> compact          (single vs double column)
//   click the TITLE on the bar  -> title orientation (vertical/horizontal)
//
// Each writes SettingsStore.d and saves; SettingsApply.qml's Connections push
// the change live over hl.config, exactly as the plain rows it replaces did —
// so no apply wiring changed. A caption under the stage names all three current
// values, and a second line names the gestures, so nothing here can silently
// no-op or hide its state (§10).
Column {
    id: root
    spacing: 8

    readonly property var d: SettingsStore.d
    readonly property string edge: d.titlebarEdge
    readonly property bool compact: d.compact
    readonly property bool horiz: d.titleOrientation === "horizontal"
    readonly property bool vbar: edge === "right" || edge === "left"

    function setEdge(e) { if (e !== d.titlebarEdge) { d.titlebarEdge = e; SettingsStore.save(); } }
    function toggleCompact() { d.compact = !d.compact; SettingsStore.save(); }
    function toggleOrient() { d.titleOrientation = horiz ? "vertical" : "horizontal"; SettingsStore.save(); }

    Item {
        id: stage
        width: 260
        height: 172

        property string hoverEdge: ""

        readonly property int m: 28                       // edge gutter = click margin
        readonly property int bodyX: m
        readonly property int bodyY: m
        readonly property int bodyW: width - 2 * m
        readonly property int bodyH: height - 2 * m
        readonly property int thick: root.compact ? 11 : 22
        readonly property int cellS: Math.max(3, thick - 8)
        readonly property int cellsLen: 5 * (cellS + 2) + 4  // 5 system cells

        // geometry of the bar (or a ghost) sitting on edge e, in stage coords
        function bx(e) { return e === "right" ? bodyX + bodyW - thick : bodyX; }
        function by(e) { return e === "bottom" ? bodyY + bodyH - thick : bodyY; }
        function bw(e) { return (e === "right" || e === "left") ? thick : bodyW; }
        function bh(e) { return (e === "right" || e === "left") ? bodyH : thick; }

        // ---- the mock window body ----
        Rectangle {
            id: body
            x: stage.bodyX; y: stage.bodyY; width: stage.bodyW; height: stage.bodyH
            color: Theme.bg
            radius: Theme.windowRounding
            border.width: 2
            border.color: Theme.windowBorder
        }

        // ---- ghost preview of the bar at a hovered, non-current edge ----
        Rectangle {
            visible: stage.hoverEdge !== "" && stage.hoverEdge !== root.edge
            x: stage.bx(stage.hoverEdge); y: stage.by(stage.hoverEdge)
            width: stage.bw(stage.hoverEdge); height: stage.bh(stage.hoverEdge)
            color: "transparent"
            border.width: 2
            border.color: Theme.border
            opacity: 0.7
        }

        // ---- the live bar on the current edge ----
        Rectangle {
            id: bar
            x: stage.bx(root.edge); y: stage.by(root.edge)
            width: stage.bw(root.edge); height: stage.bh(root.edge)
            color: Theme.bgAlt
            border.width: 2
            border.color: Theme.accent

            // system cells — five little squares at the window-adjacent end
            Repeater {
                model: 5
                Rectangle {
                    required property int index
                    width: stage.cellS; height: stage.cellS
                    x: root.vbar ? (stage.thick - stage.cellS) / 2
                                 : 3 + index * (stage.cellS + 2)
                    y: root.vbar ? 3 + index * (stage.cellS + 2)
                                 : (stage.thick - stage.cellS) / 2
                    color: "transparent"
                    border.width: 1
                    border.color: Theme.accent
                }
            }

            // the title — stacked (vertical) or inline (horizontal), sitting in
            // the length of bar past the cells. A representation, not the real
            // rotated texture: it says stacked-vs-inline, which IS the setting.
            Item {
                id: titleZone
                clip: true
                x: root.vbar ? 0 : stage.cellsLen
                y: root.vbar ? stage.cellsLen : 0
                width: root.vbar ? stage.thick : bar.width - stage.cellsLen
                height: root.vbar ? bar.height - stage.cellsLen : stage.thick

                Column {
                    visible: !root.horiz
                    anchors.centerIn: parent
                    Repeater {
                        model: ["W", "i", "n"]
                        PixelText {
                            required property string modelData
                            text: modelData
                            font.pixelSize: 8; lineHeight: 8
                            color: Theme.accent
                        }
                    }
                }
                Row {
                    visible: root.horiz
                    anchors.centerIn: parent
                    Repeater {
                        model: ["W", "i", "n"]
                        PixelText {
                            required property string modelData
                            text: modelData
                            font.pixelSize: 8; lineHeight: 8
                            color: Theme.accent
                        }
                    }
                }
            }

            // toggle compact by clicking the cells end
            Rectangle {
                x: root.vbar ? 0 : 0
                y: 0
                width: root.vbar ? stage.thick : stage.cellsLen
                height: root.vbar ? stage.cellsLen : stage.thick
                color: cellsHit.containsMouse ? Theme.highlight : "transparent"
                MouseArea {
                    id: cellsHit
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.toggleCompact()
                }
            }

            // toggle orientation by clicking the title
            MouseArea {
                id: titleHit
                x: titleZone.x; y: titleZone.y
                width: titleZone.width; height: titleZone.height
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.toggleOrient()
            }
        }

        // ---- four edge gutters: click a side to move the bar there ----
        Repeater {
            model: [
                { e: "top",    gx: 0,                     gy: 0,                     gw: stage.width,      gh: stage.m },
                { e: "bottom", gx: 0,                     gy: stage.height - stage.m, gw: stage.width,     gh: stage.m },
                { e: "left",   gx: 0,                     gy: stage.m,               gw: stage.m,          gh: stage.height - 2 * stage.m },
                { e: "right",  gx: stage.width - stage.m, gy: stage.m,               gw: stage.m,          gh: stage.height - 2 * stage.m }
            ]
            MouseArea {
                required property var modelData
                x: modelData.gx; y: modelData.gy
                width: modelData.gw; height: modelData.gh
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onEntered: stage.hoverEdge = modelData.e
                onExited: if (stage.hoverEdge === modelData.e) stage.hoverEdge = ""
                onClicked: { root.setEdge(modelData.e); stage.hoverEdge = ""; }
            }
        }
    }

    // state readout — no knob's value is hidden behind a gesture (§10)
    PixelText {
        text: "side: " + root.edge
            + "   ·   title: " + root.d.titleOrientation
            + "   ·   bar: " + (root.compact ? "compact" : "full")
        color: Theme.text
    }
    PixelText {
        text: "click a side to move the bar · the cells to compact · the title to rotate"
        color: Theme.textDim
    }
}

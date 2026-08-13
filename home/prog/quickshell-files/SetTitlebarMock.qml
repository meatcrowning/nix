import QtQuick

// An interactive preview of the hyprvtb titlebar (docs/DESIGN.md §12), drawn as
// a REAL titlebar sitting on the edge of a faux window rather than a schematic:
// the five system cells in their actual glyphs (§12.1 — close `x`, roll `>>`,
// maximize `=`, minimize `>`, pin `o>`), the program icon slot (§12.2), then the
// title — all in the live titlebar palette (bar bg = Theme.bg, glyphs in the
// col.text tone, the focused title in accent; wal-set.sh's mapping). The window
// body below/beside it is just its frame outline, reflecting the live border and
// rounding settings on this same page.
//
// It is wired to the three GLOBAL bar knobs and nothing else. There is no global
// config key for WHICH buttons show or their order/side — the inner column is
// each app declaring its own cells over the vtbclient socket — so this control is
// deliberately the three global knobs only (the board decision of 2026-08-09:
// build the picker for edge/orientation/compact, no per-button show/hide).
//
//   click a SIDE of the window  -> titlebar side    (right/left/top/bottom)
//   click the CELLS end of bar  -> compact          (single vs double column)
//   click the TITLE on the bar  -> title orientation (vertical/horizontal)
//
// The same three knobs also have plain dropdowns beside the preview in
// SetPgAppearance.qml, so nothing here is set only by a gesture (§10); this stage
// is the direct-manipulation face of the same store keys. Each write goes to
// SettingsStore.d and saves; SettingsApply.qml's Connections push it live over
// hl.config, exactly as the plain rows this replaced did — no apply wiring
// changed.
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
        height: 176

        property string hoverEdge: ""

        readonly property int m: 20                       // edge gutter = click margin
        readonly property int bodyX: m
        readonly property int bodyY: m
        readonly property int bodyW: width - 2 * m
        readonly property int bodyH: height - 2 * m

        // titlebar geometry (docs/DESIGN.md §12.1): five system cells, then the
        // program icon, then the title, laid along the bar's main axis.
        readonly property int cell: 11
        readonly property int gap: 2
        readonly property int pitch: cell + gap
        readonly property int pad: 5
        readonly property int thick: root.compact ? 15 : 24
        readonly property int cellsRun: pad + 5 * pitch      // system cells' length
        readonly property int iconRun: pitch                 // icon slot
        readonly property int titleStart: cellsRun + iconRun // where the title begins

        // geometry of the bar (or a ghost) sitting on edge e, in stage coords
        function bx(e) { return e === "right" ? bodyX + bodyW - thick : bodyX; }
        function by(e) { return e === "bottom" ? bodyY + bodyH - thick : bodyY; }
        function bw(e) { return (e === "right" || e === "left") ? thick : bodyW; }
        function bh(e) { return (e === "right" || e === "left") ? bodyH : thick; }

        // ---- the faux window: just its frame (docs/DESIGN.md §4, live keys) ----
        Rectangle {
            id: body
            x: stage.bodyX; y: stage.bodyY; width: stage.bodyW; height: stage.bodyH
            color: Theme.bg
            radius: Theme.windowRounding
            border.width: Math.max(1, Theme.windowBorderWidth)
            border.color: Theme.windowBorder
        }

        // ---- ghost preview of the bar at a hovered, non-current edge ----
        Rectangle {
            visible: stage.hoverEdge !== "" && stage.hoverEdge !== root.edge
            x: stage.bx(stage.hoverEdge); y: stage.by(stage.hoverEdge)
            width: stage.bw(stage.hoverEdge); height: stage.bh(stage.hoverEdge)
            color: "transparent"
            border.width: 1
            border.color: Theme.border
            opacity: 0.7
        }

        // ---- the live titlebar on the current edge ----
        Item {
            id: bar
            x: stage.bx(root.edge); y: stage.by(root.edge)
            width: stage.bw(root.edge); height: stage.bh(root.edge)

            // bg_color is the same black as the window body; the bar reads as a
            // strip through its glyphs and the hairline that fences it off from
            // the content (the deco/frame boundary), not a different fill.
            Rectangle {
                anchors.fill: parent
                color: Theme.bg
                // hairline on the content-facing edge
                Rectangle {
                    color: Theme.border
                    width: root.vbar ? 1 : parent.width
                    height: root.vbar ? parent.height : 1
                    x: root.vbar ? (root.edge === "right" ? 0 : parent.width - 1) : 0
                    y: root.vbar ? 0 : (root.edge === "bottom" ? 0 : parent.height - 1)
                }
            }

            // the five system cells, in their real glyphs and order (vtbDeco.cpp)
            Repeater {
                model: ["x", ">>", "=", ">", "o>"]
                Item {
                    id: sysCell
                    required property int index
                    required property string modelData
                    width: stage.cell; height: stage.cell
                    x: root.vbar ? (stage.thick - stage.cell) / 2
                                 : stage.pad + index * stage.pitch
                    y: root.vbar ? stage.pad + index * stage.pitch
                                 : (stage.thick - stage.cell) / 2
                    PixelText {
                        anchors.centerIn: parent
                        text: sysCell.modelData
                        font.pixelSize: 8; lineHeight: 8
                        color: Theme.textDim
                    }
                }
            }

            // the program icon slot — states identity, drawn plainly (§12.2)
            AppIcon {
                iconName: "filer"
                color: Theme.accent
                width: stage.cell; height: stage.cell
                x: root.vbar ? (stage.thick - stage.cell) / 2 : stage.cellsRun
                y: root.vbar ? stage.cellsRun : (stage.thick - stage.cell) / 2
            }

            // ---- the title, in the length of bar past the icon ----
            Item {
                id: titleZone
                clip: true
                x: root.vbar ? 0 : stage.titleStart
                y: root.vbar ? stage.titleStart : 0
                width: root.vbar ? stage.thick : bar.width - stage.titleStart
                height: root.vbar ? bar.height - stage.titleStart : stage.thick

                // vertical: a stacked column of upright letters (the shipped look)
                Column {
                    visible: !root.horiz
                    anchors.centerIn: parent
                    Repeater {
                        model: ["f", "i", "l", "e", "r"]
                        PixelText {
                            required property string modelData
                            text: modelData
                            font.pixelSize: 8; lineHeight: 9
                            color: Theme.accent
                        }
                    }
                }
                // horizontal: the whole title as one run turned 90° clockwise on a
                // vertical bar (book-spine, §12), or laid inline on a horizontal one
                PixelText {
                    visible: root.horiz
                    anchors.centerIn: parent
                    text: "filer"
                    font.pixelSize: 8; lineHeight: 8
                    color: Theme.accent
                    rotation: root.vbar ? 90 : 0
                }
            }

            // toggle compact by clicking the system-cells end of the bar
            Rectangle {
                x: 0; y: 0
                width: root.vbar ? stage.thick : stage.cellsRun
                height: root.vbar ? stage.cellsRun : stage.thick
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
            Rectangle {
                x: titleZone.x; y: titleZone.y
                width: titleZone.width; height: titleZone.height
                color: titleHit.containsMouse ? Theme.highlight : "transparent"
                MouseArea {
                    id: titleHit
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.toggleOrient()
                }
            }
        }

        // ---- four edge gutters: click a side to move the bar there ----
        Repeater {
            model: [
                { e: "top",    gx: 0,                     gy: 0,                      gw: stage.width,     gh: stage.m },
                { e: "bottom", gx: 0,                     gy: stage.height - stage.m, gw: stage.width,     gh: stage.m },
                { e: "left",   gx: 0,                     gy: stage.m,                gw: stage.m,         gh: stage.height - 2 * stage.m },
                { e: "right",  gx: stage.width - stage.m, gy: stage.m,                gw: stage.m,         gh: stage.height - 2 * stage.m }
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
}

import QtQuick

// ONE MINISTER'S LIVE SHELL — the little tail the triangle draws under its
// cards, [his ask, 2026-08-01]: *"the last couple of lines"* of each running
// minister's own output, so a bound spirit reads as a live process.
//
// THE LINES ARE HANDS OFF FOR THIS COMPONENT. They travel ready in the shell
// dict (`Agents.shells`), built in `main.py` off the SAME transcript the card
// drawer tails (`Agents.output` — a running worker's `~/.cache/board-work/
// <id>.log` is buffered and empty until it exits, so the transcript is the only
// honest live source), glyph-mapped at ingest (§2.3), and already cut to two
// lines. This draws them, one clipped line each, exactly the way the drawer's
// do — somebody else's output, the secondary tone, NoWrap so a tool result
// cannot bury the row it hangs off (§5.2).
//
// The name is the shell's subject, the same word the card above it reads; it is
// drawn once, above its lines, so the tail is never anonymous and the name is
// never repeated on every row of a wrapped line.
Item {
    id: sh

    property string name: ""
    property var lines: []
    property real cellW: 8
    property color fgDim: Theme.textDim

    implicitHeight: col.implicitHeight + 2
    height: implicitHeight

    // Cut a line to `cells` characters, ASCII "..." — the twin of the drawer's
    // (and `win.clipTo`'s). Never `Text.ElideRight`, whose U+2026 the font has
    // not (§2.3); a character count is exact because the font is monospace.
    function clipTo(s, cells) {
        if (cells < 4)
            return "..."
        return s.length <= cells ? s : s.slice(0, cells - 3) + "..."
    }

    Column {
        id: col
        width: parent.width
        spacing: 0

        PixelText {
            id: nameT
            width: col.width
            visible: sh.name !== ""
            height: visible ? implicitHeight : 0
            color: sh.fgDim
            text: sh.name
        }

        Repeater {
            model: sh.lines
            delegate: PixelText {
                required property var modelData
                width: col.width
                // No wrap and no `elide`: Qt elides with U+2026 (§2.3). The
                // monospace font makes a character count an exact width (§2.7).
                wrapMode: Text.NoWrap
                clip: true
                color: sh.fgDim
                text: sh.clipTo(String(modelData), Math.floor(width / sh.cellW))
            }
        }
    }
}

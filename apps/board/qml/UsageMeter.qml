import QtQuick

// One usage window: `5h  [====    ]  73%`.
//
// The numbers and every decision about them are `boardusage.py`'s — where they
// come from, why the short one is labelled `5h` and not "daily", and why there
// is no Fable row. This file only draws.
//
// Colour is BORROWED, not invented (docs/DESIGN.md §3.2): the ladder is the one the
// panel's disk card already uses for "how full is it" — accent, `warn` past
// three quarters, `crit` past nine tenths — so a bar here means the same thing
// a bar there does. The unlit track is `bgAlt`, never `dim` (§3.4).
//
// An UNKNOWN reading draws the empty track and the word, never a zero-length
// bar that would read as "nothing used" (§10). The bar is not clickable and
// nothing here opens anything: it is a readout, and a control that is drawn is
// a control that works.
//
// The WIDTH is the caller's, not the content's ([his, 2026-07-29] the meters are
// exactly as wide as the model chooser above them and stack under it). So the
// window name goes hard left and the percentage hard right — paired values at
// opposite edges of one line, §5.4 — and the TRACK is what flexes into whatever
// is left, the way a text column consumes its slack (§5.2). Nothing here is a
// literal bar width any more.
//
// At that width the age cannot share the line — `73%` plus `(2h old)` is wider
// than the chooser on its own — so it takes a second line under the row rather
// than being dropped: §3.5 wants it read, not hovered for.
Item {
    id: meter

    //: one row of `Usage.rows` — {label, known, percent, text, note, detail}
    property var row: null
    property color fgDim: Theme.textDim
    property color fgText: Theme.text

    //: the narrowest the bar may get before the row stops being a bar at all
    property int minBarW: 24

    readonly property int lineH: Theme.fontSize + 4

    implicitWidth: name.width + 6 + minBarW + 6 + value.width
    implicitHeight: lineH + (age.visible ? lineH : 0)
    width: implicitWidth
    height: implicitHeight

    PixelText {
        id: name
        y: Math.round((meter.lineH - height) / 2)
        color: meter.fgDim
        text: meter.row ? meter.row.label : ""
    }

    Rectangle {
        id: track
        x: name.width + 6
        y: Math.round((meter.lineH - height) / 2)
        width: Math.max(0, value.x - 6 - x)
        // A 3px stub of a bar is not a bar; the word beside it is the whole
        // reading in that state anyway (`unknown` is nearly as wide as the
        // chooser). Nothing is dropped that carries a number.
        visible: width >= meter.minBarW
        height: Math.max(6, Math.round(Theme.fontSize / 2))
        color: Theme.bgAlt
        border.width: 1
        border.color: Theme.border

        Rectangle {
            // Pixel-snapped, like every other 1px-bevelled thing here: a
            // fractional width shimmers along its edge as the value ticks.
            x: 1
            y: 1
            height: parent.height - 2
            width: (meter.row && meter.row.known)
                   ? Math.round((parent.width - 2) * meter.row.percent / 100)
                   : 0
            visible: width > 0
            color: (meter.row && meter.row.percent >= 90) ? Theme.crit
                 : (meter.row && meter.row.percent >= 75) ? Theme.warn
                 : Theme.accent
        }
    }

    PixelText {
        id: value
        // Right edge, but never back over the window name if the caller hands
        // this a width narrower than the two words together.
        x: Math.max(name.width + 6, meter.width - width)
        y: Math.round((meter.lineH - height) / 2)
        color: (meter.row && meter.row.known) ? meter.fgText : meter.fgDim
        text: meter.row ? meter.row.text : ""
    }

    PixelText {
        // §3.5: an old reading says so in the row, not only on hover — the age
        // is the difference between "he has used 73%" and "he had, an hour ago".
        // Under the percentage it qualifies, against the same right edge.
        id: age
        x: meter.width - width
        y: meter.lineH + Math.round((meter.lineH - height) / 2)
        color: meter.fgDim
        text: meter.row && meter.row.note ? "(" + meter.row.note + ")" : ""
        visible: text !== ""
    }

    //: the window owns the footer line (§7.4); the meter only says when it is
    //: under the pointer, and the caller decides what that sentence is
    readonly property bool hovering: hov.hovered

    HoverHandler { id: hov }

    // ...and WHEN THIS LIMIT COMES BACK is the row's own tooltip. [his,
    // 2026-07-29] *"add a tooltip to each usage indicator that says when that
    // limit next resets"*. The sentence is `boardusage.readings()`'s (§2 — his
    // prose lives with the numbers, not here), it names its own window because a
    // chip is read away from the label it grew out of, and it is never empty: a
    // payload with no `resets_at` says that instead of showing nothing (§10).
    //
    // It covers the whole row rather than the bar alone: the label and the
    // percentage are as much "this limit" as the track is (§5.3). Both hover
    // channels are live at once and that is deliberate — the chip answers *when
    // does it reset*, the footer sentence answers *what is this number and how
    // old*. A `HoverHandler` is passive, so the two do not fight.
    ToolTipArea {
        anchors.fill: parent
        // BOTH sentences, in one chip. `detail` used to be written into the
        // window's `status` on hover, and that is the footer the hyprvtb bar
        // draws — so hovering a meter put text in the inner titlebar, his
        // *"stray text ... in the inner sidebar"*. The two answers still differ
        // (*what is this number* and *when does it come back*), so they are two
        // lines of one tooltip rather than two channels.
        text: {
            var d = meter.row && meter.row.detail ? meter.row.detail : "";
            var r = meter.row && meter.row.reset ? meter.row.reset : "";
            return d !== "" && r !== "" ? d + "\n" + r : d + r;
        }
    }
}

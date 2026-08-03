import QtQuick

// One usage window: `5h  [====    ]  73%`.
//
// The numbers and every decision about them are `boardusage.py`'s — where they
// come from, why the short one is labelled `5h` and not "daily", and why there
// is no Fable row. This file only draws.
//
// Colour is BORROWED, not invented (docs/DESIGN.md §3.2): the ladder is the one the
// panel's disk card uses for "how full is it" — `warn` past three quarters,
// `crit` past nine tenths. The nominal band used to be `accent`, copied
// verbatim from the disk card; §3.8 law 2 moved it to `ok` here — nominal
// usage isn't "active/focused", it's "healthy", and `ok` is the role that
// already means that. The unlit track is `bgAlt`, never `dim` (§3.4).
//
// An UNKNOWN reading draws the empty track and the word, never a zero-length
// bar that would read as "nothing used" (§10).
//
// CLICKING THE ROW REFRESHES IT [his, 2026-07-30] — the whole row, label to
// percentage, because "this limit" is all of it (§5.3) and a bar 7px tall is not
// a target. It runs the same fetch the clocks run (`Usage.refreshNow()`), and
// §10 is why `busy` and the caller's report exist rather than a cursor alone: a
// host with no network, an expired token or `BOARD_USAGE_OFFLINE=1` all make
// this click achieve nothing, and each of those has to SAY so. Nothing here
// blanks while it works — the reading on screen stays the last true one.
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

    //: a fetch is in flight — the caller hands this straight from `Usage.busy`.
    //  While it is true the row says so and refuses a second click: two clicks
    //  cannot make one round trip go faster, and the second would look ignored.
    property bool busy: false

    //: he clicked the row. The caller runs the fetch and words the outcome; a
    //  readout does not own the network (§5.3, and the same split as `hovering`).
    signal refreshRequested()

    readonly property int lineH: Theme.fontSize + 4

    implicitWidth: name.width + 6 + minBarW + 6 + value.width
    implicitHeight: lineH + (age.visible ? lineH : 0)
    width: implicitWidth
    height: implicitHeight

    // The row is a target now, so it hovers like one — the same `Theme.highlight`
    // fill a list row and the chooser above it use (§9.1), declared first so it
    // sits behind the reading rather than over it. No border and no radius: it is
    // a row in a stack, not a box (§5.1).
    Rectangle {
        anchors.fill: parent
        color: hov.hovered ? Theme.highlight : "transparent"
    }

    PixelText {
        id: name
        y: Math.round((meter.lineH - height) / 2)
        // Lit for as long as the fetch runs — the in-flight state has to be
        // visible in the ROW he clicked and not only in the footer, and the one
        // thing a meter can safely change while it works is the label beside a
        // reading that must not move (§10, §3.5).
        color: meter.busy ? Theme.accent : meter.fgDim
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
                 : Theme.ok
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

    // The whole row, both lines of it when the age is showing. A `HoverHandler`
    // is passive and the tooltip below accepts no buttons, so all three channels
    // — hover fill, click, chip — live over the same rectangle without fighting
    // (the pairing `PickBox` documents).
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: if (!meter.busy) meter.refreshRequested()
    }

    // ...and HOW LONG UNTIL THIS LIMIT COMES BACK is the row's own tooltip, and
    // now the only thing in it: [his, 2026-07-30] *"the tooltip should just say
    // `resets in ____`"*. One line, a countdown, `boardusage.readings()`'s
    // wording (§2 — his prose lives with the numbers, not here) and never empty
    // (§10).
    //
    // It used to carry `detail` above that line — what the number is and how old
    // the reading is. Nothing was lost by dropping it: the age is already the
    // row's second line (§3.5), and the window name is two characters to the
    // left of the pointer. A chip that repeats what is under it costs the width
    // of the one thing that is not (§8, §9.1).
    //
    // It covers the whole row rather than the bar alone: the label and the
    // percentage are as much "this limit" as the track is (§5.3).
    ToolTipArea {
        anchors.fill: parent
        text: meter.row && meter.row.reset ? meter.row.reset : ""
    }
}

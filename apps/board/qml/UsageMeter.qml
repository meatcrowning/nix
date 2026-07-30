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
Item {
    id: meter

    //: one row of `Usage.rows` — {label, known, percent, text, note, detail}
    property var row: null
    property color fgDim: Theme.textDim
    property color fgText: Theme.text
    property int barW: 56

    implicitWidth: name.width + 6 + track.width + 6 + value.width
                   + (age.visible ? age.width + 5 : 0)
    implicitHeight: Theme.fontSize + 4
    width: implicitWidth
    height: implicitHeight

    PixelText {
        id: name
        anchors.verticalCenter: parent.verticalCenter
        color: meter.fgDim
        text: meter.row ? meter.row.label : ""
    }

    Rectangle {
        id: track
        x: name.width + 6
        anchors.verticalCenter: parent.verticalCenter
        width: meter.barW
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
        x: track.x + track.width + 6
        anchors.verticalCenter: parent.verticalCenter
        color: (meter.row && meter.row.known) ? meter.fgText : meter.fgDim
        text: meter.row ? meter.row.text : ""
    }

    PixelText {
        // §3.5: an old reading says so in the row, not only on hover — the age
        // is the difference between "he has used 73%" and "he had, an hour ago".
        id: age
        x: value.x + value.width + 5
        anchors.verticalCenter: parent.verticalCenter
        color: meter.fgDim
        text: meter.row && meter.row.note ? "(" + meter.row.note + ")" : ""
        visible: text !== ""
    }

    //: the window owns the footer line (§7.4); the meter only says when it is
    //: under the pointer, and the caller decides what that sentence is
    readonly property bool hovering: hov.hovered

    HoverHandler { id: hov }
}

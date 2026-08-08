import QtQuick

// The one in-window button (surfer's BrowserButton, unchanged in behaviour):
// hairline border and rounding off the global frame tokens (Theme.ctrlBorder /
// Theme.rounding), hover tints to bgAlt, and every foreground greys to
// the titlebar's own inactive tone when the window is unfocused — docs/DESIGN.md
// §3.1.1 fades the WHOLE window, not just its chrome.
//
// editor draws very few of these: its chrome lives in the hyprvtb titlebar
// (§7.4), so these are only for the find/replace bar's own steppers and the
// confirm dialog's two answers.
Rectangle {
    id: root
    property string label: ""
    property bool enabled: true
    property bool danger: false
    property bool lit: false
    property bool winActive: true
    signal clicked()

    width: t.implicitWidth + 16
    height: Theme.lineHeight + 7
    color: lit ? (winActive ? Theme.accent : Theme.inactive)
         : (ma.containsMouse && enabled ? Theme.bgAlt : "transparent")
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: !enabled ? Theme.border
                 : danger ? Theme.crit
                 : ma.containsMouse ? (winActive ? Theme.accent : Theme.inactive)
                 : Theme.border
    opacity: enabled ? 1 : 0.4

    PixelText {
        id: t
        anchors.centerIn: parent
        text: root.label
        // An active toggle is INVERTED — filled with accent, glyph in the
        // background colour (§12.1). Same vocabulary as the titlebar's cells, so
        // a lit control reads the same wherever it is drawn.
        color: root.lit ? Theme.bg
             : root.danger ? Theme.crit
             : (ma.containsMouse && root.enabled) ? (root.winActive ? Theme.accent : Theme.inactive)
             : (root.winActive ? Theme.text : Theme.inactive)
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (root.enabled) root.clicked()
    }
}

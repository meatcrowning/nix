import QtQuick

// The theme section's heading: the colours the desktop is currently built from,
// as one contiguous strip, centred over the controls that produce them.
//
// It is LIVE, and live in two different ways on purpose. The base colour is
// read straight off the store, so it moves the instant the picker below is
// touched. Everything after it is the real Theme token — the palette that
// actually shipped — so the strip updates as each selection re-applies rather
// than showing a guess at what wal will return. A preview that predicted the
// palette would be a second implementation of wal-extract.py in QML, and the
// first time the two disagreed the strip would be lying (docs/DESIGN.md §10.2).
Item {
    id: root
    width: parent ? parent.width : 480
    height: 34

    readonly property color base: SettingsStore.d.baseColor
    readonly property var tokens: [
        Theme.bg, Theme.bgAlt, Theme.highlight, Theme.border, Theme.dim,
        Theme.textDim, Theme.text, Theme.accent,
        Theme.ok, Theme.warn, Theme.crit, Theme.info
    ]

    readonly property int cellW: 20
    readonly property int cellH: 24

    Row {
        anchors.centerIn: parent
        spacing: 10

        // The base colour, set apart from the derived ladder — it is an input,
        // not one of the twelve tokens.
        Rectangle {
            width: root.cellH
            height: root.cellH
            color: root.base
            radius: Theme.windowRounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
        }

        Item {
            width: root.tokens.length * root.cellW
            height: root.cellH
            anchors.verticalCenter: parent.verticalCenter

            Repeater {
                model: root.tokens
                Rectangle {
                    required property int index
                    required property var modelData
                    x: index * root.cellW
                    width: root.cellW
                    height: root.cellH
                    color: modelData
                }
            }

            Rectangle {
                anchors.fill: parent
                color: "transparent"
                radius: Theme.windowRounding
                border.width: Theme.ctrlBorder
                border.color: Theme.border
            }
        }
    }
}

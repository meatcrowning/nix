import QtQuick

// Current conditions over the 7-day forecast — a pure view over the Weather
// singleton, which already owns the fetch, so it costs nothing to instantiate
// twice (once in the popup, once as a dock tile).
//
// Two things make it fill whatever it is given rather than sit in a pool of
// dead space: the four columns are PROPORTIONAL (the same component has to read
// at the popup's 252px and at whatever a dock cell hands it), and the day rows
// GROW to take up any slack height. `naturalRow` is what implicitHeight is built
// from — deriving it from `height` would be a binding loop, since the popup
// takes its height from implicitHeight.
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility.
    property bool active: false
    property int pad: 10
    readonly property real inner: Math.max(80, width - pad * 2)

    readonly property int naturalRow: 16
    readonly property int dayCount: Math.max(1, Weather.days.length)
    readonly property real _chrome: pad * 2 + now.height + 4 + head.height + 4
                                    + 1 + 4 + labels.height + 4
    readonly property real rowH:
        Math.max(naturalRow, (height - _chrome) / dayCount)

    implicitWidth: 252
    implicitHeight: _chrome + dayCount * naturalRow

    // Column geometry, shared by the rows and the labels under them.
    readonly property real cName: inner * 0.19
    readonly property real cSky:  inner * 0.24
    readonly property real cTemp: inner * 0.32
    readonly property real cRain: inner * 0.25

    // What it is doing RIGHT NOW, which the forecast rows don't tell you — the
    // same two values the classic bar's weather block shows.
    PixelText {
        id: now
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        text: (Weather.tempF <= -999 ? "--" : Weather.tempF + "°")
              + "  " + Weather.cond
        color: Theme.text
    }

    PixelText {
        id: head
        anchors { top: now.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
        text: SettingsStore.d.weatherPlace
        color: Theme.accent
    }

    Column {
        id: col
        anchors { top: head.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 0

        Repeater {
            model: Weather.days
            Row {
                required property var modelData
                width: root.inner
                height: root.rowH
                spacing: 0
                PixelText {
                    width: root.cName; height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: parent.modelData.name; color: Theme.textDim
                }
                PixelText {
                    width: root.cSky; height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: parent.modelData.cond; color: Theme.info; elide: Text.ElideRight
                }
                PixelText {
                    width: root.cTemp; height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: parent.modelData.hi + "/" + parent.modelData.lo
                    color: Theme.text
                }
                PixelText {
                    width: root.cRain; height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: parent.modelData.prob >= 0 ? parent.modelData.prob + "%" : "-"
                    color: parent.modelData.precip >= 0.05 ? Theme.info : Theme.textDim
                }
            }
        }

        PixelText {
            visible: Weather.days.length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            height: root.rowH
            verticalAlignment: Text.AlignVCenter
            text: "no data yet"
            color: Theme.textDim
        }
    }

    // column labels, pinned under the rows
    Rectangle {
        id: rule
        anchors { bottom: labels.top; bottomMargin: 4; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 1
        color: Theme.border
    }
    Row {
        id: labels
        anchors { bottom: parent.bottom; bottomMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 0
        PixelText { width: root.cName; text: "day";   color: Theme.textDim }
        PixelText { width: root.cSky;  text: "sky";   color: Theme.textDim }
        PixelText { width: root.cTemp; text: "hi/lo"; color: Theme.textDim }
        PixelText { width: root.cRain; text: "rain%"; color: Theme.textDim }
    }
}

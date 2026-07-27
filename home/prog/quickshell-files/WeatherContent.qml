import QtQuick

// The 7-day forecast body — a pure view over the Weather singleton, which
// already owns the fetch, so this costs nothing to instantiate twice (once in
// the popup, once as a dock tile).
//
// The four columns are proportional rather than fixed pixel widths: the same
// component has to read at the popup's 252px and at whatever a dock cell hands
// it, and fixed columns would either overflow the narrow case or leave a gap in
// the wide one.
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    property int pad: 10
    readonly property real inner: Math.max(80, width - pad * 2)

    implicitWidth: 252
    implicitHeight: pad * 2 + head.height + col.spacing + col.implicitHeight

    PixelText {
        id: head
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        text: SettingsStore.d.weatherPlace
        color: Theme.accent
    }

    Column {
        id: col
        anchors {
            top: head.bottom; topMargin: 4
            horizontalCenter: parent.horizontalCenter
        }
        width: root.inner
        spacing: 4

        Repeater {
            model: Weather.days
            Row {
                required property var modelData
                width: root.inner
                spacing: 0
                PixelText { width: root.inner * 0.19; text: parent.modelData.name; color: Theme.textDim }
                PixelText { width: root.inner * 0.24; text: parent.modelData.cond; color: Theme.info; elide: Text.ElideRight }
                PixelText {
                    width: root.inner * 0.32
                    text: parent.modelData.hi + "/" + parent.modelData.lo
                    color: Theme.text
                }
                PixelText {
                    width: root.inner * 0.25
                    text: parent.modelData.prob >= 0 ? parent.modelData.prob + "%" : "-"
                    color: parent.modelData.precip >= 0.05 ? Theme.info : Theme.textDim
                }
            }
        }

        PixelText {
            visible: Weather.days.length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            text: "no data yet"
            color: Theme.textDim
        }

        // column labels, directly under the rows
        Rectangle {
            visible: Weather.days.length > 0
            width: root.inner
            height: 1
            color: Theme.border
        }
        Row {
            visible: Weather.days.length > 0
            width: root.inner
            spacing: 0
            PixelText { width: root.inner * 0.19; text: "day";   color: Theme.textDim }
            PixelText { width: root.inner * 0.24; text: "sky";   color: Theme.textDim }
            PixelText { width: root.inner * 0.32; text: "hi/lo"; color: Theme.textDim }
            PixelText { width: root.inner * 0.25; text: "rain%"; color: Theme.textDim }
        }
    }
}

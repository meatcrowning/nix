import QtQuick
import Quickshell

// Vertical date display: month / day / year(2-digit) — bright month, dim
// day and year under it. (The calendar hover zone lives in shell.qml — it
// covers the whole lower strip of the bar, not just these glyphs.)
Item {
    id: root

    property string mo: "01"
    property string yy: "00"
    property string dd: "01"

    width: col.implicitWidth
    height: col.implicitHeight

    function pad(n) { return (n < 10 ? "0" : "") + n }

    function refresh() {
        const d = clock.date;
        root.mo = pad(d.getMonth() + 1);
        root.yy = pad(d.getFullYear() % 100);
        root.dd = pad(d.getDate());
    }

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
        onDateChanged: root.refresh()
    }

    Component.onCompleted: refresh()

    Column {
        id: col
        anchors.fill: parent
        spacing: 2

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.mo
            color: Theme.text
            font.pixelSize: Theme.clockSize
        }
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.dd
            color: Theme.textDim
            font.pixelSize: Theme.clockSize
        }
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.yy
            color: Theme.textDim
            font.pixelSize: Theme.clockSize
        }
    }

}

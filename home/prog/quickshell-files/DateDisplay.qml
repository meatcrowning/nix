import QtQuick
import Quickshell

// Vertical date display: two-digit month stacked over two-digit day, same
// treatment as Clock (bright over dim).
Column {
    id: root
    spacing: 2

    property string mo: "01"
    property string dd: "01"

    function pad(n) { return (n < 10 ? "0" : "") + n }

    function refresh() {
        const d = clock.date;
        root.mo = pad(d.getMonth() + 1);
        root.dd = pad(d.getDate());
    }

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
        onDateChanged: root.refresh()
    }

    Component.onCompleted: refresh()

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
}

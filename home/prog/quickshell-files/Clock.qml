import QtQuick
import Quickshell

// Vertical digital clock: two hour digits stacked over two minute digits.
Column {
    id: root
    spacing: 2

    property string hh: "12"
    property string mm: "00"

    function pad(n) { return (n < 10 ? "0" : "") + n }

    function refresh() {
        const d = clock.date;
        let h = d.getHours() % 12;
        if (h === 0) h = 12;          // 12-hour format, no leading-zero drop
        root.hh = pad(h);
        root.mm = pad(d.getMinutes());
    }

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
        onDateChanged: root.refresh()
    }

    Component.onCompleted: refresh()

    PixelText {
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.hh
        color: Theme.text
        font.pixelSize: Theme.clockSize
    }
    PixelText {
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.mm
        color: Theme.textDim
        font.pixelSize: Theme.clockSize
    }
}

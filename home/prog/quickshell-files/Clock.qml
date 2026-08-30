import QtQuick
import Quickshell

// Digital clock. On a vertical bar it is two hour digits stacked over two
// minute digits; on a horizontal one (barEdge top/bottom) the same two pairs
// read across with a colon between them, because a 48px-thick strip cannot
// hold two stacked lines at the clock size. Same colours either way: the hour
// is the bright half.
Item {
    id: root
    implicitWidth: horizontal ? row.implicitWidth : col.implicitWidth
    implicitHeight: horizontal ? row.implicitHeight : col.implicitHeight

    property bool horizontal: false

    component Big: PixelText { font.pixelSize: Theme.clockSize }

    property string hh: "12"
    property string mm: "00"

    function pad(n) { return (n < 10 ? "0" : "") + n }

    function refresh() {
        const d = clock.date;
        let h;
        if (SettingsStore.d.clock24h) {
            h = d.getHours();         // 24-hour, zero-padded
        } else {
            h = d.getHours() % 12;
            if (h === 0) h = 12;      // 12-hour format, no leading-zero drop
        }
        root.hh = pad(h);
        root.mm = pad(d.getMinutes());
    }

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
        onDateChanged: root.refresh()
    }

    // Re-render immediately when the 12/24h setting is toggled in Settings,
    // instead of waiting for the next minute tick.
    Connections {
        target: SettingsStore.d
        function onClock24hChanged() { root.refresh(); }
    }

    Component.onCompleted: refresh()

    Column {
        id: col
        visible: !root.horizontal
        anchors.centerIn: parent
        spacing: 2
        Big { anchors.horizontalCenter: parent.horizontalCenter; text: root.hh; color: Theme.text }
        Big { anchors.horizontalCenter: parent.horizontalCenter; text: root.mm; color: Theme.textDim }
    }

    Row {
        id: row
        visible: root.horizontal
        anchors.centerIn: parent
        spacing: 0
        Big { anchors.verticalCenter: parent.verticalCenter; text: root.hh; color: Theme.text }
        Big { anchors.verticalCenter: parent.verticalCenter; text: ":"; color: Theme.textDim }
        Big { anchors.verticalCenter: parent.verticalCenter; text: root.mm; color: Theme.textDim }
    }
}

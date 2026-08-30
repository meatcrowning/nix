import QtQuick
import Quickshell

// Date display: month / day / year(2-digit) — bright month, dim day and year.
// Stacked on a vertical bar, read across with slashes on a horizontal one
// (see Clock.qml for why). (The calendar hover zone lives in shell.qml — it
// covers the whole lower strip of the bar, not just these glyphs.)
Item {
    id: root

    property string mo: "01"
    property string yy: "00"
    property string dd: "01"

    property bool horizontal: false

    width: horizontal ? row.implicitWidth : col.implicitWidth
    height: horizontal ? row.implicitHeight : col.implicitHeight

    component Big: PixelText { font.pixelSize: Theme.clockSize }

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
        visible: !root.horizontal
        anchors.centerIn: parent
        spacing: 2
        Big { anchors.horizontalCenter: parent.horizontalCenter; text: root.mo; color: Theme.text }
        Big { anchors.horizontalCenter: parent.horizontalCenter; text: root.dd; color: Theme.textDim }
        Big { anchors.horizontalCenter: parent.horizontalCenter; text: root.yy; color: Theme.textDim }
    }

    Row {
        id: row
        visible: root.horizontal
        anchors.centerIn: parent
        spacing: 0
        Big { anchors.verticalCenter: parent.verticalCenter; text: root.mo; color: Theme.text }
        Big { anchors.verticalCenter: parent.verticalCenter; text: "/"; color: Theme.textDim }
        Big { anchors.verticalCenter: parent.verticalCenter; text: root.dd; color: Theme.textDim }
        Big { anchors.verticalCenter: parent.verticalCenter; text: "/"; color: Theme.textDim }
        Big { anchors.verticalCenter: parent.verticalCenter; text: root.yy; color: Theme.textDim }
    }

}

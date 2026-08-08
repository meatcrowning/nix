import QtQuick
import Quickshell

// The month grid. Today's cell gets the active treatment (bgAlt fill + accent
// border); pad cells before the 1st are blank.
//
// It rebuilds itself rather than being refreshed by whoever shows it: the popup
// used to call refresh() on open, which is no help to a dock tile that is simply
// always there. `_stamp` is the current date as a string, so the (cheap, but not
// free) rebuild happens exactly at midnight and on a week-start change, not
// once a minute.
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    property int pad: 10
    readonly property real inner: Math.max(126, width - pad * 2)
    // Floor of 14: at the dock's two-column width the whole month has ~105px to
    // live in, and a digit in this font is 8px wide, so anything larger would
    // overflow the tile rather than shrink to fit it.
    readonly property real cellW: Math.max(14, Math.min(40, inner / 7))
    // Natural row height (what the popup is sized to) and the one actually
    // used, which GROWS to fill a taller tile. Without that the month sat at
    // its natural height with dead space under it, which is exactly the space
    // the dock is short of. `naturalCellH` is what implicitHeight is built
    // from — deriving it from `height` instead would be a binding loop, since
    // the popup takes its height from implicitHeight.
    readonly property real naturalCellH: Math.round(cellW * 20 / 26)
    readonly property int weekRows: Math.max(1, Math.ceil(cells.length / 7))
    readonly property real _chrome: pad * 2 + head.height + 8 + 18 + 8
    readonly property real cellH:
        Math.max(naturalCellH, (height - _chrome) / weekRows)

    property string title: ""
    property int today: 0
    property var cells: []    // flat 7xN day numbers, 0 = blank pad cell

    implicitWidth: 7 * 26 + 24
    implicitHeight: _chrome + weekRows * naturalCellH

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
    }
    readonly property string _stamp: Qt.formatDate(clock.date, "yyyy-MM-dd")
    on_StampChanged: refresh()
    Component.onCompleted: refresh()

    Connections {
        target: SettingsStore.d
        function onWeekStartsMondayChanged() { root.refresh(); }
    }

    function refresh() {
        const now = new Date();
        today = now.getDate();
        title = Qt.formatDate(now, "MMMM yyyy").toLowerCase();
        let startDow = new Date(now.getFullYear(), now.getMonth(), 1).getDay(); // 0 = sunday
        // shift so Monday is column 0 when the week starts on Monday
        if (SettingsStore.d.weekStartsMonday) startDow = (startDow + 6) % 7;
        const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
        let c = [];
        for (let i = 0; i < startDow; i++) c.push(0);
        for (let d = 1; d <= daysInMonth; d++) c.push(d);
        while (c.length % 7 !== 0) c.push(0);
        cells = c;
    }

    PixelText {
        id: head
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        text: root.title
        color: Theme.accent
    }

    Column {
        id: col
        anchors { top: head.bottom; topMargin: 8; horizontalCenter: parent.horizontalCenter }
        spacing: 8

        Grid {
            id: dowRow
            columns: 7
            Repeater {
                model: SettingsStore.d.weekStartsMonday
                       ? ["m", "t", "w", "t", "f", "s", "s"]
                       : ["s", "m", "t", "w", "t", "f", "s"]
                Item {
                    required property string modelData
                    width: root.cellW
                    height: 18
                    PixelText {
                        anchors.centerIn: parent
                        text: parent.modelData
                        color: Theme.textDim
                    }
                }
            }
        }

        Grid {
            columns: 7
            Repeater {
                model: root.cells
                Item {
                    required property int modelData
                    width: root.cellW
                    height: root.cellH

                    Rectangle {
                        visible: parent.modelData === root.today
                        anchors.centerIn: parent
                        width: root.cellW - 2
                        height: root.cellH - 2
                        color: Theme.bgAlt
                        radius: Theme.windowRounding
                        border.width: Theme.ctrlBorder + 1
                        border.color: Theme.accent
                    }
                    PixelText {
                        visible: parent.modelData > 0
                        anchors.centerIn: parent
                        text: parent.modelData
                        color: parent.modelData === root.today ? Theme.accent : Theme.text
                    }
                }
            }
        }
    }
}

import QtQuick

// THE JOBS STRIP IS GONE FROM THE CONVERSATION under Oxygen, because the Fleet
// dock now holds it (apps/oracle/fleet.py). A strip inside the message log AND
// a tree in a panel are two displays of one list, and the one that has to go is
// the one that pushes the conversation down every time a job starts.
//
// This is a face that draws nothing rather than a deleted call site: Root.qml
// keeps its single `JobsTray {}` and the file selector decides, so the Hyprland
// tree and the `+plasma` legacy face are untouched and can still be put beside
// this one (`chatter --face=plasma`).
//
// Same API as ../JobsTray.qml — `expandedIds`, `count`, `running`, `layoutNow()`
// — so nothing at the call site has to know which face it got.
Item {
    id: root
    property string face: "oxygen"
    property var expandedIds: ({})

    readonly property int count: Jobs.rows.length
    readonly property int running: Jobs.runningCount

    visible: false
    implicitHeight: 0
    height: 0

    function layoutNow() {}
}

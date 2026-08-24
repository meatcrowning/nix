import QtQuick
import QtQuick.Controls as QQC

// The jobs strip in a Plasma session. Same strip, same rows, same rules as
// ../JobsTray.qml — the heading is a `QQC.Label` and the verb a real button,
// because in that session every word in this window is drawn by the KStyle
// (docs/DESIGN.md §7.6). The rows themselves are `+plasma/JobRow.qml`, picked
// by the file selector, so this file only differs in its one line of text.
Item {
    id: root
    property string face: "plasma"
    property var expandedIds: ({})

    readonly property int count: Jobs.rows.length
    readonly property int running: Jobs.runningCount

    visible: count > 0
    implicitHeight: visible ? Math.min(list.contentHeight, 2 * 74) : 0
    height: implicitHeight

    // The selftest reads the ROWS, and a ListView builds its delegates on a
    // polish pass that an offscreen run has no reason to schedule.
    function layoutNow() { list.forceLayout(); }

    ListView {
        id: list
        anchors.fill: parent
        clip: true
        spacing: 6
        model: Jobs.rows
        boundsBehavior: Flickable.StopAtBounds

        delegate: JobRow {
            objectName: "jobRow"      // how the selftest finds the rows
            width: list.width
            job: modelData
            expanded: !!root.expandedIds[modelData.id]
            onToggled: {
                var m = root.expandedIds;
                m[modelData.id] = !m[modelData.id];
                root.expandedIds = m;
                root.expandedIdsChanged();
            }
            onStopped: Jobs.stop(modelData.id)
            onCleared: Jobs.clear(modelData.id)
        }
    }
}

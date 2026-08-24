import QtQuick

// THE BACKGROUND JOBS, as a strip above the conversation.
//
// It exists because the work an agent does on his music library is not a tool
// call that answers in a second — it is a fingerprint pass over 19,000 tracks,
// a download, a transcode [his, 2026-08-23]. Those run for minutes or hours,
// they outlive the turn that started them, and a window that showed nothing
// while they ran would be lying about what the machine is doing
// (docs/DESIGN.md §10).
//
// It sits ABOVE the conversation, under the stat line [his, 2026-08-23] — the
// machine's own state belongs with the window's other standing facts, not
// between him and the compose box, and a strip that grows downward from there
// does not push the thing he is reading.
//
// It is SMALL on purpose: two rows before it scrolls, no heading (the rows say
// what is running better than a count of them does), and each row folds its log
// away until asked (§9.1). It collapses to nothing when there are no jobs (§5.2
// — dead space is a defect).
//
// The rows are `JobRow.qml`, which has a Plasma twin — so this file is the same
// in both sessions and the drawing is not.
Item {
    id: root
    property string face: "hypr"
    property var expandedIds: ({})

    readonly property int count: Jobs.rows.length
    readonly property int running: Jobs.runningCount

    visible: count > 0
    implicitHeight: visible ? Math.min(list.contentHeight, 2 * 66) : 0
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

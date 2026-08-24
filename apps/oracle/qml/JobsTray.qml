import QtQuick

// THE BACKGROUND JOBS, as a strip between the conversation and the compose box.
//
// It exists because the work an agent does on his music library is not a tool
// call that answers in a second — it is a fingerprint pass over 19,000 tracks,
// a download, a transcode [his, 2026-08-23]. Those run for minutes or hours,
// they outlive the turn that started them, and a window that showed nothing
// while they ran would be lying about what the machine is doing
// (docs/DESIGN.md §10).
//
// It COLLAPSES TO NOTHING when there are no jobs (§5.2 — dead space is a
// defect), it never scrolls the conversation out of the way (a bounded height,
// its own scroll past three rows), and each row folds its log away until asked
// (§9.1). The heading is one line: how many are running, and one verb.
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
    implicitHeight: visible ? Math.min(list.contentHeight, 3 * 78)
                              + head.height + 10 : 0
    height: implicitHeight

    Item {
        id: head
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: root.visible ? headText.implicitHeight + 4 : 0

        PixelText {
            id: headText
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            // The fact first, in his register: what is happening, and how many.
            text: root.running > 0
                  ? (root.running === 1 ? "1 job running"
                                        : root.running + " jobs running")
                  : (root.count === 1 ? "1 job finished"
                                      : root.count + " jobs finished")
            color: Theme.textDim
        }

        JobVerb {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            label: "clear finished"
            visible: root.count > root.running
            onClicked: Jobs.clear()
        }
    }

    // The selftest reads the ROWS, and a ListView builds its delegates on a
    // polish pass that an offscreen run has no reason to schedule.
    function layoutNow() { list.forceLayout(); }

    ListView {
        id: list
        anchors { top: head.bottom; topMargin: 6
                  left: parent.left; right: parent.right; bottom: parent.bottom }
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

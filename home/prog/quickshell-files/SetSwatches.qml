import QtQuick

// The current theme's colours as ONE contiguous strip — the same look as the
// palette strips on the paper+theme tiles at the top of this page
// (SetPaperGrid): equal-width columns, no gaps. The colours are the clusters
// wal-extract.py quantised the wallpaper into (Wall.clusters, published by
// wal-set.sh, dominant first).
//
// A lit column feeds the palette derivation; clicking it drops it
// (SettingsStore.d.paletteDropped -> wal-extract.py) and the theme re-applies.
// Clicking a dropped one re-lights it. Press-and-DRAG paints the pressed
// column's new state across every column crossed, so a run is one gesture.
// A dropped column is dimmed AND shrunk to a bottom sliver — the state said
// twice (docs/DESIGN.md §3.5), legible however narrow the columns get. The
// commit happens on release, and a release that would drop ALL of them is
// refused with a crit border flash (§10.2): all-dropped would silently fall
// back to using everything.
//
// ONE MouseArea over the whole strip, deliberately not one per column: the
// drag needs it, and a per-delegate area dies with its delegate if the model
// re-signals mid-press, taking the release with it.
Item {
    id: root
    width: 240
    height: 20

    readonly property var clusters: Wall.clusters
    readonly property int count: clusters.length
    readonly property var dropped: SettingsStore.d.paletteDropped || []
    readonly property real cellW: count > 0 ? width / count : width

    // an in-flight drag: the index range and the state it paints
    property int  dragA: -1
    property int  dragB: -1
    property bool dragDrops: false

    function isDropped(hx) { return root.dropped.indexOf(hx) >= 0; }
    // what column i will be once the current gesture commits
    function shownDropped(i) {
        if (root.dragA >= 0
            && i >= Math.min(root.dragA, root.dragB)
            && i <= Math.max(root.dragA, root.dragB))
            return root.dragDrops;
        return isDropped(root.clusters[i]);
    }

    // Nothing published yet (first run before a theme apply): say so rather
    // than draw an empty clickable box (§10.2).
    PixelText {
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: parent.right
        visible: root.count === 0
        text: "no palette yet"
        color: Theme.textDim
    }

    Row {
        anchors.fill: parent
        visible: root.count > 0
        Repeater {
            model: root.clusters
            Rectangle {
                id: cell
                required property int index
                required property string modelData
                readonly property bool off: root.shownDropped(index)
                width: Math.ceil(root.width / Math.max(1, root.count))
                height: off ? 5 : root.height
                anchors.bottom: parent.bottom
                color: "#" + modelData
                opacity: off ? 0.45 : 1.0
            }
        }
    }

    // hovered column marker — an accent underline tracking the pointer, so
    // the click target is visible even between 7px columns
    Rectangle {
        visible: root.count > 0 && ma.containsMouse
        x: Math.floor(ma.hoverIdx * root.cellW)
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -3
        width: Math.ceil(root.cellW)
        height: 2
        color: Theme.accent
    }

    Rectangle {
        anchors.fill: parent
        visible: root.count > 0
        color: "transparent"
        border.width: 1
        border.color: refuse.running ? Theme.crit
                    : ma.containsMouse ? Theme.accent : Theme.border
    }

    Timer { id: refuse; interval: 450 }

    MouseArea {
        id: ma
        anchors.fill: parent
        enabled: root.count > 0
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        preventStealing: true
        readonly property int hoverIdx: idxAt(mouseX)
        function idxAt(x) {
            return Math.max(0, Math.min(root.count - 1,
                                        Math.floor(x / root.cellW)));
        }
        onPressed: (m) => {
            const i = idxAt(m.x);
            root.dragDrops = !root.isDropped(root.clusters[i]);
            root.dragA = i;
            root.dragB = i;
        }
        onPositionChanged: (m) => {
            if (root.dragA >= 0)
                root.dragB = idxAt(m.x);
        }
        onCanceled: { root.dragA = -1; root.dragB = -1; }
        onReleased: {
            if (root.dragA < 0)
                return;
            const lo = Math.min(root.dragA, root.dragB);
            const hi = Math.max(root.dragA, root.dragB);
            root.dragA = -1;
            root.dragB = -1;
            const cur = (SettingsStore.d.paletteDropped || []).slice();
            for (let i = lo; i <= hi; i++) {
                const hx = root.clusters[i];
                const at = cur.indexOf(hx);
                if (root.dragDrops && at < 0)
                    cur.push(hx);
                else if (!root.dragDrops && at >= 0)
                    cur.splice(at, 1);
            }
            if (root.clusters.filter(c => cur.indexOf(c) < 0).length === 0) {
                refuse.restart();
                return;
            }
            SettingsStore.d.paletteDropped = cur;
            SettingsStore.save();
        }
    }
}

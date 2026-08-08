import QtQuick

// The current theme's colours as ONE contiguous strip — the same look as the
// palette strips on the paper+theme tiles at the top of this page
// (SetPaperGrid): equal columns, no gaps. The colours are the clusters
// wal-extract.py quantised the wallpaper into (Wall.clusters, published by
// wal-set.sh, dominant first), plus a reset button that re-lights everything.
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
// The columns are an EXACT partition of the strip width — cell i spans
// [round(i*w/n), round((i+1)*w/n)) — and the hit test is the same floor
// division, so what is drawn is what is clicked. The first cut (a Row of
// ceil(w/n)-wide cells, the tiles' recipe) overflowed the box by up to n-1 px
// with nothing clipping it: the strip drew shifted and every click landed one
// or two columns off its target. The tiles get away with ceil because the
// tile clips; a bare control does not.
//
// ONE MouseArea over the whole strip, deliberately not one per column: the
// drag needs it, and a per-delegate area dies with its delegate if the model
// re-signals mid-press, taking the release with it.
Row {
    id: root
    spacing: 8

    readonly property var clusters: Wall.clusters
    readonly property int count: clusters.length
    // This paper's own entry in the per-wallpaper map (see SettingsStore's
    // paletteDropped note). A bare-array value is the pre-per-paper format.
    readonly property var dropped: {
        const m = SettingsStore.d.paletteDropped;
        if (!m || typeof m !== "object" || Array.isArray(m)) return [];
        return m[Wall.path] || [];
    }
    function writeDropped(arr) {
        const old = SettingsStore.d.paletteDropped;
        const m = (old && typeof old === "object" && !Array.isArray(old))
                ? JSON.parse(JSON.stringify(old)) : {};
        if (arr.length) m[Wall.path] = arr;
        else delete m[Wall.path];
        SettingsStore.d.paletteDropped = m;
        SettingsStore.save();
    }

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
        visible: root.count === 0
        text: "no palette yet"
        color: Theme.textDim
    }

    Item {
        id: strip
        width: 220
        height: 20
        visible: root.count > 0

        function cutAt(i) { return Math.round(i * strip.width / Math.max(1, root.count)); }

        Repeater {
            model: root.clusters
            Rectangle {
                id: cell
                required property int index
                required property string modelData
                readonly property bool off: root.shownDropped(index)
                x: strip.cutAt(index)
                width: strip.cutAt(index + 1) - strip.cutAt(index)
                height: off ? 5 : strip.height
                y: strip.height - height
                color: "#" + modelData
                opacity: off ? 0.45 : 1.0
            }
        }

        // hovered column marker — an accent underline tracking the pointer, so
        // the click target is visible even between 7px columns
        Rectangle {
            visible: ma.containsMouse
            x: strip.cutAt(ma.hoverIdx)
            y: strip.height + 2
            width: strip.cutAt(ma.hoverIdx + 1) - strip.cutAt(ma.hoverIdx)
            height: 2
            color: Theme.accent
        }

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            radius: Theme.windowRounding
            border.width: Theme.ctrlBorder
            border.color: refuse.running ? Theme.crit
                        : ma.containsMouse ? Theme.accent : Theme.border
        }

        Timer { id: refuse; interval: 450 }

        MouseArea {
            id: ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            preventStealing: true
            readonly property int hoverIdx: idxAt(mouseX)
            function idxAt(x) {
                return Math.max(0, Math.min(root.count - 1,
                    Math.floor(x * root.count / Math.max(1, strip.width))));
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
                const cur = root.dropped.slice();
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
                root.writeDropped(cur);
            }
        }
    }

    // Re-light everything. Greyed, not hidden, while nothing is dropped
    // (§10.1) — it still shows what it would do.
    Rectangle {
        visible: root.count > 0
        width: resetLabel.implicitWidth + 14
        height: 20
        color: "transparent"
        opacity: root.dropped.length > 0 ? 1.0 : 0.4
        radius: Theme.windowRounding
        border.width: Theme.ctrlBorder
        border.color: rma.containsMouse && root.dropped.length > 0 ? Theme.accent : Theme.border
        PixelText {
            id: resetLabel
            anchors.centerIn: parent
            text: "reset"
            color: rma.containsMouse && root.dropped.length > 0 ? Theme.text : Theme.textDim
        }
        MouseArea {
            id: rma
            anchors.fill: parent
            enabled: root.dropped.length > 0
            hoverEnabled: root.dropped.length > 0
            cursorShape: Qt.PointingHandCursor
            onClicked: root.writeDropped([])
        }
    }
}

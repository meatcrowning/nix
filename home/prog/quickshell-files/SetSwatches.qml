import QtQuick

// The current theme's colours — the clusters wal-extract.py quantised the
// wallpaper into (Wall.clusters, published by wal-set.sh, dominant first).
// Clicking a lit swatch drops that colour from the palette derivation
// (SettingsStore.d.paletteDropped) and the theme re-applies; clicking a
// dropped one takes it back. A dropped swatch stays visible — dimmed AND
// crossed, the state said twice (docs/DESIGN.md §3.5) — so it can be re-lit.
// The last lit swatch refuses to drop with a crit border flash (§10.2):
// all-dropped would silently fall back to using everything.
Flow {
    id: root
    spacing: 4
    // 8 per row; wraps to more rows as paletteColorCount grows
    width: 8 * (16 + spacing) - spacing

    property var dropped: SettingsStore.d.paletteDropped || []

    Repeater {
        model: Wall.clusters
        delegate: Rectangle {
            id: sw
            required property string modelData
            readonly property bool off: root.dropped.indexOf(modelData) >= 0
            width: 16
            height: 16
            color: "#" + modelData
            opacity: off ? 0.35 : 1.0
            border.width: 1
            border.color: refuse.running ? Theme.crit
                        : ma.containsMouse ? Theme.accent : Theme.border
            PixelText {
                anchors.centerIn: parent
                visible: sw.off
                text: "x"
                color: Theme.text
            }
            Timer { id: refuse; interval: 450 }
            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    const cur = (SettingsStore.d.paletteDropped || []).slice();
                    const i = cur.indexOf(sw.modelData);
                    if (i >= 0)
                        cur.splice(i, 1);
                    else {
                        const lit = Wall.clusters.filter(c => cur.indexOf(c) < 0);
                        if (lit.length <= 1) { refuse.restart(); return; }
                        cur.push(sw.modelData);
                    }
                    SettingsStore.d.paletteDropped = cur;
                    SettingsStore.save();
                }
            }
        }
    }
}

import QtQuick
import "../../qmlcommon"

// Compact jump index for the gallery. Year order starts at decades; wheel up
// over one decade opens its individual years, and wheel down returns out.
Item {
    id: root
    height: Theme.lineHeight + 2

    property string sortMode: "orig_year"
    property int revision: 0
    property int zoomDecade: -1
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    signal jumpRequested(int albumIndex)

    onSortModeChanged: zoomDecade = -1

    function leading(text, artist) {
        var s = String(text || "").trim();
        if (artist && s.toLowerCase().indexOf("the ") === 0)
            s = s.slice(4);
        var c = s.length ? s.charAt(0).toUpperCase() : "#";
        return /[A-Z]/.test(c) ? c : "#";
    }

    readonly property var entries: {
        root.revision;
        var out = [], seen = {};
        for (var i = 0; i < AlbumsModel.count; ++i) {
            var a = AlbumsModel.get(i), key, label, decade = -1;
            if (sortMode === "orig_year") {
                var year = Number(a.year) || 0;
                decade = year > 0 ? Math.floor(year / 10) * 10 : -1;
                if (zoomDecade >= 0 && decade !== zoomDecade)
                    continue;
                key = zoomDecade >= 0 ? String(year) : String(decade);
                label = year > 0 ? (zoomDecade >= 0 ? String(year) : String(decade) + "s") : "?";
            } else {
                label = leading(sortMode === "artist" ? a.artist : a.album,
                                sortMode === "artist");
                key = label;
            }
            if (!seen[key]) {
                seen[key] = true;
                out.push({ label: label, index: i, decade: decade });
            }
        }
        return out;
    }

    Rectangle { anchors.fill: parent; color: Theme.bgAlt }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

    Row {
        anchors.fill: parent
        Repeater {
            model: root.entries
            delegate: Item {
                required property var modelData
                width: root.width / Math.max(1, root.entries.length)
                height: root.height

                PixelText {
                    anchors.centerIn: parent
                    text: modelData.label
                    color: hit.containsMouse ? root.fgAccent : root.fgText
                }
                MouseArea {
                    id: hit
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    WheelNotch { id: notch }
                    onClicked: root.jumpRequested(modelData.index)
                    onWheel: function(w) {
                        var step = notch.steps(w);
                        if (root.sortMode !== "orig_year" || step === 0)
                            return;
                        if (step > 0 && root.zoomDecade < 0 && modelData.decade >= 0)
                            root.zoomDecade = modelData.decade;
                        else if (step < 0 && root.zoomDecade >= 0)
                            root.zoomDecade = -1;
                        w.accepted = true;
                    }
                }
            }
        }
    }
}

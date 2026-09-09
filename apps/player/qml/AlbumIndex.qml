import QtQuick
import "../../qmlcommon"

// Compact jump index for the gallery. Year order starts at decades; wheel up
// over one decade opens its individual years, and wheel down returns out.
Item {
    id: root
    height: plasma ? Math.max(Theme.lineHeight + 2, sortControls.implicitHeight + 4)
                   : Theme.lineHeight + 2

    Motion { id: motion }

    property string sortMode: "orig_year"
    property bool sortDescending: false
    property int revision: 0
    property int zoomDecade: -1
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property var displayEntries: []
    property bool ready: false
    signal jumpRequested(int albumIndex)
    signal sortRequested(string mode)
    signal sortDirectionRequested(bool descending)

    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    readonly property string sortLabel: {
        switch (sortMode) {
        case "artist": return "artist";
        case "album": return "album title";
        case "added": return "date added";
        case "plays": return "play count";
        case "rating": return "rating";
        default: return "year";
        }
    }

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

    onEntriesChanged: if (ready) swap.restart()
    Component.onCompleted: {
        displayEntries = entries;
        ready = true;
    }

    Rectangle { anchors.fill: parent; color: Theme.bgAlt }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

    Item {
        id: indexArea
        anchors { top: parent.top; bottom: parent.bottom; left: parent.left
                  right: sortControls.visible ? sortControls.left : parent.right }
        anchors.rightMargin: sortControls.visible ? 6 : 0
        clip: true

    Row {
        id: labels
        anchors.fill: indexArea
        Repeater {
            model: root.displayEntries
            delegate: Item {
                required property var modelData
                width: indexArea.width / Math.max(1, root.displayEntries.length)
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

    Row {
        id: sortControls
        visible: root.plasma
        anchors { right: parent.right; rightMargin: 3; verticalCenter: parent.verticalCenter }
        spacing: 2

        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            text: "sort by"
            color: root.fgDim
        }
        SelectButton {
            id: sortChoice
            width: 112
            label: root.sortLabel
            fgText: root.fgText
            fgDim: root.fgDim
            fgAccent: root.fgAccent
            options: [
                { label: "year", value: "orig_year" },
                { label: "artist", value: "artist" },
                { label: "album title", value: "album" },
                { label: "date added", value: "added" },
                { label: "play count", value: "plays" },
                { label: "rating", value: "rating" }
            ]
            onChose: function(mode) { root.sortRequested(mode); }
        }
        HeaderButton {
            width: implicitWidth
            height: sortChoice.height
            label: root.sortDescending ? "dn" : "up"
            plainLabel: root.sortDescending ? "descending" : "ascending"
            iconName: root.sortDescending ? "view-sort-descending" : "view-sort-ascending"
            iconOnly: true
            fgText: root.fgText
            fgDim: root.fgDim
            fgAccent: root.fgAccent
            onClicked: root.sortDirectionRequested(!root.sortDescending)
        }
    }


    SequentialAnimation {
        id: swap
        ParallelAnimation {
            NumberAnimation {
                target: labels; property: "opacity"; to: 0
                duration: motion.ms(motion.slideMs / 2)
                easing.type: motion.slideEasing
            }
            NumberAnimation {
                target: labels; property: "scale"; to: 0.96
                duration: motion.ms(motion.slideMs / 2)
                easing.type: motion.slideEasing
            }
        }
        ScriptAction {
            script: {
                root.displayEntries = root.entries;
                labels.scale = 1.04;
            }
        }
        ParallelAnimation {
            NumberAnimation {
                target: labels; property: "opacity"; to: 1
                duration: motion.ms(motion.slideMs / 2)
                easing.type: motion.slideEasing
            }
            NumberAnimation {
                target: labels; property: "scale"; to: 1
                duration: motion.ms(motion.slideMs / 2)
                easing.type: motion.slideEasing
            }
        }
    }
}

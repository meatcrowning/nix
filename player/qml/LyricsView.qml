import QtQuick
import QtQuick.Controls.Basic

// Lyrics pane. Synced (.lrc-style) lyrics scroll a ListView, the current line
// lit in Theme.text and the rest dimmed, following Player.position; clicking
// a line seeks there. Plain lyrics fall back to a flickable text column.
// Requests go through Library.requestLyrics → LyricsProvider worker; replies
// are matched on trackId so a stale fetch can't paint the wrong song.
Item {
    id: root
    property int trackId: -1
    property bool active: true    // only fetch while the pane is on screen
    property var data: ({ source: "", synced: false, lines: [], text: "" })
    property int currentLine: -1

    onTrackIdChanged: refetch()
    onActiveChanged: if (active) refetch()

    function refetch() {
        currentLine = -1;
        data = { source: "", synced: false, lines: [], text: "" };
        if (active && trackId >= 0)
            Library.requestLyrics(trackId);
    }

    Connections {
        target: Lyrics
        function onReady(tid, result) {
            if (tid === root.trackId)
                root.data = result;
        }
    }

    // Follow playback: binary-search the current line for the position.
    Connections {
        target: Player
        enabled: root.active && root.data.synced
        function onPositionChanged() {
            var lines = root.data.lines;
            if (!lines || lines.length === 0)
                return;
            var pos = Player.position;
            var lo = 0, hi = lines.length - 1, ans = -1;
            while (lo <= hi) {
                var mid = (lo + hi) >> 1;
                if (lines[mid].t <= pos) { ans = mid; lo = mid + 1; }
                else hi = mid - 1;
            }
            if (ans !== root.currentLine) {
                root.currentLine = ans;
                if (ans >= 0)
                    lyricsList.positionViewAtIndex(ans, ListView.Center);
            }
        }
    }

    PixelText {
        id: head
        x: 8
        y: 8
        text: "lyrics" + (root.data.source && root.data.source !== "none"
                          ? "  ·  " + root.data.source : "")
        color: Theme.textDim
    }

    // ---- synced ----
    ListView {
        id: lyricsList
        anchors.top: head.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 8
        visible: root.data.synced
        clip: true
        model: root.data.synced ? root.data.lines : []
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: VScroll {}

        delegate: Item {
            width: lyricsList.width
            height: Math.max(18, lineText.implicitHeight + 3)
            PixelText {
                id: lineText
                width: parent.width
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.line
                wrapMode: Text.Wrap
                color: index === root.currentLine ? Theme.text : Theme.textDim
            }
            MouseArea {
                anchors.fill: parent
                onClicked: Player.seek(modelData.t)
            }
        }
    }

    // ---- plain ----
    Flickable {
        anchors.top: head.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 8
        visible: !root.data.synced && root.data.text.length > 0
        clip: true
        contentHeight: plainText.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: VScroll {}

        PixelText {
            id: plainText
            width: parent.width
            text: root.data.text
            wrapMode: Text.Wrap
            color: Theme.textDim
        }
    }

    PixelText {
        anchors.centerIn: parent
        visible: !root.data.synced && root.data.text.length === 0
        text: root.trackId < 0 ? "" : (root.data.source === "none" ? "no lyrics found" : "…")
        color: Theme.dim
    }
}

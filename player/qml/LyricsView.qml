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
    property var lyricsData: ({ source: "", synced: false, lines: [], text: "" })
    property int currentLine: -1
    // Whether there is anything to show — the now-playing view collapses this
    // pane entirely when a track has no lyrics.
    readonly property bool hasContent: lyricsData.synced || lyricsData.text.length > 0

    onTrackIdChanged: refetch()
    onActiveChanged: if (active) refetch()

    function refetch() {
        currentLine = -1;
        lyricsData = { source: "", synced: false, lines: [], text: "" };
        if (active && trackId >= 0)
            Library.requestLyrics(trackId);
    }

    Connections {
        target: Lyrics
        function onReady(tid, result) {
            if (tid === root.trackId)
                root.lyricsData = result;
        }
    }

    // Follow playback: binary-search the current line for the position.
    Connections {
        target: Player
        enabled: root.active && root.lyricsData.synced
        function onPositionChanged() {
            var lines = root.lyricsData.lines;
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
        text: "lyrics" + (root.lyricsData.source && root.lyricsData.source !== "none"
                          ? "  ·  " + root.lyricsData.source : "")
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
        visible: root.lyricsData.synced
        clip: true
        model: root.lyricsData.synced ? root.lyricsData.lines : []
        interactive: false     // scrollbar + wheel only — no drag-flicking
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
                horizontalAlignment: Text.AlignHCenter
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
        id: plainFlick
        anchors.top: head.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 8
        visible: !root.lyricsData.synced && root.lyricsData.text.length > 0
        clip: true
        contentHeight: plainText.implicitHeight
        interactive: false     // scrollbar + wheel only — no drag-flicking
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: VScroll {}

        PixelText {
            id: plainText
            // NOT parent.width: parent is the Flickable's contentItem, whose
            // width stays 0 when only contentHeight is set — bind to the
            // Flickable itself (minus the scrollbar).
            width: plainFlick.width - 12
            text: root.lyricsData.text
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            color: Theme.textDim
        }
    }

    WheelScroll {
        anchors.fill: lyricsList
        view: lyricsList.visible ? lyricsList : null
    }
    WheelScroll {
        anchors.fill: plainFlick
        view: plainFlick.visible ? plainFlick : null
    }

    PixelText {
        anchors.centerIn: parent
        visible: !root.lyricsData.synced && root.lyricsData.text.length === 0
        // "instrumental" is an answer, not a failure — LRCLIB knows this track
        // has no words, so say so rather than implying the lookup fell short.
        text: root.trackId < 0 ? ""
              : root.lyricsData.source === "instrumental" ? "instrumental"
              : root.lyricsData.source === "none" ? "no lyrics found"
              : "..."
        color: Theme.dim
    }
}

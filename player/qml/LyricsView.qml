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
    // pane entirely otherwise.
    //
    // Words, an OPEN QUESTION, or a verdict of yours that you might want to
    // take back. A track LRCLIB has confirmed instrumental is the one case
    // that collapses silently: it is settled by an authority and there is
    // nothing left to do about it. An unresolved miss keeps the pane so you
    // can settle it by hand, and a hand-marked one keeps it so that stays
    // undoable.
    readonly property bool resolvedContent: lyricsData.synced
                                            || lyricsData.text.length > 0
                                            || lyricsData.source === "none"
                                            || lyricsData.source === "instrumental-user"

    // While a lookup is in flight this HOLDS the previous track's answer.
    // Recomputing it from the just-cleared lyricsData collapsed the pane to
    // zero width for the handful of frames a resolve takes, and since the whole
    // bottom row is anchored off this pane's left edge, every skip snapped the
    // queue full-width and back — a violent flash on each track change. The
    // column width now moves only when the new verdict is actually in.
    property bool fetching: false
    property bool lastContent: false
    readonly property bool hasContent: fetching ? lastContent : resolvedContent

    onTrackIdChanged: refetch()
    onActiveChanged: if (active) refetch()

    function refetch() {
        currentLine = -1;
        if (active && trackId >= 0) {
            fetching = true;
            lyricsData = { source: "", synced: false, lines: [], text: "" };
            Library.requestLyrics(trackId);
        } else {
            fetching = false;
            lastContent = false;
            lyricsData = { source: "", synced: false, lines: [], text: "" };
        }
    }

    Connections {
        target: Lyrics
        function onReady(tid, result) {
            if (tid === root.trackId) {
                root.lyricsData = result;
                root.lastContent = root.resolvedContent;
                root.fetching = false;
            }
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
            width: Math.max(0, plainFlick.width - 12)
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

    // ---- nothing to show: say WHICH kind of nothing ----
    //
    // "instrumental" (the track has no words) and "not found" (nobody has them
    // indexed) are different claims, and only the first is ever certain. The
    // pane states whichever one is true and, when it is only a miss, offers to
    // settle it by hand — for a library this niche you often know and LRCLIB
    // never will.
    Column {
        anchors.centerIn: parent
        // Math.max: a zero-width pane would give this a NEGATIVE width, and
        // centre-aligned text in a negative-width item draws half a line's
        // worth to the LEFT of the pane, outside it.
        width: Math.max(0, parent.width - 16)
        spacing: 6
        visible: !root.lyricsData.synced && root.lyricsData.text.length === 0
                 && root.trackId >= 0

        readonly property bool isInst: root.lyricsData.source === "instrumental"
                                       || root.lyricsData.source === "instrumental-user"
        readonly property bool isMiss: root.lyricsData.source === "none"

        PixelText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: parent.isInst
                  ? (root.lyricsData.source === "instrumental-user"
                     ? "instrumental" : "instrumental - no lyrics exist")
                  : parent.isMiss ? "no lyrics found" : "..."
            color: Theme.dim
        }

        // Undo for a hand-marked track; the LRCLIB verdict is not editable.
        HeaderButton {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.lyricsData.source === "instrumental-user"
            label: "search anyway"
            onClicked: {
                Library.setInstrumental(root.trackId, false);
                root.refetch();
            }
        }

        HeaderButton {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: parent.isMiss
            label: "mark instrumental"
            onClicked: {
                Library.setInstrumental(root.trackId, true);
                root.refetch();
            }
        }
    }
}

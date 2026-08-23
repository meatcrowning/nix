import QtQuick
import QtMultimedia

// ONE video in a reply, as a card the size of the bubble.
//
// [his, 2026-08-23] — "are inline youtube video displays possible in oracle?
// like the youtube video displays in the bubble? or any video pulled from the
// internet?" `show_video` resolves a watch page (or a direct media URL) to a
// STREAM url; this plays it where the reply put it, and nothing is on disk but
// the poster frame.
//
// Three rules it exists to keep:
//
//   * IT DOES NOT START ON ITS OWN. The card sits on its poster under a play
//     marker until he clicks it — he listens to music while he works, and a
//     chat window that starts making noise because a model said something is
//     the desktop taking his speakers (root AGENTS.md, docs/DESIGN.md §13).
//   * THE DECODER IS BUILT ON THE CLICK, not on the card. The process's first
//     QtMultimedia object costs ~460ms (viewer measured it: the ffmpeg backend
//     and its hw-decode probe load then, not at `import QtMultimedia`), so a
//     transcript holding six videos he never played must not pay for six.
//     Hence the Loader — the same shape viewer's video pane uses.
//   * A FAILURE IS DRAWN (§10). A stream that will not decode says so on the
//     card rather than leaving a black rectangle to be interpreted.
Column {
    id: card

    // One `videoResult` entry: {ok, url, src, title, alt, w, h, duration,
    // poster, live} or {ok:false, url, error}.
    property var entry: null
    readonly property bool ok: !!entry && entry.ok === true
    readonly property string src: ok ? (entry.src || "") : ""
    readonly property string poster: (ok && entry.poster) ? entry.poster : ""
    readonly property bool live: ok && entry.live === true
    // The caption is his model's own words when it wrote any, else the site's
    // title — never both, and never the raw URL, which is not a caption.
    readonly property string caption:
        ok ? ((entry.alt || "") !== "" ? entry.alt : (entry.title || "")) : ""

    // The frame's aspect: the real one when the resolver knew it, else 16:9.
    // Capped in height so a portrait clip cannot make one reply three screens
    // tall; inside the cap the video FITS (a video is never cropped — §5.1's
    // bleed rule is about stills, and a cropped video loses the shot).
    readonly property real aspect:
        (ok && entry.w > 0 && entry.h > 0) ? (entry.h / entry.w) : (9 / 16)
    readonly property int maxH: 420

    spacing: 2

    // m:ss, in the fixed slots §5.4 asks for, so the clock does not shuffle the
    // scrub track sideways every second.
    function clock(ms) {
        if (!(ms > 0)) return "0:00";
        var t = Math.floor(ms / 1000);
        var m = Math.floor(t / 60);
        var s = t % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    // ---- the failure line ---------------------------------------------------
    PixelText {
        visible: !card.ok
        width: card.width
        wrapMode: Text.Wrap
        text: "video: " + ((entry && entry.error) ? entry.error : "could not be shown")
        color: Theme.crit
    }

    // ---- the picture --------------------------------------------------------
    Rectangle {
        id: frame
        visible: card.ok
        width: card.width
        height: Math.min(Math.round(card.width * card.aspect), card.maxH)
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        clip: true

        // Has he asked for this one yet? Nothing below exists until he has.
        property bool started: false

        Image {
            id: posterImg
            anchors { fill: parent; margins: 1 }
            visible: card.poster !== "" && !video.playing
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            sourceSize.width: Math.max(1, frame.width - 2)
            source: card.poster !== "" ? "file://" + card.poster : ""
        }

        Loader {
            id: video
            anchors { fill: parent; margins: 1 }
            active: frame.started
            sourceComponent: playerComp
            // The card asks the item questions rather than reaching into it, so
            // everything below survives the Loader being inactive.
            readonly property bool playing:
                item !== null && item.player.playbackState === MediaPlayer.PlayingState
            readonly property bool failed:
                item !== null && item.player.error !== MediaPlayer.NoError
            readonly property real pos: item !== null ? item.player.position : 0
            readonly property real dur: {
                if (item !== null && item.player.duration > 0)
                    return item.player.duration;
                return card.ok && entry.duration > 0 ? entry.duration * 1000 : 0;
            }
        }

        Component {
            id: playerComp
            Item {
                property alias player: player
                AudioOutput { id: audioOut }
                MediaPlayer {
                    id: player
                    source: card.src
                    videoOutput: videoOut
                    audioOutput: audioOut
                }
                // Built BY the click, so the click is what it does.
                Component.onCompleted: player.play()
                VideoOutput {
                    id: videoOut
                    anchors.fill: parent
                    fillMode: VideoOutput.PreserveAspectFit
                }
            }
        }

        // The play marker — DRAWN, not lettered: "▶" is U+25B6 and two of the
        // three pixel fonts return glyph 0 for it (docs/DESIGN.md §2.3), so the
        // staircase filer's video tiles wear is the marker here too.
        Rectangle {
            id: marker
            anchors.centerIn: parent
            width: 28
            height: 28
            visible: !video.playing && !video.failed
            color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.72)
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            Item {
                anchors.centerIn: parent
                width: 13
                height: 13
                // Paused mid-clip, the marker is a play mark again; only the
                // rows differ, so one Repeater draws both (§5.4: one shape, two
                // states, never two widgets).
                Repeater {
                    model: 13
                    Rectangle {
                        required property int index
                        y: index
                        height: 1
                        x: 0
                        width: 7 - Math.abs(index - 6)
                        color: Theme.text
                    }
                }
            }
        }

        // A stream the decoder would not take (§10 — never a black box).
        PixelText {
            anchors.centerIn: parent
            visible: video.failed
            width: frame.width - 16
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: "can't play this stream"
            color: Theme.crit
        }

        // Click the picture: start it, then play/pause it.
        MouseArea {
            id: hover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (!frame.started) {
                    frame.started = true;
                    return;
                }
                if (video.item === null) return;
                if (video.playing) video.item.player.pause();
                else video.item.player.play();
            }
        }

        // ---- the transport strip -------------------------------------------
        // Inside the artwork, on hover or while it plays (§5.1: a label moves
        // INTO the picture rather than claiming a strip of its own), and gone
        // entirely for a live stream, which has nothing to scrub.
        Rectangle {
            id: transport
            visible: frame.started && !card.live && (hover.containsMouse || !video.playing)
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                      margins: 1 }
            height: Theme.lineHeight + 8
            color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.82)

            Row {
                anchors { fill: parent; leftMargin: 6; rightMargin: 6 }
                spacing: 6

                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    // Fixed slots: the elapsed clock must not resize the track
                    // under the pointer every second (§5.4).
                    width: 34
                    text: card.clock(video.pos)
                    color: Theme.text
                }
                // The scrub track. A direct manipulation: the fill follows the
                // pointer with no easing and the seek happens as it moves
                // (§6.4), so the picture is where the finger is.
                Rectangle {
                    id: track
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(20, parent.width - 12 - 34 - 34 - 12)
                    height: 6
                    radius: Theme.rounding
                    color: Theme.bgAlt
                    border.width: Theme.ctrlBorder
                    border.color: Theme.border

                    Rectangle {
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom
                                  margins: 1 }
                        width: video.dur > 0
                               ? Math.max(0, (track.width - 2) * (video.pos / video.dur))
                               : 0
                        radius: Theme.rounding
                        color: Theme.accent
                    }
                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -6      // the hit band exceeds the ink (§5.3)
                        preventStealing: true
                        function seek(x) {
                            if (video.item === null || video.dur <= 0) return;
                            var f = Math.max(0, Math.min(1, x / track.width));
                            video.item.player.position = Math.round(f * video.dur);
                        }
                        onPressed: (m) => seek(m.x)
                        onPositionChanged: (m) => { if (pressed) seek(m.x); }
                    }
                }
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 34
                    horizontalAlignment: Text.AlignRight
                    text: card.clock(video.dur)
                    color: Theme.textDim
                }
            }
        }
    }

    // ---- the caption --------------------------------------------------------
    PixelText {
        visible: card.ok && card.caption !== ""
        width: card.width
        wrapMode: Text.Wrap
        text: card.caption
        color: Theme.textDim
    }
}

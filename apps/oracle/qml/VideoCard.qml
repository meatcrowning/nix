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
    // Where a fullscreen video goes: the scene-level VideoStage in Root.qml.
    // The stage builds no second player — it BORROWS this one, pointing its own
    // surface at it and handing it back on the way out, so going full and
    // coming back neither restarts the stream nor loses the position.
    property Item stage: null
    // Root, for the mini-player: the card tells it when a player is built (so
    // it can show the transport when this card's bubble is off-screen) and
    // when the card is destroyed. Nullable, so the card still works bare.
    property var host: null
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

    // The duration in ms: the player's own once it knows it, else what the
    // resolver said — so the clock is not 0:00 for the first second of a stream.
    readonly property real dur: {
        if (video.item !== null && video.item.player.duration > 0)
            return video.item.player.duration;
        return (ok && entry.duration > 0) ? entry.duration * 1000 : 0;
    }
    readonly property bool full:
        !!stage && video.item !== null && stage.playing === video.item.player

    // Hand this card's player to the stage, or take it back.
    function toggleFull() {
        if (!stage || video.item === null) return;
        if (full) stage.close();
        else stage.open(video.item.player, video.item.out, card);
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
            // Back on view while the picture is away on the stage — a card
            // showing a black rectangle would read as broken.
            visible: card.poster !== "" && (!video.playing || card.full)
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
            // A player was built: tell the mini-player it exists to follow.
            onLoaded: if (card.host && card.host.videoCardActive)
                card.host.videoCardActive(card)
        }

        Component {
            id: playerComp
            Item {
                property alias player: player
                property alias out: videoOut
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
            visible: (!video.playing || card.full) && !video.failed
            color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.72)
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            Item {
                anchors.centerIn: parent
                width: 13
                height: 13
                // Rows 0..12 widen 1,3,5,7,5,3,1 — a symmetric arrowhead
                // pointing right, centred on the middle row.
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
        // Inside the artwork, on hover or while it is paused (§5.1: a label
        // moves INTO the picture rather than claiming a strip of its own), and
        // absent for a live stream, which has nothing to scrub. The same strip
        // the fullscreen stage wears — VideoTransport.qml.
        //
        // The visibility ORs the transport's own `pointerHere` into `hover`
        // (see VideoTransport's header comment): without it, moving the pointer
        // onto the strip's controls steals `hover.containsMouse` from the
        // whole-frame tracker below, the strip's condition goes false, it
        // hides under the pointer, and the mouse is handed back — the
        // pop-in-and-out glitch while manipulating it.
        VideoTransport {
            id: videoTransport
            visible: frame.started && !card.live
                     && (hover.containsMouse || videoTransport.pointerHere
                         || !video.playing)
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                      margins: 1 }
            player: video.item !== null ? video.item.player : null
            dur: card.dur
            full: card.full
            onToggleFull: card.toggleFull()
        }
    }

    // The player it built is being torn down (a session switch or a reload) —
    // tell the mini-player so it stops following a card that no longer exists.
    Component.onDestruction: if (host && host.videoCardGone)
        host.videoCardGone(card)

    // ---- the caption --------------------------------------------------------
    PixelText {
        visible: card.ok && card.caption !== ""
        width: card.width
        wrapMode: Text.Wrap
        text: card.caption
        color: Theme.textDim
    }
}

import QtQuick
import QtQuick.Controls as QQC
import QtMultimedia
import ".." as Base

// ONE video in a reply, as a card the size of the bubble — in an Oxygen session.
//
// Same API as `../VideoCard.qml` — `entry`, `stage`, `host`, `contextRequested`,
// and the read-only `dur` / `full` / `volume` / `caption` the deck, the stage
// and the mini-player all read — and the same three rules it exists to keep:
// it does not start on its own, the decoder is built on the click (a transcript
// holding six videos he never played must not pay for six), and a failure is
// DRAWN rather than left as a black rectangle.
//
// What changes: the frame is the style's own `Frame`, the play marker is the
// icon theme's `media-playback-start` on a real `ToolButton` instead of a
// hand-stacked arrowhead of 1px rows, and every caption is a `Label`. The
// transport strip is the shared `VideoTransport` — one control file for the
// card, the stage and the mini-player — reached through the parent directory so
// the selector still hands back the KStyle face of it.
Column {
    id: card

    property string face: "oxygen"

    property var entry: null
    property Item stage: null
    property var host: null
    signal contextRequested(string path, real x, real y)

    readonly property bool ok: !!entry && entry.ok === true
    readonly property string src: ok ? (entry.src || "") : ""
    readonly property string poster: (ok && entry.poster) ? entry.poster : ""
    readonly property bool live: ok && entry.live === true
    readonly property string caption:
        ok ? ((entry.alt || "") !== "" ? entry.alt : (entry.title || "")) : ""
    readonly property string meta: (ok && entry.meta) ? entry.meta : ""

    readonly property real aspect:
        (ok && entry.w > 0 && entry.h > 0) ? (entry.h / entry.w) : (9 / 16)
    // The gallery's ceiling for a still, so a portrait clip and a portrait
    // picture take the same room in a reply.
    readonly property int maxH: 320

    spacing: 2

    readonly property real dur: {
        if (video.item !== null && video.item.player.duration > 0)
            return video.item.player.duration;
        return (ok && entry.duration > 0) ? entry.duration * 1000 : 0;
    }
    readonly property bool full:
        !!stage && video.item !== null && stage.playing === video.item.player

    // ONE VOLUME FOR EVERY CLIP: the card holds none of its own, it reads
    // Root's and writes back through it. Bare (no host), a card is simply loud.
    readonly property real volume:
        (host && host.clipVolume !== undefined) ? host.clipVolume : 1
    function setVolume(v) {
        if (host && host.setClipVolume) host.setClipVolume(v);
    }

    // Hand this card's player to the stage, or take it back.
    function toggleFull() {
        if (!stage || video.item === null) return;
        if (full) stage.close();
        else stage.open(video.item.player, video.item.out, card);
    }

    // ---- the failure line ---------------------------------------------------
    QQC.Label {
        visible: !card.ok
        width: card.width
        wrapMode: Text.Wrap
        text: "video: " + ((entry && entry.error) ? entry.error : "could not be shown")
        color: Theme.crit
    }

    // ---- the picture --------------------------------------------------------
    QQC.Frame {
        id: frame
        visible: card.ok
        width: card.width
        height: Math.min(Math.round(card.width * card.aspect), card.maxH)
        clip: true
        padding: 1

        // Has he asked for this one yet? Nothing below exists until he has.
        property bool started: false

        contentItem: Item {
            Image {
                id: posterImg
                anchors.fill: parent
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
                anchors.fill: parent
                active: frame.started
                sourceComponent: playerComp
                // The card asks the item questions rather than reaching into
                // it, so everything here survives the Loader being inactive.
                readonly property bool playing:
                    item !== null && item.player.playbackState === MediaPlayer.PlayingState
                readonly property bool failed:
                    item !== null && item.player.error !== MediaPlayer.NoError
                readonly property real pos: item !== null ? item.player.position : 0
                onLoaded: if (card.host && card.host.videoCardActive)
                    card.host.videoCardActive(card)
            }
        }

        Component {
            id: playerComp
            Item {
                property alias player: player
                property alias out: videoOut
                AudioOutput { id: audioOut; volume: card.volume }
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

        // The play marker: the icon theme's own transport mark on the style's
        // own tool button, so the verb is drawn the way every KDE player draws
        // it. Not in the input path — the frame-wide MouseArea above is what
        // starts it — but it is the affordance saying the click is there.
        QQC.ToolButton {
            id: marker
            anchors.centerIn: parent
            visible: (!video.playing || card.full) && !video.failed
            enabled: false
            opacity: 0.9
            icon.name: "media-playback-start"
            icon.color: palette.buttonText
            display: QQC.AbstractButton.IconOnly
        }

        // A stream the decoder would not take — never a black box.
        QQC.Label {
            anchors.centerIn: parent
            visible: video.failed
            width: frame.width - 16
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: "can't play this stream"
            color: Theme.crit
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.RightButton
            onClicked: function (m) {
                var p = mapToItem(null, m.x, m.y);
                var f = card.ok ? (card.entry.path || "") : "";
                if (f !== "") card.contextRequested(f, p.x, p.y);
            }
        }

        // ---- the transport strip -------------------------------------------
        // Inside the artwork, on hover or while it is paused, and absent for a
        // live stream, which has nothing to scrub.
        //
        // THE STRIP DOES NOT FLICKER. Hover alone is a feedback loop: the strip
        // appears under the pointer, the appearance costs the frame tracker its
        // `containsMouse`, and the condition that showed it hides it again. So
        // the pointer only ever TURNS IT ON, and a timer turns it off a moment
        // after the pointer has actually gone.
        property bool pointerOnClip: hover.containsMouse || videoTransport.pointerHere
        onPointerOnClipChanged: {
            if (frame.pointerOnClip) { stripLinger.stop(); frame.stripShown = true; }
            else stripLinger.restart();
        }
        property bool stripShown: false
        Timer {
            id: stripLinger
            interval: 900
            onTriggered: frame.stripShown = frame.pointerOnClip
        }

        Base.VideoTransport {
            id: videoTransport
            visible: frame.started && !card.live
                     && (frame.stripShown || !video.playing)
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                      margins: 1 }
            player: video.item !== null ? video.item.player : null
            dur: card.dur
            full: card.full
            volume: card.volume
            onVolumeSet: (v) => card.setVolume(v)
            onToggleFull: card.toggleFull()
        }
    }

    // The player it built is being torn down (a session switch or a reload) —
    // tell the mini-player so it stops following a card that no longer exists.
    Component.onDestruction: if (host && host.videoCardGone)
        host.videoCardGone(card)

    // ---- the caption --------------------------------------------------------
    QQC.Label {
        visible: card.ok && (card.caption !== "" || card.meta !== "")
        width: card.width
        elide: Text.ElideRight
        text: card.caption
        opacity: 0.75
    }
    QQC.Label {
        visible: card.ok && card.meta !== ""
        width: card.width
        elide: Text.ElideRight
        text: card.meta
        opacity: 0.55
    }
}

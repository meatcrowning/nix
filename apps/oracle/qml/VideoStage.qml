import QtQuick
import QtMultimedia
import "../../qmlcommon"

// One video, filling the window, over the conversation.
//
// [his, 2026-08-23] — "can you add a fullscreen button to videos?" The image
// lightbox's counterpart for a moving picture, and the same kind of object: an
// OVERLAY, not a window (chatter's chrome is the compositor's, §12), sitting in
// the one Item both faces mount, so Hyprland and Plasma get it alike.
//
// It BORROWS the card's player rather than building one. A MediaPlayer's
// `videoOutput` is just where its frames land, so pointing it at this surface
// and back again moves the picture without restarting the stream, re-buffering
// it, or losing the position — which a second player, or a reparented card,
// would each do. Nothing here owns state: close() hands the player back exactly
// as it was handed over.
Item {
    id: stage

    anchors.fill: parent
    z: 290                      // under the image lightbox (300), over the log

    // The borrowed MediaPlayer, and where its picture goes home to.
    property var playing: null
    property var homeOutput: null
    property Item card: null

    readonly property real dur: card ? card.dur : 0
    readonly property string caption: card ? card.caption : ""

    function open(player, cardOutput, fromCard) {
        playing = player;
        homeOutput = cardOutput;
        card = fromCard;
        player.videoOutput = out;
        opened = true;
        forceActiveFocus();
    }
    function close() {
        if (playing && homeOutput)
            playing.videoOutput = homeOutput;
        playing = null;
        homeOutput = null;
        card = null;
        opened = false;
        closed();
    }

    signal closed()

    property bool opened: false
    // `visible` follows the FADE, not the flag, so the fade-out is seen and the
    // overlay stops taking clicks the moment it is gone (§6.7).
    visible: opacity > 0.001
    enabled: opened
    opacity: opened ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: motion.ms(motion.slideMs)
                          easing.type: motion.slideEasing }
    }
    Motion { id: motion }

    focus: opened
    onOpenedChanged: if (opened) forceActiveFocus()
    Keys.onEscapePressed: stage.close()
    Keys.onSpacePressed: {
        if (!stage.playing) return;
        if (stage.playing.playbackState === MediaPlayer.PlayingState)
            stage.playing.pause();
        else
            stage.playing.play();
    }

    // The ground: the window's own surface at 96%, not black — the palette owns
    // the colour here too (§3.1), and a video wants a darker room than a still.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.96)
        MouseArea {
            anchors.fill: parent
            onClicked: stage.close()
        }
    }

    VideoOutput {
        id: out
        anchors { fill: parent; margins: 12
                  topMargin: 12 + capBand.height + 6; bottomMargin: 28 }
        fillMode: VideoOutput.PreserveAspectFit
        // Click the picture to play/pause; the ground behind it closes.
        MouseArea {
            id: pic
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (!stage.playing) return;
                if (stage.playing.playbackState === MediaPlayer.PlayingState)
                    stage.playing.pause();
                else
                    stage.playing.play();
            }
        }
    }

    // The title, and what closes it, stated once (§8.1: the fact and nothing
    // else) — IN A BAND, over the top of the picture rather than in a margin
    // beside it [his, 2026-08-24: the caption "is not visible" in fullscreen].
    // A dim line on the ground at the very edge of the window is a line he has
    // to go looking for; the same translucent strip the transport wears makes
    // it part of the same object, and `z` puts it over the video whatever the
    // picture's shape leaves free. Full text colour, not dim: this is the one
    // thing on screen naming what he is watching.
    Rectangle {
        id: capBand
        z: 5
        anchors { left: parent.left; right: parent.right; top: parent.top
                  margins: 12 }
        height: Theme.lineHeight + 8
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.82)
        radius: Theme.rounding
        visible: stage.caption !== "" || stage.opened

        PixelText {
            anchors { left: parent.left; leftMargin: 8
                      right: escLabel.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            elide: Text.ElideRight
            text: stage.caption
            color: Theme.text
        }
        PixelText {
            id: escLabel
            anchors { right: parent.right; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            text: "esc"
            color: Theme.textDim
        }
    }

    // The same strip the card wears, with the mark turned inward.
    VideoTransport {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  margins: 12 }
        visible: !!stage.playing
        player: stage.playing
        dur: stage.dur
        full: true
        volume: stage.card ? stage.card.volume : 1
        onVolumeSet: (v) => { if (stage.card) stage.card.setVolume(v); }
        onToggleFull: stage.close()
    }
}

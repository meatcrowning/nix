import QtQuick
import QtMultimedia
import "../../qmlcommon"

// The mini-player: a compact strip pinned to the TOP of the message view that
// appears only while a video is playing whose bubble is NOT in view [his,
// 2026-08-23: "when a video is playing and its chat bubble is not in view, can
// it show a little playing preview thing at the top of the message box? so the
// user always has access to scrobbling, play/pause/stop etc."].
//
// It BORROWS the card's player exactly the way the fullscreen VideoStage does —
// the player's `videoOutput` is just where its frames land, so pointing it at
// this small surface and back again moves the picture without restarting the
// stream or losing the position. The card is off-screen when this shows, so
// the frames are not being missed; when the card scrolls back into view Root
// closes it and the picture goes home.
//
// The transport is the SAME VideoTransport the card and the stage wear (one
// control file, docs/DESIGN.md §0.1), so scrubbing, play/pause, stop and
// fullscreen behave identically everywhere. A dismiss button closes the bar
// (playback state is untouched); fullscreen closes it too, then opens the
// stage, because a player's videoOutput can only be one surface at a time.
Item {
    id: mini

    // The borrowed MediaPlayer and where its picture goes home to.
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
    }
    function close() {
        if (playing && homeOutput)
            playing.videoOutput = homeOutput;
        playing = null;
        homeOutput = null;
        card = null;
        opened = false;
    }
    // Fullscreen from the bar: hand the picture back to the card first, then
    // let the card throw it to the stage — one videoOutput at a time.
    function goFull() {
        var c = card;
        if (c) { close(); c.toggleFull(); }
    }

    // The user closed the bar on this card — Root remembers it so the bar does
    // not reopen the instant it is dismissed.
    signal dismissedCard(var card)

    property bool opened: false
    // `visible` follows the FADE, not the flag, so the fade-out is seen and the
    // bar stops taking clicks the moment it is gone (§6.7).
    visible: opacity > 0.001
    enabled: opened
    opacity: opened ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: motion.ms(motion.slideMs)
                          easing.type: motion.slideEasing }
    }
    Motion { id: motion }

    // The bar itself, floating over the top of the conversation.
    Rectangle {
        id: strip
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: barRow.height + 8
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.94)
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        Row {
            id: barRow
            anchors { fill: parent; margins: 4 }
            spacing: 6

            // The live frame, small — the "preview" part of the mini-player.
            VideoOutput {
                id: out
                width: 96
                height: 54
                fillMode: VideoOutput.PreserveAspectFit
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (!mini.playing) return;
                        if (mini.playing.playbackState === MediaPlayer.PlayingState)
                            mini.playing.pause();
                        else mini.playing.play();
                    }
                }
            }

            // Caption + transport, stacked beside the preview.
            Column {
                width: strip.width - out.width - 6 - 24 - 6 - 8
                spacing: 0

                PixelText {
                    width: parent.width
                    elide: Text.ElideRight
                    text: mini.caption
                    color: Theme.textDim
                }
                VideoTransport {
                    width: parent.width
                    player: mini.playing
                    dur: mini.dur
                    full: false
                    volume: mini.card ? mini.card.volume : 1
                    onVolumeSet: (v) => { if (mini.card) mini.card.setVolume(v); }
                    onToggleFull: mini.goFull()
                }
            }

            // Dismiss the bar. Playback state is untouched — this only stops
            // following the card; the video keeps doing whatever it was doing.
            // The card is passed out so Root can remember the dismissal (the
            // bar must not reopen the moment it is closed).
            Item {
                width: 24
                height: 24
                Rectangle {
                    anchors.centerIn: parent
                    width: 12
                    height: 12
                    // Two 1px diagonals — an X, drawn not lettered (§2.3).
                    Rectangle {
                        anchors.centerIn: parent
                        width: 12
                        height: 1
                        rotation: 45
                        color: dismiss.containsMouse ? Theme.accent : Theme.text
                    }
                    Rectangle {
                        anchors.centerIn: parent
                        width: 12
                        height: 1
                        rotation: -45
                        color: dismiss.containsMouse ? Theme.accent : Theme.text
                    }
                }
                MouseArea {
                    id: dismiss
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        mini.dismissedCard(mini.card);
                        mini.close();
                    }
                }
            }
        }
    }
}

import QtQuick
import QtQuick.Controls as QQC
import QtMultimedia
import ".." as Base

// The mini-player in an Oxygen session: a compact strip pinned to the top of
// the message view while a video is playing whose bubble is NOT in view.
//
// It BORROWS the card's player exactly the way the fullscreen VideoStage does —
// the player's `videoOutput` is just where its frames land, so pointing it at
// this small surface and back again moves the picture without restarting the
// stream or losing the position.
//
// Same API as `../MiniPlayer.qml` — `open()`, `close()`, `goFull()`, `playing`,
// `card`, `opened`, `dismissedCard(var)` — so Root is untouched. What changes:
// the hand-drawn bar becomes the style's own `Frame`, the caption a `Label`,
// and the two 1px diagonals that dismissed it become a `ToolButton` wearing
// `window-close`. The transport is still the one shared `VideoTransport`, so
// scrubbing behaves identically in the card, the bar and the stage.
Item {
    id: mini

    property string face: "oxygen"

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

    readonly property int oxMs: DeskStyle.styleMs > 0 ? DeskStyle.styleMs : 150

    property bool opened: false
    // `visible` follows the FADE, not the flag, so the bar stops taking clicks
    // the moment it is gone.
    visible: opacity > 0.001
    enabled: opened
    opacity: opened ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: mini.oxMs; easing.type: Easing.InOutQuad }
    }

    // The bar itself, floating over the top of the conversation — the style's
    // own frame, so it reads as a KDE panel rather than as a drawn slab.
    QQC.Frame {
        id: strip
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: barRow.height + topPadding + bottomPadding

        contentItem: Row {
            id: barRow
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
                width: Math.max(1, barRow.width - out.width - dismissBtn.width
                                   - 2 * barRow.spacing)
                spacing: 0

                QQC.Label {
                    width: parent.width
                    elide: Text.ElideRight
                    text: mini.caption
                    opacity: 0.75
                }
                Base.VideoTransport {
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
            // The card is passed out so Root can remember the dismissal.
            QQC.ToolButton {
                id: dismissBtn
                icon.name: "window-close"
                display: QQC.AbstractButton.IconOnly
                QQC.ToolTip.visible: hovered
                QQC.ToolTip.text: "hide this bar"
                onClicked: {
                    mini.dismissedCard(mini.card);
                    mini.close();
                }
            }
        }
    }
}

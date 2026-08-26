import QtQuick
import QtQuick.Controls as QQC
import QtMultimedia
import ".." as Base

// One video, filling the window, over the conversation — in an Oxygen session.
//
// The lightbox's counterpart for a moving picture, and an OVERLAY for the same
// reasons stated at the top of `+oxygen/Lightbox.qml`: a Popup here could not
// leave the QQuickWidget's rect anyway, and a real modal window would be a
// second titlebar and a second taskbar entry for watching a clip.
//
// It BORROWS the card's player rather than building one. A MediaPlayer's
// `videoOutput` is just where its frames land, so pointing it at this surface
// and back again moves the picture without restarting the stream, re-buffering
// it, or losing the position. Nothing here owns state: `close()` hands the
// player back exactly as it was handed over.
//
// Same API as `../VideoStage.qml` — `open()`, `close()`, `playing`, `card`,
// `closed()` — so Root and every VideoCard are untouched. What changes is the
// hand: the caption band is the style's surface with a `Label` on it, close is
// a `ToolButton` wearing `window-close`, and the fade runs at Oxygen's own
// `GenericAnimationsDuration`.
Item {
    id: stage

    property string face: "oxygen"

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

    readonly property int oxMs: DeskStyle.styleMs > 0 ? DeskStyle.styleMs : 150
    readonly property color surface: pal.palette.window
    QQC.Label { id: pal; visible: false }

    property bool opened: false
    // `visible` follows the FADE, not the flag, so the overlay stops taking
    // clicks the moment it is gone.
    visible: opacity > 0.001
    enabled: opened
    opacity: opened ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: stage.oxMs; easing.type: Easing.InOutQuad }
    }

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

    // The ground: the style's own window brush at 96% — a video wants a darker
    // room than a still, and the colour is still the session's.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(stage.surface.r, stage.surface.g, stage.surface.b, 0.96)
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

    // The title and the way out, IN A BAND over the top of the picture rather
    // than in a margin beside it — a dim line at the very edge of the window is
    // one he has to go looking for. The same translucent strip the transport
    // wears makes it part of the same object, and `z` puts it over the video
    // whatever the picture's shape leaves free.
    Rectangle {
        id: capBand
        z: 5
        anchors { left: parent.left; right: parent.right; top: parent.top
                  margins: 12 }
        height: Math.max(Theme.lineHeight + 8, closeBtn.implicitHeight + 4)
        color: Qt.rgba(stage.surface.r, stage.surface.g, stage.surface.b, 0.82)
        visible: stage.caption !== "" || stage.opened

        QQC.Label {
            anchors { left: parent.left; leftMargin: 8
                      right: closeBtn.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            elide: Text.ElideRight
            text: stage.caption
        }
        // CLOSE — a mark he can click, not a keyboard hint. Esc still works;
        // this is the same act with an affordance on it, in the icon theme's
        // own vocabulary.
        QQC.ToolButton {
            id: closeBtn
            anchors { right: parent.right; rightMargin: 4
                      verticalCenter: parent.verticalCenter }
            icon.name: "window-close"
            display: QQC.AbstractButton.IconOnly
            QQC.ToolTip.visible: hovered
            QQC.ToolTip.text: "close"
            onClicked: stage.close()
        }
    }

    // The same strip the card wears, with the mark turned inward.
    Base.VideoTransport {
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

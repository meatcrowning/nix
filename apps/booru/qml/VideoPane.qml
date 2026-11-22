import QtQuick
import QtQuick.Controls
import QtMultimedia
import "../../qmlcommon"

// A post's video, played from the disk cache (main.py `media`): looped,
// click to pause, and a scrub bar that seeks on release (docs/DESIGN.md 6.4).
// Loaded on demand by Root.qml so a missing QtMultimedia costs only video.
Item {
    id: pane
    property string source: ""
    property bool muted: true

    MediaPlayer {
        id: player
        source: pane.source
        loops: MediaPlayer.Infinite
        videoOutput: out
        audioOutput: AudioOutput { muted: pane.muted }
        Component.onCompleted: play()
        onSourceChanged: play()
    }
    VideoOutput {
        id: out
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: bar.top; bottomMargin: 4 }
        fillMode: VideoOutput.PreserveAspectFit
        MouseArea {
            anchors.fill: parent
            onClicked: player.playbackState === MediaPlayer.PlayingState ? player.pause() : player.play()
        }
    }
    PixelText {
        anchors.centerIn: out
        visible: player.error !== MediaPlayer.NoError
        text: player.errorString
        color: Theme.crit
    }
    Slider {
        id: bar
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        from: 0
        to: Math.max(1, player.duration)
        Binding on value { when: !bar.pressed; value: player.position; restoreMode: Binding.RestoreNone }
        onPressedChanged: if (!pressed) player.position = value
        enabled: player.seekable
    }
}

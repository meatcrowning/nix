import QtQuick
import QtQuick.Controls as QQC
import QtMultimedia

// The video's transport strip in an Oxygen session.
//
// `+plasma/VideoTransport.qml` already uses the style's Slider and Labels, but
// three things in it are still ours: the band is filled from `Theme.bg` (the
// wallpaper-derived palette, which nothing else in a Plasma window wears), its
// height is measured off `Theme.lineHeight` and a magic 38px slot holds each
// clock, and the two controls are `Button { flat: true }`.
//
// Oxygen's own vocabulary for a row of icon-only controls is a TOOLBAR OF TOOL
// BUTTONS — `ToolButton` is the widget every KDE media strip is built from, and
// it is what Oxygen gives its own hover and press relief to. The clock slots are
// measured from the widest string they can hold in the style's own font
// (`TextMetrics`) instead of being guessed, so the scrub never shifts under the
// pointer and never depends on a number picked by eye. The band keeps the
// system window colour at the same 0.82 the sibling used: it lies over moving
// picture, and a Frame or an opaque ToolBar would put a lit relief between him
// and the video.
//
// Tooltips are capitalised, because a KDE tooltip is a sentence the platform
// writes, not a lowercase desktop label.
//
// Same API as the sibling — `player`, `dur`, `full`, `volume`, `toggleFull()`,
// `volumeSet()`, `pointerHere` — so VideoCard, VideoStage and MiniPlayer are
// untouched.
Rectangle {
    id: bar

    property string face: "oxygen"      // how a harness proves which one loaded
    property var player: null
    property real dur: 0
    property bool full: false

    signal toggleFull()

    readonly property real pos: player ? player.position : 0
    // The volume, handed in and reported back — the strip owns nothing, so one
    // clip's level is every clip's level (see the sibling's header).
    property real volume: 1
    signal volumeSet(real v)
    // The card's hover logic reads this: the Slider and the ToolButtons take the
    // mouse the moment he reaches for them, and without it the strip hides under
    // the pointer trying to use it.
    readonly property bool pointerHere:
        barHit.containsMouse || scrub.hovered || fsBtn.hovered
        || volBtn.hovered || vol.hovered

    MouseArea {
        id: barHit
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }

    height: Math.max(elapsed.implicitHeight + 8, fsBtn.implicitHeight + 4)
    color: Qt.rgba(bar.palette.window.r, bar.palette.window.g,
                   bar.palette.window.b, 0.82)

    function clock(ms) {
        if (!(ms > 0)) return "0:00";
        var t = Math.floor(ms / 1000);
        var m = Math.floor(t / 60);
        var s = t % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    // The clock slot, measured rather than guessed: the widest run a timer of
    // this length can produce, in the style's own font. A clock that resizes
    // would shove the scrub sideways under the pointer once a second.
    TextMetrics {
        id: slot
        font: elapsed.font
        text: bar.dur >= 3600000 ? "88:88:88" : "88:88"
    }

    QQC.Label {
        id: elapsed
        anchors { left: parent.left; leftMargin: 8
                  verticalCenter: parent.verticalCenter }
        width: Math.ceil(slot.width)
        text: bar.clock(bar.pos)
    }

    // A direct manipulation: the handle follows the pointer with no easing and
    // the seek happens as it moves, so the picture is where the finger is.
    // `moved` fires for a drag and for a click on the groove; the value is only
    // pushed back from the player while he is NOT holding it.
    QQC.Slider {
        id: scrub
        anchors { left: elapsed.right; right: total.left
                  leftMargin: 6; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        from: 0
        to: Math.max(1, bar.dur)
        value: bar.pos
        enabled: bar.dur > 0 && bar.player !== null
        onMoved: if (bar.player && bar.dur > 0) bar.player.position = Math.round(value)
    }

    QQC.Label {
        id: total
        anchors { right: volBtn.left; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        width: Math.ceil(slot.width)
        horizontalAlignment: Text.AlignRight
        text: bar.clock(bar.dur)
        // The total is the subordinate of the pair; the style's disabled
        // foreground is how Oxygen says so.
        enabled: false
    }

    // THE VOLUME ROCKER. Oxygen ships the four `audio-volume-*` icons for
    // exactly this, and a ToolButton is what it draws an icon-only control in a
    // strip as.
    QQC.ToolButton {
        id: volBtn
        anchors { right: vol.left; rightMargin: 2
                  verticalCenter: parent.verticalCenter }
        property real preMute: 1
        icon.name: bar.volume <= 0.001 ? "audio-volume-muted"
                   : bar.volume < 0.34 ? "audio-volume-low"
                   : bar.volume < 0.67 ? "audio-volume-medium"
                                       : "audio-volume-high"
        display: QQC.AbstractButton.IconOnly
        QQC.ToolTip.visible: hovered
        QQC.ToolTip.text: bar.volume <= 0.001 ? "Unmute" : "Mute"
        onClicked: {
            if (bar.volume <= 0.001)
                bar.volumeSet(volBtn.preMute > 0.01 ? volBtn.preMute : 1);
            else { volBtn.preMute = bar.volume; bar.volumeSet(0); }
        }
    }

    QQC.Slider {
        id: vol
        anchors { right: fsBtn.left; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        width: 60
        from: 0
        to: 1
        value: bar.volume
        onMoved: bar.volumeSet(value)
    }

    // FULLSCREEN, with the session's own icon — Oxygen ships `view-fullscreen`
    // and `view-restore` for exactly this verb.
    QQC.ToolButton {
        id: fsBtn
        anchors { right: parent.right; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        icon.name: bar.full ? "view-restore" : "view-fullscreen"
        display: QQC.AbstractButton.IconOnly
        // The text is the tooltip's, not the button's — a two-word label beside
        // a video is noise, and the icon is the KDE vocabulary for this verb.
        QQC.ToolTip.visible: hovered
        QQC.ToolTip.text: bar.full ? "Leave fullscreen" : "Fullscreen"
        onClicked: bar.toggleFull()
    }
}

import QtQuick
import QtQuick.Controls as QQC
import QtMultimedia

// The video's transport strip in a Plasma session: the STYLE'S OWN controls.
//
// `../VideoTransport.qml` draws every pixel of itself — a rounded track with an
// accent fill, and a fullscreen mark built from four 1px corner brackets. That
// is right under Hyprland and wrong in a KDE window, where the same three
// controls exist in the style already: a `Slider`, a `Button`, and two `Label`s.
// It is the rule player's transport bar was rebuilt under (docs/DESIGN.md §7.6 —
// where an app can be a real KDE window, it is one; player's hand-drawn
// `PlayBar.qml` is gone for exactly this reason).
//
// Same API as the sibling — `player`, `dur`, `full`, `toggleFull()` — so
// VideoCard and VideoStage are untouched.
//
// The strip itself stays a translucent band rather than a `Frame`: it lies over
// moving picture, and the style's frame would put a lit relief between him and
// the video. The colour is the session's own (`Theme.bg` is KDE-derived under
// Plasma, `apps/pylib/kdetheme.py`).
Rectangle {
    id: bar

    property string face: "plasma"      // how a harness proves which one loaded
    property var player: null
    property real dur: 0
    property bool full: false

    signal toggleFull()

    readonly property real pos: player ? player.position : 0
    // The volume, handed in and reported back — the strip owns nothing, so one
    // clip's level is every clip's level (see the sibling's header).
    property real volume: 1
    signal volumeSet(real v)
    // THE SAME CONTRACT AS THE SIBLING, and the half that was missing until
    // 2026-08-24: `pointerHere` did not exist here at all, so under Plasma the
    // card's hover logic read `undefined` and had only its own frame tracker to
    // go on — and the Slider and the Button take the mouse the moment he
    // reaches for them. That is the bar he watched "flip constantly from being
    // visible to invisible" while trying to scrub. NoButton over the whole
    // strip, plus the two controls' own `hovered`.
    readonly property bool pointerHere:
        barHit.containsMouse || scrub.hovered || fsBtn.hovered
        || volBtn.hovered || vol.hovered

    MouseArea {
        id: barHit
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }

    height: Math.max(Theme.lineHeight + 8, fsBtn.implicitHeight + 4)
    color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.82)

    function clock(ms) {
        if (!(ms > 0)) return "0:00";
        var t = Math.floor(ms / 1000);
        var m = Math.floor(t / 60);
        var s = t % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    QQC.Label {
        id: elapsed
        anchors { left: parent.left; leftMargin: 8
                  verticalCenter: parent.verticalCenter }
        // A FIXED slot (§5.4): a clock that resizes would shove the scrub
        // sideways under the pointer once a second.
        width: 38
        text: bar.clock(bar.pos)
    }

    // A direct manipulation (§6.4): the handle follows the pointer with no
    // easing and the seek happens as it moves, so the picture is where the
    // finger is. `moved` fires for a drag and for a click on the groove; the
    // value is only pushed back from the player while he is NOT holding it.
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

    // THE VOLUME ROCKER, as the style's own button and slider — Oxygen ships
    // the four `audio-volume-*` icons for exactly this, and a hand-drawn cone
    // beside a real Slider is the mismatch §7.6 exists to stop.
    QQC.Button {
        id: volBtn
        anchors { right: vol.left; rightMargin: 2
                  verticalCenter: parent.verticalCenter }
        flat: true
        property real preMute: 1
        icon.name: bar.volume <= 0.001 ? "audio-volume-muted"
                   : bar.volume < 0.34 ? "audio-volume-low"
                   : bar.volume < 0.67 ? "audio-volume-medium"
                                       : "audio-volume-high"
        icon.color: palette.buttonText
        display: QQC.AbstractButton.IconOnly
        QQC.ToolTip.visible: hovered
        QQC.ToolTip.text: bar.volume <= 0.001 ? "unmute" : "mute"
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

    QQC.Label {
        id: total
        anchors { right: volBtn.left; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        width: 38
        horizontalAlignment: Text.AlignRight
        text: bar.clock(bar.dur)
        opacity: 0.75
    }

    // FULLSCREEN, as the style's button with the session's own icon — the
    // corner-bracket mark the sibling draws is a pixel-era glyph, and Oxygen
    // ships `view-fullscreen` / `view-restore` for exactly this verb.
    QQC.Button {
        id: fsBtn
        anchors { right: parent.right; rightMargin: 6
                  verticalCenter: parent.verticalCenter }
        flat: true
        icon.name: bar.full ? "view-restore" : "view-fullscreen"
        icon.color: palette.buttonText
        display: QQC.AbstractButton.IconOnly
        // The text is the tooltip's, not the button's — a two-word label beside
        // a video is noise, and the icon is the KDE vocabulary for this.
        QQC.ToolTip.visible: hovered
        QQC.ToolTip.text: bar.full ? "leave fullscreen" : "fullscreen"
        onClicked: bar.toggleFull()
    }
}

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

    QQC.Label {
        id: total
        anchors { right: fsBtn.left; rightMargin: 6
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
        display: QQC.AbstractButton.IconOnly
        // The text is the tooltip's, not the button's — a two-word label beside
        // a video is noise, and the icon is the KDE vocabulary for this.
        QQC.ToolTip.visible: hovered
        QQC.ToolTip.text: bar.full ? "leave fullscreen" : "fullscreen"
        onClicked: bar.toggleFull()
    }
}

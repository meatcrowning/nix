import QtQuick
import QtMultimedia

// The strip along the bottom of a playing video: elapsed clock, scrub track,
// duration, and the button that throws it full-window.
//
// One file because the card, the fullscreen stage and the mini-player wear the
// SAME strip — a second copy would be two implementations of one control, and
// the scrub is the part that must not differ between them (docs/DESIGN.md
// §0.1). Since 2026-08-23 it also carries the transport's OWN play/pause and
// stop buttons, so a video can be driven from anywhere the strip shows, not
// just by clicking the picture.
//
// `pointerHere` is the OR of every hover tracker on the strip — the four
// controls and a NoButton area over the whole of it. It
// exists because the strip's visibility can't read `hover.containsMouse`
// alone: the instant the pointer lands on the strip's own controls they steal
// the mouse from the card's whole-frame hover tracker, so a strip shown "on
// hover" hides under the pointer it just appeared under — the pop-in/pop-out
// glitch. The card ORs `pointerHere` into its visibility so the strip stays
// while the pointer is on any part of it.
Rectangle {
    id: bar

    property string face: "hypr"     // how a harness proves which one loaded

    // The MediaPlayer this drives, or null while the card has not built one.
    property var player: null
    // Duration in ms — the player's own once it knows, else what the resolver
    // said, so the clock is not 0:00 for the first second of a stream.
    property real dur: 0
    property bool full: false

    signal toggleFull()

    readonly property bool playing: player ? player.playbackState === MediaPlayer.PlayingState : false
    readonly property real pos: player ? player.position : 0
    // True while the pointer is over ANY of the strip's own controls — the
    // card's hover logic reads this so the strip does not vanish under the
    // pointer that is trying to use it (see the header comment).
    readonly property bool pointerHere:
        barHit.containsMouse || trackHit.containsMouse || fsHit.containsMouse
        || ppHit.containsMouse || stopHit.containsMouse

    height: Theme.lineHeight + 8
    color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.82)

    // m:ss in a FIXED slot (§5.4) — an elapsed clock that resizes would shove
    // the scrub track sideways under the pointer once a second.
    function clock(ms) {
        if (!(ms > 0)) return "0:00";
        var t = Math.floor(ms / 1000);
        var m = Math.floor(t / 60);
        var s = t % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    // THE WHOLE STRIP TRACKS THE POINTER, not just its four buttons [his,
    // 2026-08-24: the bar "flips constantly from being visible to invisible"
    // with the pointer on the scrub track]. `track.containsMouse` was a read of
    // a Rectangle, which has no such property — it was undefined, so the two
    // thirds of the strip that are not a button reported nothing and the card's
    // hover logic had only its own frame tracker to go on. NoButton, so every
    // press still reaches what is under it.
    MouseArea {
        id: barHit
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }

    Row {
        anchors { fill: parent; leftMargin: 6; rightMargin: 6 }
        spacing: 6

        // PLAY / PAUSE — the one control the strip did not have, and the reason
        // the mini-player exists [his, 2026-08-23: the controls must be
        // reachable when the video's bubble is off-screen]. DRAWN, not lettered:
        // ▶ is U+25B6 and ⏸/⏹ are outside the pixel fonts' cmap (§2.3). Play is
        // the right-pointing arrowhead the card's marker wears; pause is two
        // bars; the state says which is drawn.
        Item {
            id: ppBtn
            anchors.verticalCenter: parent.verticalCenter
            width: 24
            height: 24
            Item {
                anchors.centerIn: parent
                width: 12
                height: 12
                // Pause: two vertical bars.
                Row {
                    visible: bar.playing
                    anchors.centerIn: parent
                    spacing: 3
                    Repeater {
                        model: 2
                        Rectangle {
                            width: 2
                            height: 12
                            color: ppHit.containsMouse ? Theme.accent : Theme.text
                        }
                    }
                }
                // Play: the symmetric right-pointing arrowhead (rows widen then
                // narrow), same drawing as the card's start marker.
                Repeater {
                    visible: !bar.playing
                    model: 12
                    Rectangle {
                        required property int index
                        y: index
                        height: 1
                        x: 0
                        width: 1 + Math.min(index, 11 - index)
                        color: ppHit.containsMouse ? Theme.accent : Theme.text
                    }
                }
            }
            MouseArea {
                id: ppHit
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (!bar.player) return;
                    if (bar.playing) bar.player.pause();
                    else bar.player.play();
                }
            }
        }

        // STOP — pause and return to the start (§4 of transport grammar). The
        // player keeps its source; a later play restarts it.
        Item {
            id: stopBtn
            anchors.verticalCenter: parent.verticalCenter
            width: 24
            height: 24
            Rectangle {
                anchors.centerIn: parent
                width: 10
                height: 10
                radius: Theme.rounding
                color: stopHit.containsMouse ? Theme.accent : Theme.text
            }
            MouseArea {
                id: stopHit
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (!bar.player) return;
                    bar.player.pause();
                    bar.player.position = 0;
                }
            }
        }

        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            text: bar.clock(bar.pos)
            color: Theme.text
        }
        // The track. A direct manipulation: the fill follows the pointer with no
        // easing and the seek happens as it moves (§6.4), so the picture is
        // where the finger is.
        Rectangle {
            id: track
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(20, parent.width - 12 - 24 - 24 - 34 - 34 - 24 - 5 * 6)
            height: 6
            radius: Theme.rounding
            color: Theme.bgAlt
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom
                          margins: 1 }
                width: bar.dur > 0
                       ? Math.max(0, (track.width - 2) * (bar.pos / bar.dur))
                       : 0
                radius: Theme.rounding
                color: Theme.accent
            }
            MouseArea {
                id: trackHit
                anchors.fill: parent
                anchors.margins: -6      // the hit band exceeds the ink (§5.3)
                hoverEnabled: true
                preventStealing: true
                function seek(x) {
                    if (!bar.player || bar.dur <= 0) return;
                    var f = Math.max(0, Math.min(1, x / track.width));
                    bar.player.position = Math.round(f * bar.dur);
                }
                onPressed: (m) => seek(m.x)
                onPositionChanged: (m) => { if (pressed) seek(m.x); }
            }
        }
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            horizontalAlignment: Text.AlignRight
            text: bar.clock(bar.dur)
            color: Theme.textDim
        }
        // FULLSCREEN [his, 2026-08-23: "can you add a fullscreen button to
        // videos?"]. DRAWN, not lettered — the corner-bracket mark is four
        // 1px-thick L's, exact at any size and in no font's cmap (§2.3), and it
        // turns INWARD when the video is already full, which is the same shape
        // saying the opposite thing rather than a second icon.
        Item {
            id: fsBtn
            anchors.verticalCenter: parent.verticalCenter
            width: 24
            height: 24

            Item {
                anchors.centerIn: parent
                width: 14
                height: 14
                Repeater {
                    model: 4
                    delegate: Item {
                        required property int index
                        // 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right
                        // `right`/`bottom` are taken (Item's anchor lines are
                        // FINAL), hence the corner-named pair.
                        readonly property bool atRight: index === 1 || index === 3
                        readonly property bool atBottom: index >= 2
                        // Arms on the OUTER edges point outward = "make this
                        // bigger"; mirrored to the inner edges it points inward
                        // = "put it back". One shape, two states (§5.4).
                        readonly property bool out: !bar.full
                        width: 6
                        height: 6
                        x: atRight ? parent.width - width : 0
                        y: atBottom ? parent.height - height : 0
                        Rectangle {
                            width: parent.width
                            height: 1
                            y: (parent.out === !parent.atBottom) ? 0 : parent.height - 1
                            color: fsHit.containsMouse ? Theme.accent : Theme.text
                        }
                        Rectangle {
                            width: 1
                            height: parent.height
                            x: (parent.out === !parent.atRight) ? 0 : parent.width - 1
                            color: fsHit.containsMouse ? Theme.accent : Theme.text
                        }
                    }
                }
            }
            MouseArea {
                id: fsHit
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: bar.toggleFull()
            }
        }
    }
}

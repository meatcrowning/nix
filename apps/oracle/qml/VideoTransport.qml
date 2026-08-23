import QtQuick
import QtMultimedia

// The strip along the bottom of a playing video: elapsed clock, scrub track,
// duration, and the button that throws it full-window.
//
// One file because the card and the fullscreen stage wear the SAME strip — a
// second copy would be two implementations of one control, and the scrub is the
// part that must not differ between them (docs/DESIGN.md §0.1).
Rectangle {
    id: bar

    // The MediaPlayer this drives, or null while the card has not built one.
    property var player: null
    // Duration in ms — the player's own once it knows, else what the resolver
    // said, so the clock is not 0:00 for the first second of a stream.
    property real dur: 0
    property bool full: false

    signal toggleFull()

    readonly property real pos: player ? player.position : 0

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

    Row {
        anchors { fill: parent; leftMargin: 6; rightMargin: 6 }
        spacing: 6

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
            width: Math.max(20, parent.width - 12 - 34 - 34 - 24 - 3 * 6)
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
                anchors.fill: parent
                anchors.margins: -6      // the hit band exceeds the ink (§5.3)
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

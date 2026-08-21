import QtQuick
import "../../qmlcommon"

// PlayBar — the transport strip along the bottom of the window, in a PLASMA
// session only.
//
// Everywhere else this does not exist and must not: docs/DESIGN.md §7.4 gives
// player's transport, its scrub track and its position readout to the hyprvtb
// titlebar ("In-window header row removed; views get the full window"), and
// NowPlaying.qml's own comment records the same thing — "no transport controls
// and no position readout, both of which live in the titlebar". None of that
// bar exists under Plasma, where the compositor is KWin: the buttons came back
// as a menubar (qmlcommon/DeskMenuBar.qml), but the PLAYBAR line of the vtb
// protocol had nowhere to go at all, so that session had no scrub track and no
// clock. His call, 2026-08-18: give it a real one, along the bottom, where
// every other music player on that desktop keeps it.
//
// Gated on `DeskStyle.plasma` — the same switch the menubar and the palette use
// — the way DeskMenuBar gates itself: outside that session the bar is invisible
// and 0 high, so the Hyprland window keeps its full-height content and its
// titlebar scrub bar exactly as before, and the call site needs no branch.
//
// Controlled, never stateful, like Slider.qml: the fill follows
// `Player.position` and a drag or a wheel notch only calls `Player.seekFrac`,
// whose result flows back in through the same binding — so the handle can never
// disagree with the audio. Two held values are the exceptions: `dragFrac`,
// alive only while the pointer is down (a scrub that snapped back to the
// playing position on every mouse move would be unusable), and `wheelPending`,
// alive until the source catches up with the last wheel seek (so a burst of
// notches accumulates instead of each re-deriving its step from a stale
// position). Both are bounded and both defer to `Player.position`.
Item {
    id: root

    // Handed in already faded by the window (docs/DESIGN.md §3.1.1).
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    visible: plasma
    height: plasma ? 40 : 0

    readonly property bool hasTrack: Player.duration > 0 && Player.index >= 0
    // The now-playing track, for the favourite toggle — lit while it is
    // favourited, disabled when nothing is playing, exactly like the titlebar
    // column's heart (Main.qml tbButtons) and the NowPlaying header heart.
    readonly property var cur: Player.current
    readonly property bool hasCur: cur && cur.id !== undefined
    // -1 while nothing is being dragged; 0..1 while it is.
    property real dragFrac: -1
    // -1 unless a wheel notch just asked for a seek: the fill shows what we
    // ASKED for until the source's own position catches up (or `echo` gives
    // up), so a burst of notches accumulates instead of each re-deriving its
    // step from a stale position. Same 5%/1500ms/0.004 as the panel seekbar
    // (home/prog/quickshell-files/MediaContent.qml) and hyprvtb's titlebar
    // scrub track (VTB_PLAYBAR_SCROLL), docs/DESIGN.md §9.2.
    property real wheelPending: -1
    readonly property real wheelStep: 0.05
    readonly property real echoEps: 0.004
    readonly property real playFrac: hasTrack
        ? Math.max(0, Math.min(1, Player.position / Player.duration)) : 0
    readonly property real frac: dragFrac >= 0 ? dragFrac
        : (wheelPending >= 0 ? wheelPending : playFrac)
    onPlayFracChanged: if (wheelPending >= 0 && Math.abs(playFrac - wheelPending) <= echoEps) {
        wheelPending = -1; echo.stop();
    }
    Timer { id: echo; interval: 1500; onTriggered: root.wheelPending = -1 }
    function wheelSeek(n) {
        if (!root.hasTrack || n === 0)
            return;
        var t = Math.max(0, Math.min(1, root.frac + n * root.wheelStep));
        root.wheelPending = t;
        echo.restart();
        Player.seekFrac(t);
    }

    function fmt(s) {
        s = Math.max(0, Math.round(s));
        return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
    }
    function seekTo(px) {
        if (!root.hasTrack)
            return;
        Player.seekFrac(Math.max(0, Math.min(1, px / Math.max(1, track.width))));
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bg

        // The seam above the bar — the same one line the menubar draws below
        // itself, so the content sits in a plainly bounded field.
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: Theme.ctrlBorder
            color: Theme.border
        }

        // ---- transport ---------------------------------------------------
        // The same verbs, the same two-character glyphs and the same disabled
        // rule as the titlebar column (§12.1): a function that already has a
        // glyph keeps it in every place it appears. The three toggles the
        // Plasma menubar's "playback" menu carried but this bar did not —
        // favourite, repeat and shuffle — sit after the play controls, in the
        // titlebar column's own order, behind a small gap that stands in for
        // the menu's separator. A LIT toggle IS its state (§12.1): `lit` draws
        // the on ones in accent, exactly as the titlebar renders state 1.
        Row {
            id: transport
            anchors { left: parent.left; leftMargin: 8; verticalCenter: parent.verticalCenter }
            spacing: 2

            HeaderButton {
                label: "<<"
                enabled: Player.queueLength > 0
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.previous()
            }
            HeaderButton {
                label: Player.playing ? "||" : ">"
                enabled: Player.queueLength > 0
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.toggle()
            }
            HeaderButton {
                label: ">>"
                enabled: Player.queueLength > 0
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.next()
            }

            Item { width: 8; height: 1 }   // the menu's separator, as a gap

            HeaderButton {
                label: "♥"
                lit: root.hasCur && root.cur.favorite === true
                enabled: root.hasCur
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: if (root.hasCur) Library.setFavorite(root.cur.id, !root.cur.favorite)
            }
            HeaderButton {
                label: Player.loop === 1 ? "1" : "o"
                lit: Player.loop > 0
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.cycleLoop()
            }
            HeaderButton {
                label: "*"
                lit: Player.shuffle
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.setShuffle(!Player.shuffle)
            }
        }

        // ---- the clock, both ends of the track ---------------------------
        // Fixed-width slots so the track does not reflow as the digits change
        // (§5.4): the readout is the one thing on this bar that changes every
        // second.
        PixelText {
            id: elapsed
            anchors { left: transport.right; leftMargin: 10; verticalCenter: parent.verticalCenter }
            width: 40
            horizontalAlignment: Text.AlignRight
            text: root.hasTrack ? root.fmt(root.frac * Player.duration) : "-:--"
            color: root.fgDim
        }
        PixelText {
            id: total
            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
            width: 40
            text: root.hasTrack ? root.fmt(Player.duration) : "-:--"
            color: root.fgDim
        }

        // ---- the scrub track ---------------------------------------------
        Item {
            id: track
            anchors { left: elapsed.right; leftMargin: 10
                      right: total.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            height: 16

            Rectangle {     // the groove
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                height: 2
                color: Theme.border
            }
            Rectangle {     // played
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                width: Math.max(0, root.frac * track.width)
                height: 2
                color: root.hasTrack ? root.fgAccent : Theme.border
            }
            Rectangle {     // the handle
                visible: root.hasTrack
                width: 6
                height: 12
                radius: 1
                x: Math.max(0, Math.min(track.width - width, root.frac * track.width - width / 2))
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.bg
                border.width: 1
                border.color: root.fgAccent
            }

            // Press-drag-release, and a plain click seeks too — a direct
            // manipulation, so no easing anywhere near it (§6.4). The whole
            // 16px height is the target, not the 2px groove (§5.3).
            MouseArea {
                anchors.fill: parent
                enabled: root.hasTrack
                cursorShape: root.hasTrack ? Qt.PointingHandCursor : Qt.ArrowCursor
                preventStealing: true
                onPressed: (m) => { root.dragFrac = Math.max(0, Math.min(1, m.x / Math.max(1, track.width))); }
                onPositionChanged: (m) => {
                    if (pressed)
                        root.dragFrac = Math.max(0, Math.min(1, m.x / Math.max(1, track.width)));
                }
                onReleased: (m) => {
                    root.seekTo(m.x);
                    root.dragFrac = -1;
                }
                onCanceled: root.dragFrac = -1

                // Wheel scrubs, one detent = 5% of the track, a FRACTION not a
                // count of seconds (docs/DESIGN.md §9.2). WheelNotch, never a
                // sign test: a touchpad is ~125Hz of sub-pixel deltas and a
                // sign-only handler fires a full 5% per event — the bug the
                // titlebar copy had to fix. It banks the sub-detent remainder
                // and clamps a burst, so slow scrubbing still moves and a flick
                // cannot throw the song by minutes.
                WheelNotch { id: seekNotch }
                onWheel: (wheel) => {
                    var n = seekNotch.steps(wheel);
                    if (n !== 0)
                        root.wheelSeek(n);
                }
            }
        }
    }
}

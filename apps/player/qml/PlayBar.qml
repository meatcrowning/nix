import QtQuick

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
// `Player.position` and a drag only calls `Player.seekFrac`, whose result flows
// back in through the same binding — so the handle can never disagree with the
// audio. `dragFrac` is the ONE exception, held only while the pointer is down,
// because a scrub that snapped back to the playing position on every mouse move
// would be unusable.
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
    // -1 while nothing is being dragged; 0..1 while it is.
    property real dragFrac: -1
    readonly property real playFrac: hasTrack
        ? Math.max(0, Math.min(1, Player.position / Player.duration)) : 0
    readonly property real frac: dragFrac >= 0 ? dragFrac : playFrac

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
        // The same three verbs, the same two-character glyphs and the same
        // disabled rule as the titlebar column (§12.1): a function that already
        // has a glyph keeps it in every place it appears.
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
            }
        }
    }
}

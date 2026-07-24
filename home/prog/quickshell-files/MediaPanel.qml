import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Mpris

// Media player popup (SlidePopup: tiled bottom-right desktop widget, hover-kept
// / pinnable), sitting between the disk and clock widgets in the fanned row.
// Everything interactive comes from MPRIS (Quickshell.Services.Mpris): the
// active player drives the title/artist/art, the transport buttons, and the
// draggable seekbar. The spectrum below the artwork is a second cava instance
// (scripts/cava-spectrum.conf, 16 mono bars) — same plumbing as the bar's VU
// meter (VuMeter.qml), reacting to whatever's on the output sink regardless of
// which app is the MPRIS source.
SlidePopup {
    id: root

    popupNamespace: "qs-media"
    persistKey: "media"
    tileRank: 25    // between the clock (20) and weather (30)
    implicitWidth: 300
    implicitHeight: content.implicitHeight + 20

    // ---- active player selection ----------------------------------------
    // Prefer a source that's actually playing; else the first controllable
    // one; else whatever exists. Recomputes as players come and go.
    readonly property var player: {
        if (!Mpris.players) return null;
        const ps = Mpris.players.values;
        if (!ps || ps.length === 0) return null;
        for (let i = 0; i < ps.length; i++) if (ps[i].isPlaying) return ps[i];
        for (let i = 0; i < ps.length; i++) if (ps[i].canControl) return ps[i];
        return ps[0];
    }
    readonly property bool hasPlayer: player !== null
    readonly property bool playing: hasPlayer && player.isPlaying
    property var spectrumLevels: []

    // ---- repeat / shuffle state -----------------------------------------
    // Repeat cycles None -> Track -> Playlist natively when the player exposes
    // LoopStatus. When it doesn't (localLoop path), we fake a repeat-track by
    // seeking back to 0 just before the current track ends — the one loop mode
    // we can honestly implement without owning the player's queue.
    property int localLoop: 0   // 0 = off, 1 = repeat-track; only when !loopSupported

    // Effective repeat mode for the icon: 0 = off, 1 = track, 2 = playlist.
    readonly property int repeatMode: {
        if (!hasPlayer) return 0;
        if (player.loopSupported) {
            switch (player.loopState) {
                case MprisLoopState.Track: return 1;
                case MprisLoopState.Playlist: return 2;
                default: return 0;
            }
        }
        return localLoop;   // 0 or 1
    }
    // A local repeat-track can only work if we can seek. Native loop needs no seek.
    readonly property bool canRepeat: hasPlayer && (player.loopSupported || player.canSeek)

    function cycleRepeat() {
        if (!hasPlayer) return;
        if (player.loopSupported) {
            const s = player.loopState;
            player.loopState = (s === MprisLoopState.None) ? MprisLoopState.Track
                : (s === MprisLoopState.Track) ? MprisLoopState.Playlist
                : MprisLoopState.None;
        } else {
            localLoop = localLoop === 0 ? 1 : 0;
        }
    }

    // Local repeat-track enforcement: while active, watch position and jump back
    // to the start just before the track would end (and hand off to the next).
    Timer {
        interval: 250
        running: root.localLoop === 1 && root.hasPlayer
                 && !root.player.loopSupported && root.playing
        repeat: true
        onTriggered: {
            const p = root.player;
            if (!p || !p.canSeek || !p.lengthSupported || p.length <= 0) return;
            if (p.position >= p.length - 0.8) p.position = 0;
        }
    }

    // MPRIS position isn't pushed live — re-emit positionChanged on a timer
    // while playing so the seekbar binding re-reads the interpolated value.
    Timer {
        interval: 500
        running: root.open && root.playing && root.hasPlayer
        repeat: true
        onTriggered: if (root.player) root.player.positionChanged()
    }

    // ---- spectrum feed (cava, only while the widget is on screen) --------
    Process {
        id: cavaProc
        running: root.open
        command: ["sh", "-c", "exec cava -p \"$HOME/.config/quickshell/scripts/cava-spectrum.conf\""]
        stdout: SplitParser {
            onRead: data => {
                const parts = data.split(";");
                const out = [];
                for (let i = 0; i < 16; i++) out.push(Math.min(100, parseInt(parts[i], 10) || 0));
                root.spectrumLevels = out;
            }
        }
        onExited: cavaRestart.restart()
    }
    Timer {
        id: cavaRestart
        interval: 2000
        onTriggered: if (root.open) cavaProc.running = true
    }

    function fmtTime(s) {
        if (!s || s < 0 || !isFinite(s)) return "0:00";
        s = Math.floor(s);
        const m = Math.floor(s / 60);
        const ss = s % 60;
        return m + ":" + (ss < 10 ? "0" : "") + ss;
    }

    // ---- a transport button: crisp Canvas-drawn icon, themed frame -------
    component MediaButton: Rectangle {
        id: btn
        property string kind: "play"   // prev | next | play | pause | shuffle | repeat
        property bool active: true
        property bool toggled: false   // lit accent even without hover (repeat/shuffle on)
        property int variant: 0        // repeat: 0 = plain loop, 1 = repeat-one (adds "1")
        signal clicked()

        width: 26
        height: 26
        color: (btn.toggled || (mba.containsMouse && active)) ? Theme.bgAlt : "transparent"
        border.width: 1
        border.color: !active ? Theme.border : ((btn.toggled || mba.containsMouse) ? Theme.accent : Theme.border)
        opacity: active ? 1 : 0.4

        onKindChanged: icon.requestPaint()
        onVariantChanged: icon.requestPaint()

        Canvas {
            id: icon
            anchors.centerIn: parent
            width: 12
            height: 12
            property color col: (btn.toggled || (mba.containsMouse && btn.active)) ? Theme.accent : Theme.text
            onColChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d");
                ctx.reset();
                ctx.clearRect(0, 0, width, height);
                ctx.fillStyle = col;
                ctx.strokeStyle = col;
                const w = width, h = height;
                if (btn.kind === "play") {
                    ctx.beginPath(); ctx.moveTo(1, 0); ctx.lineTo(w - 1, h / 2); ctx.lineTo(1, h); ctx.closePath(); ctx.fill();
                } else if (btn.kind === "pause") {
                    ctx.fillRect(1, 0, 3, h); ctx.fillRect(w - 4, 0, 3, h);
                } else if (btn.kind === "next") {
                    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(w - 3, h / 2); ctx.lineTo(0, h); ctx.closePath(); ctx.fill();
                    ctx.fillRect(w - 2, 0, 2, h);
                } else if (btn.kind === "prev") {
                    ctx.fillRect(0, 0, 2, h);
                    ctx.beginPath(); ctx.moveTo(w, 0); ctx.lineTo(3, h / 2); ctx.lineTo(w, h); ctx.closePath(); ctx.fill();
                } else if (btn.kind === "shuffle") {
                    // two crossing paths with arrowheads on the right
                    ctx.lineWidth = 1.4; ctx.lineCap = "round";
                    ctx.beginPath(); ctx.moveTo(1, 2.5); ctx.lineTo(w - 3, h - 2.5); ctx.stroke();
                    ctx.beginPath(); ctx.moveTo(1, h - 2.5); ctx.lineTo(w - 3, 2.5); ctx.stroke();
                    ctx.beginPath(); ctx.moveTo(w, h - 2.5); ctx.lineTo(w - 4, h - 4.5); ctx.lineTo(w - 4, h - 0.5); ctx.closePath(); ctx.fill();
                    ctx.beginPath(); ctx.moveTo(w, 2.5); ctx.lineTo(w - 4, 0.5); ctx.lineTo(w - 4, 4.5); ctx.closePath(); ctx.fill();
                } else if (btn.kind === "repeat") {
                    // rounded loop: top & bottom bars joined by short verticals,
                    // arrowheads pointing down (right) and up (left)
                    ctx.lineWidth = 1.4; ctx.lineCap = "round";
                    ctx.beginPath();
                    ctx.moveTo(w * 0.2, h * 0.28); ctx.lineTo(w * 0.72, h * 0.28);
                    ctx.lineTo(w * 0.72, h * 0.5); ctx.stroke();
                    ctx.beginPath();
                    ctx.moveTo(w * 0.72 - 2, h * 0.5); ctx.lineTo(w * 0.72 + 2, h * 0.5);
                    ctx.lineTo(w * 0.72, h * 0.5 + 2.5); ctx.closePath(); ctx.fill();
                    ctx.beginPath();
                    ctx.moveTo(w * 0.8, h * 0.72); ctx.lineTo(w * 0.28, h * 0.72);
                    ctx.lineTo(w * 0.28, h * 0.5); ctx.stroke();
                    ctx.beginPath();
                    ctx.moveTo(w * 0.28 - 2, h * 0.5); ctx.lineTo(w * 0.28 + 2, h * 0.5);
                    ctx.lineTo(w * 0.28, h * 0.5 - 2.5); ctx.closePath(); ctx.fill();
                    if (btn.variant === 1) {   // repeat-one: a small "1" in the middle
                        ctx.fillRect(w / 2 - 0.7, h * 0.42, 1.4, h * 0.18);
                        ctx.fillRect(w / 2 - 1.6, h * 0.44, 0.9, 1);
                    }
                }
            }
        }

        MouseArea {
            id: mba
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: btn.active ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: if (btn.active) btn.clicked()
        }
    }

    // ---- spectrum: 16 vertical bars, driven by spectrumLevels ------------
    component Spectrum: Item {
        id: spec
        readonly property int nbars: 16
        Row {
            anchors.fill: parent
            spacing: 2
            Repeater {
                model: spec.nbars
                Item {
                    required property int index
                    width: (spec.width - (spec.nbars - 1) * 2) / spec.nbars
                    height: spec.height
                    Rectangle {
                        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                        height: Math.max(1, spec.height * (root.spectrumLevels[index] || 0) / 100)
                        color: Theme.accent
                        Behavior on height { NumberAnimation { duration: 60 } }
                    }
                }
            }
        }
    }

    Column {
        id: content
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 6

        // header: the source app, or a generic label when nothing's playing
        PixelText {
            width: 276
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: (root.hasPlayer && root.player.identity) ? root.player.identity : "media"
            color: Theme.accent
        }

        // track title / artist
        PixelText {
            width: 276
            elide: Text.ElideRight
            text: root.hasPlayer ? (root.player.trackTitle || "—") : "nothing playing"
            color: Theme.text
        }
        PixelText {
            width: 276
            elide: Text.ElideRight
            visible: root.hasPlayer && (root.player.trackArtist || "") !== ""
            text: root.hasPlayer ? root.player.trackArtist : ""
            color: Theme.textDim
        }

        // artwork + spectrum
        Row {
            width: 276
            height: 60
            spacing: 8

            Item {
                width: 60
                height: 60
                Rectangle {
                    anchors.fill: parent
                    color: Theme.bgAlt
                    border.width: 1
                    border.color: Theme.border
                }
                Image {
                    id: art
                    anchors { fill: parent; margins: 1 }
                    source: root.hasPlayer ? (root.player.trackArtUrl || "") : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    cache: true
                    clip: true
                    sourceSize.width: 120
                    sourceSize.height: 120
                    visible: status === Image.Ready
                }
                // CP437 note glyph placeholder when there's no cover art
                PixelText {
                    anchors.centerIn: parent
                    visible: !art.visible
                    text: "♫"
                    color: Theme.textDim
                }
            }

            Spectrum {
                width: 276 - 60 - 8
                height: 60
            }
        }

        // seekbar: elapsed | draggable track | total
        Row {
            width: 276
            height: 14
            spacing: 6

            PixelText {
                width: 36
                anchors.verticalCenter: parent.verticalCenter
                horizontalAlignment: Text.AlignLeft
                text: root.fmtTime(root.hasPlayer ? root.player.position : 0)
                color: Theme.textDim
            }

            Item {
                id: seek
                width: 276 - 36 - 36 - 12
                height: parent.height
                anchors.verticalCenter: parent.verticalCenter

                readonly property bool seekable: root.hasPlayer && root.player.canSeek
                    && root.player.lengthSupported && root.player.length > 0
                readonly property real frac: seekable
                    ? Math.max(0, Math.min(1, root.player.position / root.player.length)) : 0

                Rectangle { // track
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: 6
                    color: Theme.bgAlt
                    border.width: 1
                    border.color: Theme.border
                    Rectangle { // fill
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 1 }
                        width: Math.round((parent.width - 2) * seek.frac)
                        color: Theme.accent
                    }
                }

                function seekTo(x) {
                    if (!seek.seekable) return;
                    root.player.position = Math.max(0, Math.min(1, x / width)) * root.player.length;
                }
                MouseArea {
                    anchors { fill: parent; topMargin: -4; bottomMargin: -4 }
                    enabled: seek.seekable
                    cursorShape: seek.seekable ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onPressed: (mouse) => seek.seekTo(mouse.x)
                    onPositionChanged: (mouse) => { if (pressed) seek.seekTo(mouse.x); }
                }
            }

            PixelText {
                width: 36
                anchors.verticalCenter: parent.verticalCenter
                horizontalAlignment: Text.AlignRight
                text: root.fmtTime(root.hasPlayer && root.player.lengthSupported ? root.player.length : 0)
                color: Theme.textDim
            }
        }

        // transport controls
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 12
            topPadding: 2

            MediaButton {
                kind: "shuffle"
                active: root.hasPlayer && root.player.shuffleSupported
                toggled: root.hasPlayer && root.player.shuffle
                onClicked: root.player.shuffle = !root.player.shuffle
            }
            MediaButton {
                kind: "prev"
                active: root.hasPlayer && root.player.canGoPrevious
                onClicked: root.player.previous()
            }
            MediaButton {
                kind: root.playing ? "pause" : "play"
                active: root.hasPlayer && (root.player.canPlay || root.player.canPause)
                onClicked: root.player.togglePlaying()
            }
            MediaButton {
                kind: "next"
                active: root.hasPlayer && root.player.canGoNext
                onClicked: root.player.next()
            }
            MediaButton {
                kind: "repeat"
                active: root.canRepeat
                toggled: root.repeatMode !== 0
                variant: root.repeatMode === 1 ? 1 : 0   // "1" glyph for repeat-track
                onClicked: root.cycleRepeat()
            }
        }
    }
}

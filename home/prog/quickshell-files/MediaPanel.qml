import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Mpris

// Media player popup (SlidePopup: tiled bottom-right desktop widget, hover-kept
// / pinnable), sitting between the disk and clock widgets in the fanned row.
// Everything interactive comes from MPRIS (Quickshell.Services.Mpris): the
// active player drives the title/artist/art, the transport buttons, and the
// draggable seekbar. The spectrum below the artwork is a second cava instance
// (scripts/cava-spectrum.conf) — same plumbing as the bar's VU meter
// (VuMeter.qml), reacting to whatever's on the output sink regardless of which
// app is the MPRIS source. cava's bucket count is config-only, so the bar count
// (mediaSpectrumBars) is patched into a runtime copy of the conf and cava is
// bounced whenever it changes — otherwise raising it past the file's baked
// count leaves the extra bars flat (only the first N buckets ever get data).
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
        if (SettingsStore.d.mediaPreferPlaying)
            for (let i = 0; i < ps.length; i++) if (ps[i].isPlaying) return ps[i];
        for (let i = 0; i < ps.length; i++) if (ps[i].canControl) return ps[i];
        return ps[0];
    }
    readonly property bool hasPlayer: player !== null
    readonly property bool playing: hasPlayer && player.isPlaying
    property var spectrumLevels: []
    // Per-bar peak-hold state, advanced once per cava frame (see the feed's
    // SplitParser). Classic analyser behaviour: instant attack, a brief hold at
    // the top, then an accelerating fall — the acceleration is what makes a peak
    // read as *falling* rather than fading, so keep the velocity term.
    property var spectrumPeaks: []
    property var spectrumPeakVel: []
    property var spectrumPeakHold: []
    // Frames, at cava's 60fps: ~0.33s of hold before the drop starts.
    readonly property int peakHoldFrames: 20
    // Units of the 0-100 scale added to the fall speed each frame.
    readonly property real peakGravity: 0.055

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
        // see VuMeter.qml: prepend ~/.nix-profile/bin so the session's bare PATH
        // can find the nix-installed cava, else the spectrum never spawns (and
        // /run/current-system/sw/bin for pw-dump, used below). cava has no CLI
        // for the bar count or the input source, so both get patched into a
        // runtime copy of the conf and cava is run against that.
        //
        // The source patch taps `easyeffects_sink.monitor` — the audio as apps
        // wrote it, BEFORE the EasyEffects chain processes it (see the conf's
        // [input] comment). Guarded on the sink actually existing: EasyEffects
        // is started from hyprland.lua alongside the session, so a cold start
        // can briefly race it, and pointing cava at a missing source would fail
        // straight into the 2s onExited retry loop. Absent -> leave `auto`,
        // i.e. fall back to the post-chain hardware monitor.
        command: ["sh", "-c",
            "export PATH=\"$HOME/.nix-profile/bin:/run/current-system/sw/bin:$PATH\"; "
            + "src=\"$HOME/.config/quickshell/scripts/cava-spectrum.conf\"; "
            + "cfg=\"${XDG_RUNTIME_DIR:-/tmp}/qs-cava-spectrum.conf\"; "
            + "sed \"s/^bars *=.*/bars = " + SettingsStore.d.mediaSpectrumBars + "/\" \"$src\" > \"$cfg\" && "
            + "{ pw-dump 2>/dev/null | grep -q '\"easyeffects_sink\"' && "
            + "sed -i \"s/^source *=.*/source = easyeffects_sink.monitor/\" \"$cfg\"; } ; "
            + "exec cava -p \"$cfg\""]
        stdout: SplitParser {
            onRead: data => {
                const n = SettingsStore.d.mediaSpectrumBars;
                const parts = data.split(";");
                const out = [];
                for (let i = 0; i < n; i++) out.push(Math.min(100, parseInt(parts[i], 10) || 0));
                root.spectrumLevels = out;

                // Advance the peak markers on the same clock as the bars. The
                // arrays are re-seeded whenever the bar count changes under us
                // (cava respawns with a new bucket count), so a length mismatch
                // is expected, not an error.
                const pk  = root.spectrumPeaks.length    === n ? root.spectrumPeaks.slice()    : out.slice();
                const vel = root.spectrumPeakVel.length  === n ? root.spectrumPeakVel.slice()  : new Array(n).fill(0);
                const hld = root.spectrumPeakHold.length === n ? root.spectrumPeakHold.slice() : new Array(n).fill(0);
                for (let i = 0; i < n; i++) {
                    if (out[i] >= pk[i]) {          // new peak: snap up, reset the fall
                        pk[i] = out[i]; vel[i] = 0; hld[i] = root.peakHoldFrames;
                    } else if (hld[i] > 0) {        // sitting at the top
                        hld[i]--;
                    } else {                        // falling, faster each frame
                        vel[i] += root.peakGravity;
                        pk[i] = Math.max(out[i], pk[i] - vel[i]);
                    }
                }
                root.spectrumPeaks = pk;
                root.spectrumPeakVel = vel;
                root.spectrumPeakHold = hld;
            }
        }
        // A bar-count change stops cava so it respawns with the new bucket count
        // (cavaBouncing path); any other exit is a crash — back off and retry.
        onExited: {
            if (root.cavaBouncing) {
                root.cavaBouncing = false;
                // re-arm the open-bound lifecycle: evaluates true (we're open),
                // so cava restarts now with the patched conf, and a later close
                // still stops it (the plain `= true` below would break that).
                cavaProc.running = Qt.binding(() => root.open);
            } else {
                cavaRestart.restart();
            }
        }
    }
    Timer {
        id: cavaRestart
        interval: 2000
        onTriggered: if (root.open) cavaProc.running = Qt.binding(() => root.open)
    }

    // cava's bucket count is fixed at spawn, so restart it when mediaSpectrumBars
    // changes. Debounced: a slider drag fires many changes; bounce once it settles.
    property bool cavaBouncing: false
    Timer {
        id: cavaBounce
        interval: 250
        onTriggered: if (root.open && cavaProc.running) { root.cavaBouncing = true; cavaProc.running = false; }
    }
    Connections {
        target: SettingsStore.d
        function onMediaSpectrumBarsChanged() { if (root.open) cavaBounce.restart(); }
    }

    function fmtTime(s) {
        if (!s || s < 0 || !isFinite(s)) return "0:00";
        s = Math.floor(s);
        const m = Math.floor(s / 60);
        const ss = s % 60;
        return m + ":" + (ss < 10 ? "0" : "") + ss;
    }

    // ---- a transport button: pixel-font glyph, themed frame -------------
    component MediaButton: Rectangle {
        id: btn
        property string kind: "play"   // prev | next | play | pause | shuffle | repeat
        property bool active: true
        property bool toggled: false   // lit accent even without hover (repeat/shuffle on)
        signal clicked()

        // glyph per kind: skip << >>, play/pause > ||, shuffle *, repeat o
        readonly property string glyph: kind === "prev" ? "<<"
            : kind === "next" ? ">>"
            : kind === "pause" ? "||"
            : kind === "shuffle" ? "*"
            : kind === "repeat" ? "o"
            : ">"   // play

        width: 26
        height: 26
        // toggled (repeat/shuffle on) inverts like the titlebar roll button:
        // accent fill + background-colored glyph. Hover is the lighter bgAlt tint.
        color: btn.toggled ? Theme.accent : ((mba.containsMouse && active) ? Theme.bgAlt : "transparent")
        border.width: 1
        border.color: !active ? Theme.border : ((btn.toggled || mba.containsMouse) ? Theme.accent : Theme.border)
        opacity: active ? 1 : 0.4

        PixelText {
            anchors.centerIn: parent
            text: btn.glyph
            color: btn.toggled ? Theme.bg : ((mba.containsMouse && btn.active) ? Theme.accent : Theme.text)
        }

        MouseArea {
            id: mba
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: btn.active ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: if (btn.active) btn.clicked()
        }
    }

    // ---- spectrum: mediaSpectrumBars vertical bars, driven by spectrumLevels --
    // cava's 0-100 is roughly linear in amplitude, and real music spends almost
    // all its time in the bottom third of that (measured medians 15, p90 49), so
    // a straight height mapping draws stubs that twitch by a pixel and reads as
    // "unresponsive". Curve it: gamma 0.55 pulls that same data up to med ~35 /
    // p90 ~68 without touching the top end (100 still maps to 100), so the bars
    // use the widget's full height and the same transient moves visibly further.
    // Do this here rather than raising cava's sensitivity — autosens owns that,
    // and fighting it is what forces per-track fiddling.
    component Spectrum: Item {
        id: spec
        readonly property int nbars: SettingsStore.d.mediaSpectrumBars
        readonly property real gamma: 0.55
        // Bars are gapless, so they can't be laid out by a Row with spacing 0:
        // at 32 buckets the per-bar width is fractional, and rounding each one
        // independently leaves subpixel seams between them. Position from the
        // shared edge instead — bar i spans round(w*i/n)..round(w*(i+1)/n), so
        // one bar's right edge IS the next one's left edge and the row stays
        // exactly `width` wide however the division falls.
        Repeater {
            model: spec.nbars
            Item {
                required property int index
                readonly property int x0: Math.round(spec.width * index / spec.nbars)
                x: x0
                width: Math.max(1, Math.round(spec.width * (index + 1) / spec.nbars) - x0)
                height: spec.height

                // level
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: Math.max(1, spec.height
                        * Math.pow(Math.max(0, root.spectrumLevels[index] || 0) / 100, spec.gamma))
                    color: Theme.accent
                    // cava already smooths (noise_reduction) and feeds 60fps,
                    // so this is a second low-pass on top. Keep it just long
                    // enough to absorb a dropped frame, not to re-add lag.
                    Behavior on height { NumberAnimation { duration: 25 } }
                }

                // peak marker — same gamma as the bar so it lines up with the
                // bar top on a fresh hit. Deliberately NOT animated: the fall
                // is already interpolated frame-by-frame by the gravity model,
                // and a Behavior here would drag the marker behind the peak it
                // is supposed to be pinning.
                //
                // Theme.textDim, matching the artist line above. It reads 3.8:1
                // against the background — where a marker spends nearly all its
                // time, since it sits above its own bar by definition — and
                // 1.9:1 against accent for the moments it rides right on a bar
                // top, which is actually better separation there than the
                // brighter Theme.text it replaces (1.4:1).
                Rectangle {
                    anchors { left: parent.left; right: parent.right }
                    height: 1
                    y: Math.min(spec.height - height, Math.max(0, spec.height - height - spec.height
                        * Math.pow(Math.max(0, root.spectrumPeaks[index] || 0) / 100, spec.gamma)))
                    color: Theme.textDim
                    visible: (root.spectrumPeaks[index] || 0) > 0
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
                onClicked: root.cycleRepeat()
            }
        }
    }
}

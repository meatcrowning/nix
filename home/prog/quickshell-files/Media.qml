pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.Mpris

// The media widget's data: which MPRIS player is "the" player, what it is
// playing, the cava spectrum feed, and repeat/shuffle. Hoisted out of
// MediaPanel.qml for the same reason as Disks.qml — the widget now draws in two
// places (the hover popup and a dock tile) and there must only ever be one cava,
// one snapshot, and one answer for `qs ipc call state carried`.
//
// `watch(obj, on)` is the on-screen registry; cava runs only while something is
// watching, which is what the popup's `open` used to mean.
Singleton {
    id: root

    property var _watchers: []
    readonly property bool live: _watchers.length > 0
    function watch(obj, on) {
        const i = _watchers.indexOf(obj);
        if (on === (i >= 0)) return;
        let w = _watchers.slice();
        if (on) w.push(obj); else w.splice(i, 1);
        _watchers = w;
    }


    // ---- active player selection ----------------------------------------
    // Prefer a source that's actually playing; else the first controllable one;
    // else whatever exists. Recomputes as players come and go.
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

    // ---- reload continuity (see shell.qml's `persist` block) --------------
    // Two separate things reset on a reload and both are visible:
    //
    //   * the spectrum. cava is bound to `live`, so a reload kills it and the
    //     new instance respawns it — every bar snaps to the floor and climbs
    //     back ~200ms later. Carrying the last frame across means the bars are
    //     simply where they were, and the live feed takes back over mid-stride.
    //   * the track text. MPRIS re-resolves over D-Bus, which is a round trip, so
    //     for the first frames there is no player at all: the header falls back
    //     to "media", the title to "nothing playing", and the artist line — which
    //     is `visible`-gated — disappears, shortening the card by a row and
    //     walking its bottom-anchored top edge down and back. `_settling` keeps
    //     the carried snapshot on screen for that window only, so a player that
    //     genuinely went away still reads as "nothing playing" a moment later
    //     rather than showing a ghost track forever.
    property var snap: null       // {id,title,artist,art,pos,len,play} or null
    property bool _settling: false
    Timer { id: settleTimer; interval: 1500; onTriggered: root._settling = false }

    readonly property bool useSnap: !hasPlayer && _settling && snap !== null
    readonly property string dispIdentity: hasPlayer ? (player.identity || "media")
        : useSnap ? (snap.id || "media") : "media"
    // EMPTY when there is nothing to say, rather than a placeholder. The widget
    // reserves the line's height either way (MediaContent's top row is a fixed
    // height), so a blank line is stable where "nothing playing" was just noise
    // — and the em dash it used to fall back to was worse than noise: More
    // Perfect DOS VGA has no U+2014, so the line fell back to another font for
    // that glyph, lost ~5px of ascent, and clipped.
    readonly property string dispTitle: Glyphs.px(hasPlayer ? (player.trackTitle || "")
        : useSnap ? (snap.title || "") : "")
    readonly property string dispArtist: Glyphs.px(hasPlayer ? (player.trackArtist || "")
        : useSnap ? (snap.artist || "") : "")
    readonly property string dispArt: hasPlayer ? (player.trackArtUrl || "")
        : useSnap ? (snap.art || "") : ""
    readonly property real dispPos: hasPlayer ? player.position : useSnap ? snap.pos : 0
    readonly property real dispLen: hasPlayer
        ? (player.lengthSupported ? player.length : 0) : useSnap ? snap.len : 0

    // ---- the play queue, straight from the player -------------------------
    // MPRIS says what is playing and nothing about what is NEXT (its TrackList
    // interface is optional, and Quickshell implements no client for it), so
    // the player app serves its queue over a unix socket instead — one JSON
    // line pushed on connect and on every queue or index change, and `GOTO n`
    // back the other way. See apps/player/main.py's start_queue_server.
    //
    // The parsed array is derived from the raw LINE, which is what gets carried
    // across a reload: PersistentProperties can only move strings between the
    // two QML engines a reload alternates between, and a `var` holding an array
    // arrives undefined on every other one.
    property string queueJson: ""
    // The rows are made display-safe HERE, not in the delegate: the drawer
    // re-creates its visible rows on every scroll, and this runs once per queue
    // change instead. A row that needs no substitution is passed through by
    // reference — no copy, no new array — so a queue of ASCII titles costs one
    // regex test each and nothing else. (The raw LINE cannot be tested as a
    // shortcut: the player's json.dumps is ensure_ascii, so a U+2019 arrives on
    // the wire as the six ASCII characters backslash-u-2-0-1-9.)
    readonly property var queue: {
        if (queueJson === "") return [];
        try {
            const t = JSON.parse(queueJson).tracks || [];
            let out = null;
            for (let i = 0; i < t.length; i++) {
                const r = t[i];
                const ti = Glyphs.px(r.title), ar = Glyphs.px(r.artist);
                if (ti === r.title && ar === r.artist) { if (out) out.push(r); continue; }
                if (!out) out = t.slice(0, i);
                out.push({ title: ti, artist: ar, dur: r.dur });
            }
            return out || t;
        } catch (e) { return []; }
    }
    readonly property int queueIndex: {
        if (queueJson === "") return -1;
        try { const i = JSON.parse(queueJson).index; return i === undefined ? -1 : i; }
        catch (e) { return -1; }
    }
    readonly property bool queueAvailable: queueSock.connected && queue.length > 0

    // Whether the drawer is open. In SettingsStore, not a local property: the
    // dock grid reads it to decide how many rows the player and the forecast
    // get, and a drawer the user opened should still be open after the reload a
    // wallpaper change causes.
    readonly property bool queueOpen: SettingsStore.d.mediaQueueOpen
    function setQueueOpen(v) {
        SettingsStore.d.mediaQueueOpen = !!v;
        SettingsStore.save();
    }
    function playIndex(i) {
        if (i < 0 || i >= queue.length) return;
        queueSock.write("GOTO " + i + "\n");
        queueSock.flush();
    }

    Socket {
        id: queueSock
        path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/player-queue.sock"
        parser: SplitParser {
            onRead: line => { if (line.trim() !== "") root.queueJson = line; }
        }
    }

    // Only attempt while the player actually has a window open. Quickshell logs
    // a warning on every failed connect, and `qs log` is cumulative — a blind
    // retry timer fills it with ServerNotFoundError all day on a machine where
    // nobody is playing music. The window list is the cheapest true answer
    // available here: it needs no poll of its own, and unlike "is there an MPRIS
    // player" it is still right on a host where mpris_server is missing.
    readonly property bool playerUp: {
        const t = ToplevelManager.toplevels;
        const v = t ? t.values : null;
        if (!v) return false;
        for (let i = 0; i < v.length; i++)
            if ((v[i].appId || "") === "player") return true;
        return false;
    }
    // Re-asserting `connected` is a no-op while the socket is up, so this is the
    // whole reconnect story — no state machine, nothing to get stuck in. It
    // fires straight away when the player appears, and every 5s after that in
    // case the window mapped before the server finished binding.
    Timer {
        interval: 5000
        repeat: true
        running: root.playerUp
        triggeredOnStart: true
        onTriggered: {
            if (!queueSock.connected)
                queueSock.connected = true;
        }
    }
    onPlayerUpChanged: if (!playerUp) { queueSock.connected = false; root.queueJson = ""; }

    function stateJson() {
        return JSON.stringify({
            qj: queueJson,
            lv: spectrumLevels, pk: spectrumPeaks,
            pv: spectrumPeakVel, ph: spectrumPeakHold,
            np: hasPlayer ? {
                id: player.identity, title: player.trackTitle,
                artist: player.trackArtist, art: player.trackArtUrl,
                pos: player.position,
                len: player.lengthSupported ? player.length : 0,
                play: player.isPlaying,
            // `useSnap`, not a bare `snap`: the snapshot exists to cover the
            // ~1.5s MPRIS round trip of ONE reload, and re-emitting it
            // unconditionally made it immortal. Once a player goes away the
            // last snapshot was carried into every subsequent reload forever,
            // each one re-arming `_settling` — so the widget showed a ghost
            // track for 1.5s on every wallpaper or theme change (the exact
            // thing the `_settling` comment above says it prevents), and
            // MediaContent's cover Image re-opened a dead artUrl each time.
            // Chromium's MPRIS artUrl is a `/tmp/.org.chromium.Chromium.XXXXXX`
            // temp file it deletes on exit, so `qs log` collected two
            // `Cannot open: file:///tmp/.org.chromium.Chromium.*` per reload
            // (one per live copy of the widget — the popup and the dock tile)
            // for the rest of the session. `useSnap` is already
            // `!hasPlayer && _settling && snap !== null`, so back-to-back
            // reloads still chain the snapshot across; only a settled tree with
            // no player carries nothing, which is what it is showing anyway.
            } : (useSnap ? snap : null),
        });
    }
    function restoreState(s) {
        if (!s) return;
        try {
            const d = JSON.parse(s);
            root.queueJson        = d.qj || "";
            root.spectrumLevels   = d.lv || [];
            root.spectrumPeaks    = d.pk || [];
            root.spectrumPeakVel  = d.pv || [];
            root.spectrumPeakHold = d.ph || [];
            root.snap = d.np || null;
            if (root.snap) { root._settling = true; settleTimer.restart(); }
        } catch (e) {}
    }

    property var spectrumLevels: []
    // Per-bar peak-hold state, advanced once per cava frame. Classic analyser
    // behaviour: instant attack, a brief hold at the top, then an accelerating
    // fall — the acceleration is what makes a peak read as *falling* rather than
    // fading, so keep the velocity term.
    property var spectrumPeaks: []
    property var spectrumPeakVel: []
    property var spectrumPeakHold: []
    readonly property int peakHoldFrames: 20      // frames at cava's 60fps ≈ 0.33s
    readonly property real peakGravity: 0.055     // 0-100 units added to the fall per frame

    // ---- repeat / shuffle ------------------------------------------------
    // Repeat cycles None -> Track -> Playlist natively when the player exposes
    // LoopStatus. When it doesn't (localLoop path), we fake repeat-track by
    // seeking back to 0 just before the current track ends — the one loop mode we
    // can honestly implement without owning the player's queue.
    // Persisted: on a player with no LoopStatus this is the ONLY record that
    // repeat is on, and losing it on a reload silently stopped repeating.
    readonly property int localLoop: SettingsStore.d.mediaLocalLoop

    readonly property int repeatMode: {
        if (!hasPlayer) return 0;
        if (player.loopSupported) {
            switch (player.loopState) {
                case MprisLoopState.Track: return 1;
                case MprisLoopState.Playlist: return 2;
                default: return 0;
            }
        }
        return localLoop;
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
            // save(), or the reader poll reverts it within ~350ms (see
            // SettingsStore) and it never reaches disk
            SettingsStore.d.mediaLocalLoop = localLoop === 0 ? 1 : 0;
            SettingsStore.save();
        }
    }

    // Local repeat-track enforcement: while active, watch position and jump back
    // to the start just before the track would end (and hand off to the next).
    // NOT gated on `live` — repeat is a property of playback, not of the widget
    // being on screen.
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

    // MPRIS position isn't pushed live — re-emit positionChanged on a timer while
    // playing so the seekbar binding re-reads the interpolated value.
    Timer {
        interval: 500
        running: root.live && root.playing && root.hasPlayer
        repeat: true
        onTriggered: if (root.player) root.player.positionChanged()
    }

    function fmtTime(s) {
        if (!s || s < 0 || !isFinite(s)) return "0:00";
        s = Math.floor(s);
        const m = Math.floor(s / 60);
        const ss = s % 60;
        return m + ":" + (ss < 10 ? "0" : "") + ss;
    }

    // ---- spectrum feed (cava, only while the widget is on screen) --------
    Process {
        id: cavaProc
        running: root.live
        // see VuMeter.qml: prepend ~/.nix-profile/bin so the session's bare PATH
        // can find the nix-installed cava, else the spectrum never spawns (and
        // /run/current-system/sw/bin for pw-dump, used below). cava has no CLI
        // for the bar count or the input source, so both get patched into a
        // runtime copy of the conf and cava is run against that.
        //
        // The source patch taps `easyeffects_sink.monitor` — the audio as apps
        // wrote it, BEFORE the EasyEffects chain processes it (see the conf's
        // [input] comment). Guarded on the sink actually existing: EasyEffects is
        // started from hyprland.lua alongside the session, so a cold start can
        // briefly race it, and pointing cava at a missing source would fail
        // straight into the 2s onExited retry loop. Absent -> leave `auto`, i.e.
        // fall back to the post-chain hardware monitor.
        command: ["sh", "-c",
            // cava reaches outside Fedora's PATH on book; NixPath.qml explains.
            NixPath.sh
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
                // (cava respawns with a new bucket count), so a length mismatch is
                // expected, not an error.
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
                // re-arm the live-bound lifecycle: evaluates true (someone is
                // watching), so cava restarts now with the patched conf, and a
                // later close still stops it (a plain `= true` would break that).
                cavaProc.running = Qt.binding(() => root.live);
            } else {
                cavaRestart.restart();
            }
        }
    }
    Timer {
        id: cavaRestart
        interval: 2000
        onTriggered: if (root.live) cavaProc.running = Qt.binding(() => root.live)
    }

    // cava's bucket count is fixed at spawn, so restart it when
    // mediaSpectrumBars changes. Debounced: a slider drag fires many changes;
    // bounce once it settles.
    property bool cavaBouncing: false
    Timer {
        id: cavaBounce
        interval: 250
        onTriggered: if (root.live && cavaProc.running) { root.cavaBouncing = true; cavaProc.running = false; }
    }
    Connections {
        target: SettingsStore.d
        function onMediaSpectrumBarsChanged() { if (root.live) cavaBounce.restart(); }
    }
}

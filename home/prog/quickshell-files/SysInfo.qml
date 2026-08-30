pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

// Polls system state on a timer and exposes it to the panel widgets.
Singleton {
    id: root

    property real   rxSpeed: 0          // bytes/s
    property real   txSpeed: 0
    property int    diskFreeKb: 0
    property int    diskUsePct: 0
    property int    volume: -1          // 0-100, or -1 when unavailable
    property bool   muted: false
    property int    cpuUsage: -1        // 0-100, or -1 until the second poll
    property int    cpuTemp: -1         // Celsius, k10temp's Tctl (or book's Battery Hotspot fallback), or -1
    property int    gpuUsage: -1        // 0-100, nvidia-smi utilization, or -1 (no nvidia-smi, e.g. book)
    property int    gpuTemp: -1         // Celsius, nvidia-smi temperature, or -1 (no nvidia-smi, e.g. book)
    property int    batteryPct: -1      // 0-100, or -1 when no system battery was found (desktop)
    property bool   batteryCharging: false
    // The sysfs `status` as a code, so nothing here string-matches a kernel
    // label: 0 none, 1 discharging, 2 charging, 3 full, 4 not charging (on AC
    // and idle), 5 present but unknown. See sysinfo.sh. "on AC" and
    // "discharging" are deliberately distinct — the same wattage means
    // opposite things in each, and a battery card that could not tell them
    // apart would read as a machine draining while it is plugged in.
    property int    batteryStatus: 0

    // The battery card's secondary reading: the state IN WORDS, plus how fast
    // the charge is moving. Lives here rather than in the card because a
    // *Content component draws and nothing else.
    //
    // Discharging gets no word — it is the unremarkable state, and the word
    // would only crowd out the number — so every word that IS there means the
    // machine is plugged in. Which way the line is about to go is the whole
    // point of the card, and the sign of a wattage is too quiet to carry it:
    // the card ALSO prefixes its percentage with "+" while charging, on the
    // line that is never dropped for want of room (see MetricCard.sub, which
    // is). Two markers rather than one because the loud one has to survive a
    // narrow panel.
    //
    // ASCII on purpose: More Perfect DOS VGA has no minus sign (U+2212) and a
    // PixelText that falls back to another font for one glyph loses ~5px of
    // ascent and clips the whole line.
    readonly property string batteryLabel: {
        if (batteryPct < 0) return "";
        // "full" is a terminal state, not a rate: pairing it with a wattage
        // reads as a battery still doing something.
        if (batteryStatus === 3) return "full";
        const word = batteryStatus === 2 ? "chg" : batteryStatus === 4 ? "ac" : "";
        const watts = powerW >= 0 ? powerW.toFixed(1) + "W" : "";
        if (word && watts) return word + " " + watts;
        // Nothing reports watts: the word alone, and "bat" where there'd be no
        // word at all, so the slot is never blank while a battery is present.
        return word || watts || "bat";
    }

    // ---- the dock task manager's extra sensors ---------------------------
    // MemAvailable, not MemFree: the kernel's estimate of what a new allocation
    // could actually get (free plus reclaimable cache). MemFree alone reads as
    // "almost none" on any machine that has been up a while, which is simply a
    // wrong thing to show a user.
    property int    memTotalKb: 0
    property int    memAvailKb: 0
    readonly property int memUsedKb: Math.max(0, memTotalKb - memAvailKb)
    readonly property int memUsage: memTotalKb > 0
        ? Math.round(100 * memUsedKb / memTotalKb) : -1
    property int    swapTotalKb: 0
    property int    swapFreeKb: 0
    readonly property int swapUsage: swapTotalKb > 0
        ? Math.round(100 * (swapTotalKb - swapFreeKb) / swapTotalKb) : -1
    property real   load1: -1
    property int    uptimeSec: 0
    // nvidia-smi extras, all -1 where the host has no nvidia-smi (book).
    property int    gpuFanPct: -1
    property real   gpuPowerW: -1
    property int    gpuMemUsedMb: -1
    property int    gpuMemTotalMb: -1
    readonly property int gpuMemUsage: gpuMemTotalMb > 0
        ? Math.round(100 * gpuMemUsedMb / gpuMemTotalMb) : -1
    // EVERY fan on the machine, one entry each: { name, rpm, pct }. The chassis
    // and cooler fans come from hwmon (`fanDetail` in sysinfo.sh, which is where
    // the discovery and the pwm-duty arithmetic live); the GPU fan is appended
    // from the nvidia-smi reading above, because it is a fan and "the fastest
    // fan going" is a wrong answer if the loudest one in the box is left out of
    // the search. `rpm` is -1 for the GPU (nvidia-smi reports no tachometer) and
    // `pct` is -1 for any fan whose chip exposes no pwm.
    //
    // EMPTY where nothing reports a fan at all, and consumers hide rather than
    // draw a permanent zero. That was `top`'s state until the nct6683 driver was
    // loaded for the board's EC, and it is book's permanently — that machine is
    // fanless.
    property var fans: []
    // Per-fan history of `pct`, keyed by NAME rather than by index: a fan
    // appearing or disappearing must not slide every other fan's history onto
    // the wrong line. Trimmed to chartLen like the other ring buffers, and
    // pruned of names that stopped reporting so a flapping header cannot grow
    // this without bound.
    property var fanPctHist: ({})
    // Which fans have EVER been seen to change their commanded duty, by name.
    // Set once and never cleared, and carried across a panel reload with the
    // rest of this state — a fan that answers the machine is a fan whose
    // reading means something, and that is a fact about the hardware, not about
    // this run. Losing it on every wallpaper change would put the pump back in
    // the headline for a minute each time. See Fans.qml for what it decides.
    property var fanVaried: ({})
    // name -> true for every fan ever seen turning with a real tachometer.
    // Only these can be judged to have STOPPED: the GPU fan reports a percentage
    // and no RPM, so "0 rpm" is its normal reading, and without this an
    // nvidia-smi hiccup would announce that the card's fan had failed.
    property var fanHadRpm: ({})
    readonly property int fanCount: fans ? fans.length : 0
    // The fan currently judged to have failed, or "". See FanAlarm.qml.
    readonly property string fanAlarm: fanAlarmState.active
    // Exposed for `qs ipc call live fans`: how far into the 30s confirmation
    // each stopped fan is, which is the only way to watch this arm without
    // waiting for it.
    readonly property var fanAlarmStoppedFor: fanAlarmState.stoppedFor

    // ---- what book shows in place of gpu/vram/fan ------------------------
    // See sysinfo.sh: that machine has no source for any of the three, so the
    // task manager gives those slots to these instead. Collected on both hosts.
    //
    // Pressure stall, "some avg10": the percentage of the last 10 seconds in
    // which at least one task was blocked on that resource. -1 without
    // /proc/pressure.
    property real psiCpu: -1
    property real psiIo: -1
    property real psiMem: -1
    // Whole-machine draw in watts, -1 where nothing reports it (top).
    property real powerW: -1
    // Physical-disk throughput, bytes/s — the same treatment as rxSpeed/txSpeed,
    // diffed from the cumulative sector counters below.
    property real dskRead: 0
    property real dskWrite: 0

    // Brightness. On a machine with a real panel backlight (laptops) this
    // goes through brightnessctl against /sys/class/backlight, which is
    // fast. Otherwise it falls back to DDC/CI over I2C via ddcutil for an
    // external monitor, which takes ~1.5s per call — far too slow for the
    // 2s main poll, hence the separate polling/debounce machinery below.
    // adjustBrightness() updates this optimistically so scrolling feels
    // instant; the periodic poll here just corrects for drift (e.g. the
    // monitor's own physical buttons).
    //
    // PERSISTED to SettingsStore.d.brightnessHw on every adjustment and
    // re-applied once per session (_restoreBrightness below), because neither
    // backend is a store we control: book's backlight is only written back by
    // systemd-backlight on a clean shutdown, and top's level is whatever the
    // monitor kept in its own NVRAM. settings.json is machine-local, so each
    // host remembers its own level.
    property int    brightness: -1      // 0-100, or -1 until first poll
    // Which brightness backend to drive. "auto" uses DDC whenever an external
    // output is attached, even on a laptop that also has a backlight; with only
    // the internal panel it uses brightnessctl. The Settings override still
    // forces either backend regardless of output topology.
    property bool   _hasBacklight: false
    readonly property bool _hasExternalOutput: {
        for (let i = 0; i < Quickshell.screens.length; ++i) {
            if (Quickshell.screens[i].name !== "eDP-1") return true;
        }
        return false;
    }
    readonly property bool useBacklight: {
        const be = SettingsStore.d.brightnessBackend;
        return be === "backlight" ? true : be === "ddc" ? false
            : _hasBacklight && !_hasExternalOutput;
    }
    readonly property bool useGammaBrightness:
        _hasExternalOutput && SettingsStore.d.brightnessBackend === "auto";

    // "Negative brightness". Once the hardware is at 0 and the user keeps
    // lowering, the extra steps come out of the compositor's gamma ramp
    // instead (hyprsunset), so the screen can go darker than the monitor
    // alone allows. 100 = no gamma reduction = the feature is off; anything
    // below means we're in the negative region and the panel/OSD read out a
    // negative level (gamma 80 -> "-20"). SettingsApply owns the hyprsunset
    // process and pushes this value to it — including killing it (which
    // restores the normal ramp) the moment we return to 100.
    //
    // The level is PERSISTED (SettingsStore.d.gammaLevel), so it survives a
    // panel reload — a theme change or an agent's Theme.qml bump rebuilds the
    // whole QML tree, and a plain `property int gamma: 100` here meant the
    // screen jumped back to full brightness every time. Read-only on purpose:
    // adjustGamma() writes the store, and the binding brings the new value
    // back, so there is exactly one copy of this state. Clamped to the current
    // floor on the way in, so raising the floor (or setting it to 100, which
    // disables the feature) takes effect on an already-negative screen.
    readonly property int gamma: {
        const floor = Math.max(5, Math.min(100, SettingsStore.d.gammaFloor));
        return Math.max(floor, Math.min(100, SettingsStore.d.gammaLevel));
    }
    readonly property bool negativeBrightness: gamma < 100
    // Signed level for display: the hardware value normally, gamma-below-100
    // once negative.
    readonly property int brightnessLevel: gamma < 100 ? gamma - 100 : brightness

    // Stereo VU levels (0-100), fed by VuMeter.qml's cava instance. They live
    // here rather than in VuMeter because the bar is instantiated per-monitor
    // inside a Variants, so it has no stable id for shell.qml's reload-continuity
    // wiring to reach — and "current output level" is system state like the rest
    // of this singleton anyway.
    property int vuL: 0
    property int vuR: 0

    // ...and so does the cava that feeds them. It used to live in VuMeter.qml,
    // which is instantiated per MONITOR (StatusPanel sits inside a Variants), so
    // there was one cava process per screen — two of the three running on this
    // machine were the same VU meter, the second belonging to a leftover sandbox
    // monitor. One reader, one process, however many bars draw it.
    // ---- is anything actually playing? ----
    // Both cava instances are gated on this. Unconditional, they cost ~19.5% of
    // a core with NOTHING PLAYING (cava 11.4%, plus double the panel's own CPU
    // animating bars at 60fps and triple wireplumber's serving two monitor
    // captures) — measured on book, see docs/perf-cpu-hotspots.md. That is a
    // laptop's battery spent drawing silence.
    //
    // Event-driven, not polled: `pactl subscribe` sits idle until PipeWire says
    // something changed. The 15s re-check below is only a backstop for a missed
    // event, and costs one script run.
    //
    // DEFAULTS TRUE and the script fails open, so any breakage here restores
    // exactly the old behaviour rather than leaving the meters dead.
    property bool audioActive: true

    Process {
        id: audioSub
        running: true
        command: ["sh", "-c", NixPath.sh + "exec pactl subscribe"]
        stdout: SplitParser {
            // "Event 'new' on sink-input #93" etc. Only playback matters.
            onRead: data => { if (data.indexOf("sink-input") >= 0) audioDebounce.restart(); }
        }
        onExited: audioSubRestart.restart()
    }
    // pactl emits a burst per stream change; one check after it settles.
    Timer { id: audioDebounce; interval: 120; onTriggered: audioCheck.running = true }
    Timer { id: audioSubRestart; interval: 2000; onTriggered: audioSub.running = true }
    Timer {
        interval: 15000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: audioCheck.running = true
    }

    Process {
        id: audioCheck
        command: ["sh", "-c",
            NixPath.sh
            + "exec python3 \"$HOME/.config/quickshell/scripts/audio-active.py\""]
        stdout: StdioCollector {
            onStreamFinished: {
                const on = this.text.trim() === "1";
                if (on === root.audioActive) return;
                root.audioActive = on;
                // Zero the meter rather than leaving the last reading frozen on
                // screen: a stale bar is indistinguishable from a live one, and
                // nothing here may show a value it isn't measuring
                // (docs/DESIGN.md — a drawn control tells the truth).
                if (!on) { root.vuL = 0; root.vuR = 0; }
            }
        }
    }

    Process {
        id: cavaVu
        running: root.audioActive
        // quickshell is launched from the Fedora session with a bare PATH that
        // omits ~/.nix-profile/bin, where cava (a nix pkg) lives — so widen it
        // or every spawn dies with "cava: not found" and the bars go dead.
        // NixPath.sh is the one definition of that fix; see NixPath.qml.
        // `vuSmoothing` / `vuFramerate` (Settings > Audio) are patched into a
        // runtime copy of the conf, the same shape Media.qml uses for the
        // spectrum's bar count — cava has no CLI for either. They were declared
        // and drawn but read by nobody, so the two sliders moved and the meter
        // did not. `bars` is deliberately NOT settable: this is a stereo meter
        // and cava's stereo mode is mirrored, so anything but 2 yields
        // frequency bands rather than channel levels (see VuMeter.qml).
        command: ["sh", "-c",
            NixPath.sh
            + "src=\"$HOME/.config/quickshell/scripts/cava-vu.conf\"; "
            + "cfg=\"${XDG_RUNTIME_DIR:-/tmp}/qs-cava-vu.conf\"; "
            + "sed -e \"s/^framerate *=.*/framerate = " + SettingsStore.d.vuFramerate + "/\" "
            + "-e \"s/^noise_reduction *=.*/noise_reduction = " + SettingsStore.d.vuSmoothing + "/\" "
            + "\"$src\" > \"$cfg\" && exec cava -p \"$cfg\""]
        stdout: SplitParser {
            onRead: data => {
                const parts = data.split(";");
                if (parts.length >= 2) {
                    root.vuL = Math.min(100, parseInt(parts[0], 10) || 0);
                    root.vuR = Math.min(100, parseInt(parts[1], 10) || 0);
                }
            }
        }
        // cava dying (e.g. pipewire restart) shouldn't leave dead bars
        onExited: cavaVuRestart.restart()
    }
    Timer {
        id: cavaVuRestart
        interval: 2000
        // Restore the BINDING, not a bare `true`: assigning true would break
        // `running: root.audioActive` for good, and cava would then never stop
        // again when playback ends — the gate would silently undo itself after
        // the first respawn. Harmless when audio has since stopped: the binding
        // re-evaluates to false and it stays down.
        onTriggered: cavaVu.running = Qt.binding(function () { return root.audioActive; })
    }

    // throughput history for the sparkline (bytes/s totals)
    property var history: []
    readonly property int historyLen: 24

    // Longer per-metric ring buffers for the hover line charts (CpuPanel,
    // EthPanel). chartLen samples * intervalSec = window; 90 * 2s = 3 min.
    readonly property int chartLen: 90
    property var cpuHist: []
    property var tempHist: []
    property var gpuHist: []
    property var gpuTempHist: []
    property var rxHist: []
    property var txHist: []
    property var memHist: []
    property var loadHist: []
    property var swapHist: []
    property var vramHist: []
    property var psiCpuHist: []
    property var psiIoHist: []
    property var psiMemHist: []
    property var powerHist: []
    property var dskRHist: []
    property var dskWHist: []

    // Battery charge is the ONE metric here that is sub-sampled rather than
    // pushed every poll. chartLen at the 2s poll is a three-minute window, over
    // which a battery does not measurably move — the card would draw a
    // permanently flat line and say nothing. One sample per battStepSec instead
    // gives the same 90 points an HOUR of span, which is long enough for the
    // slope (i.e. how long you have left) to be the thing you read off it.
    // Wall-clock gated, not a poll counter, so it is unaffected by the poll
    // interval setting and by the timer restarting on every panel reload.
    property var batteryHist: []
    readonly property int battStepSec: 40
    property real _battAt: 0

    function _pushHist(arr, v) {
        const h = arr.slice();
        h.push(v);
        while (h.length > chartLen) h.shift();
        return h;
    }

    // Parse sysinfo.sh's `fanDetail` field ("name:rpm:pct,name:rpm:pct,…") into
    // `fans`, append the GPU fan, and push this poll's sample onto each fan's
    // own history.
    //
    // The GPU fan is appended rather than kept separate because the card's
    // headline is "the fastest fan going", and on this desktop the loudest fan
    // in the box is frequently the one on the graphics card. It carries rpm -1:
    // nvidia-smi reports a percentage and no tachometer, and a fan with no
    // tachometer says so rather than borrowing a plausible number.
    //
    // Histories are keyed by NAME and PRUNED to the names still reporting, so a
    // header that flaps in and out cannot grow this object forever, and a fan
    // that vanishes does not leave its trace on another fan's line.
    function _setFans(raw) {
        const out = [];
        if (raw) {
            for (const e of String(raw).split(",")) {
                if (!e) continue;
                const p = e.split(":");
                if (p.length < 3) continue;
                const rpm = parseInt(p[1]);
                const pct = parseInt(p[2]);
                out.push({
                    name: p[0],
                    rpm: isNaN(rpm) ? -1 : rpm,
                    pct: isNaN(pct) || pct < 0 ? -1 : pct,
                });
            }
        }
        if (gpuFanPct >= 0)
            out.push({ name: "gpu", rpm: -1, pct: gpuFanPct });

        // A fan that STOPS reporting is re-emitted at 0 rpm rather than simply
        // vanishing. sysinfo.sh lists a fan only while it turns, so a fan that
        // dies just disappears from the line — and since the widget now HIDES
        // the pump outright (Fans.fixed), a pump failure would otherwise have no
        // indicator anywhere on this desktop. At 0 rpm and no duty it is nowhere
        // near maximum, so the hide rule cannot apply to it and it is always
        // drawn, marked STOPPED.
        //
        // ONLY fans that have never varied, which is the whole point: a fan
        // that has never moved is one the widget may be HIDING, and a hidden fan
        // that dies is the case with no indicator. A fan that has varied is one
        // he can see, so its line simply disappearing already tells him.
        //
        // That distinction is not pedantry — it is what stops this being noise.
        // Measured live: `fan5` on this board spun for ~20s and stopped, and the
        // first version of this reported it STOPPED for ever. Zero-RPM idle is
        // ordinary behaviour for a case fan, and pwm cannot tell it from a fault
        // here (empty headers on this chip hold 23-100% duty with nothing
        // attached). Requiring `!fanVaried` costs nothing on the case it exists
        // for — a pump that has never once moved — and removes every fan whose
        // stopping is normal.
        const live = {};
        for (const fan of out) live[fan.name] = true;
        for (const name in fanPctHist)
            if (!live[name] && !fanVaried[name] && fanHadRpm[name])
                out.push({ name: name, rpm: 0, pct: -1, stopped: true });

        const h = {};
        const varied = {};
        for (const name in fanVaried) varied[name] = fanVaried[name];
        for (const fan of out) {
            // A stopped fan keeps its history so it keeps its name, and with it
            // its row; pushing 0 into it would rewrite what it did when alive.
            if (fan.stopped) { h[fan.name] = fanPctHist[fan.name] || []; continue; }
            if (fan.pct < 0) continue;
            const prev = fanPctHist[fan.name] || [];
            // "Has this fan ever moved?" — the one question that separates a
            // fan the machine is controlling from a constant. Sticky and never
            // cleared: a chassis fan that ramped once is a real reading for
            // good, including while it sits pinned at 100% in a thermal event,
            // which is exactly when the headline must not drop it.
            if (prev.length > 0 && prev[prev.length - 1] !== fan.pct)
                varied[fan.name] = true;
            h[fan.name] = _pushHist(prev, fan.pct);
        }
        const hadRpm = {};
        for (const name in fanHadRpm) hadRpm[name] = fanHadRpm[name];
        for (const fan of out)
            if (!fan.stopped && fan.rpm > 0) hadRpm[fan.name] = true;

        fans = out;
        fanPctHist = h;
        fanVaried = varied;
        fanHadRpm = hadRpm;

        // One call per poll; returns a name only on the poll the episode is
        // confirmed, so one failure is one notification.
        const failed = fanAlarmState.update(out, h, varied, hadRpm);
        if (failed !== "") _notifyFanStopped(failed);
    }

    FanAlarm { id: fanAlarmState }

    // The loud half of the pump alarm. Critical urgency is doing four separate
    // jobs here, all of them already built: it plays soundCritical rather than
    // the balloon, it bypasses Do Not Disturb, it is exempt from the toast
    // stack's eviction, and it never auto-expires. `-t 0` says the last of those
    // explicitly as well, because the panel now honours an explicit timeout and
    // an alarm you can miss by looking away is not an alarm.
    //
    // Routed through notify-send like every other toast this repo raises
    // (shell.qml's reload failure, resize-mode-notify.sh) rather than poked into
    // the server directly, so it renders as an identical wal-themed card.
    //
    // The wording claims only what is measured — a fixed-speed fan has stopped —
    // and names the fan. It says "if this is the pump" rather than "your pump
    // has failed", because nothing here knows which header the pump is on.
    function _notifyFanStopped(name) {
        Quickshell.execDetached([
            "notify-send", "-a", "quickshell", "-u", "critical", "-t", "0",
            name + " has STOPPED",
            "a fan that ran at a fixed speed since boot now reads 0 rpm.\n"
            + "if this is the pump, the CPU is no longer being cooled."]);
    }

    // ---- reload continuity (see shell.qml's `persist` block) --------------
    // Quickshell rebuilds the whole QML tree on every reload — a QML edit, or
    // wal-set.sh rewriting Theme.qml on a wallpaper/theme change — so all of
    // the above would come back at its default: the charts empty, every
    // readout "--" until the next poll two seconds later. shell.qml carries
    // this blob across the reload and hands it back before the first frame, so
    // a reload looks like the panel simply kept running.
    //
    // Bumped once per poll; shell.qml re-snapshots on the change rather than
    // on each of the individual property signals.
    property int stateRev: 0

    function stateJson() {
        return JSON.stringify({
            rx: rxSpeed, tx: txSpeed, dfk: diskFreeKb, dup: diskUsePct,
            vol: volume, mut: muted, cu: cpuUsage, ct: cpuTemp,
            gu: gpuUsage, gt: gpuTemp, bp: batteryPct, bc: batteryCharging,
            bst: batteryStatus, bh: batteryHist, bat: _battAt,
            bri: brightness, hbl: _hasBacklight,
            h: history, ch: cpuHist, th: tempHist,
            gh: gpuHist, gth: gpuTempHist, rh: rxHist, tht: txHist,
            mtk: memTotalKb, mak: memAvailKb, stk: swapTotalKb, sfk: swapFreeKb,
            l1: load1, up: uptimeSec, gf: gpuFanPct, gp: gpuPowerW,
            gmu: gpuMemUsedMb, gmt: gpuMemTotalMb, mh: memHist,
            fns: fans, fph: fanPctHist, fvd: fanVaried, fhr: fanHadRpm,
            fsf: fanAlarmState.stoppedFor, fal: fanAlarmState.alerted,
            lh: loadHist, swh: swapHist, vh: vramHist,
            pc: psiCpu, pio: psiIo, pm: psiMem, pw: powerW,
            dr: dskRead, dw: dskWrite,
            pch: psiCpuHist, pih: psiIoHist, pmh: psiMemHist, pwh: powerHist,
            drh: dskRHist, dwh: dskWHist, pdr: _prevDskR, pdw: _prevDskW,
            // the running counters the next poll diffs against — without them
            // the first sample after a reload has no baseline and the readouts
            // sit at "--" for one interval, which is the flicker this avoids
            prx: _prevRx, ptx: _prevTx, pat: _prevAt,
            pct: _prevCpuTotal, pci: _prevCpuIdle,
        });
    }

    function restoreState(s) {
        if (!s) return;
        let d;
        try { d = JSON.parse(s); } catch (e) { return; }
        // This is a reload, not a fresh session: the live level came with us,
        // so there is nothing to put back.
        _restorePending = false;
        rxSpeed = d.rx; txSpeed = d.tx; diskFreeKb = d.dfk; diskUsePct = d.dup;
        volume = d.vol; muted = d.mut; cpuUsage = d.cu; cpuTemp = d.ct;
        gpuUsage = d.gu; gpuTemp = d.gt; batteryPct = d.bp; batteryCharging = d.bc;
        batteryStatus = d.bst || 0; batteryHist = d.bh || []; _battAt = d.bat || 0;
        brightness = d.bri; _hasBacklight = d.hbl;
        history = d.h || []; cpuHist = d.ch || []; tempHist = d.th || [];
        gpuHist = d.gh || []; gpuTempHist = d.gth || [];
        rxHist = d.rh || []; txHist = d.tht || []; memHist = d.mh || [];
        memTotalKb = d.mtk || 0; memAvailKb = d.mak || 0;
        swapTotalKb = d.stk || 0; swapFreeKb = d.sfk || 0;
        load1 = d.l1 === undefined ? -1 : d.l1;
        uptimeSec = d.up || 0;
        gpuFanPct = d.gf === undefined ? -1 : d.gf;
        gpuPowerW = d.gp === undefined ? -1 : d.gp;
        gpuMemUsedMb = d.gmu === undefined ? -1 : d.gmu;
        gpuMemTotalMb = d.gmt === undefined ? -1 : d.gmt;
        fans = d.fns || []; fanPctHist = d.fph || ({});
        fanVaried = d.fvd || ({});
        fanHadRpm = d.fhr || ({});
        // Carried too, or a wallpaper change would restart the 30s count and,
        // worse, re-fire a notification that has already been shown.
        fanAlarmState.stoppedFor = d.fsf || ({});
        fanAlarmState.alerted = d.fal || ({});
        loadHist = d.lh || []; swapHist = d.swh || [];
        vramHist = d.vh || [];
        psiCpu = d.pc === undefined ? -1 : d.pc;
        psiIo = d.pio === undefined ? -1 : d.pio;
        psiMem = d.pm === undefined ? -1 : d.pm;
        powerW = d.pw === undefined ? -1 : d.pw;
        dskRead = d.dr || 0; dskWrite = d.dw || 0;
        psiCpuHist = d.pch || []; psiIoHist = d.pih || []; psiMemHist = d.pmh || [];
        powerHist = d.pwh || []; dskRHist = d.drh || []; dskWHist = d.dwh || [];
        _prevDskR = d.pdr === undefined ? -1 : d.pdr;
        _prevDskW = d.pdw === undefined ? -1 : d.pdw;
        _prevRx = d.prx; _prevTx = d.ptx; _prevAt = d.pat || 0;
        _prevCpuTotal = d.pct; _prevCpuIdle = d.pci;
    }

    // The VU/spectrum feeds run at 60fps, far too hot to snapshot per frame,
    // so shell.qml samples this on a timer instead of on change.
    function metersJson() {
        return JSON.stringify({ l: vuL, r: vuR });
    }
    function restoreMeters(s) {
        if (!s) return;
        try { const d = JSON.parse(s); vuL = d.l; vuR = d.r; } catch (e) {}
    }

    property real _prevRx: -1
    property real _prevTx: -1
    // Wall-clock (ms) of the sample _prevRx/_prevTx came from. The throughput
    // deltas used to be divided by intervalSec on the assumption that the timer
    // fired exactly on schedule; measuring the real gap instead is both more
    // honest and what makes the counters survive a reload — the poll restarts
    // (triggeredOnStart) the moment the new tree is up, so the first sample
    // after a reload covers a fraction of an interval, and dividing it by a
    // whole one would draw a spurious dip into the chart.
    property real _prevAt: 0
    property real _prevCpuTotal: -1
    property real _prevCpuIdle: -1
    property real _prevDskR: -1
    property real _prevDskW: -1
    readonly property real intervalSec: SettingsStore.d.monPollSec

    readonly property string scriptPath:
        Qt.resolvedUrl("scripts/sysinfo.sh").toString().replace("file://", "")

    function parse(text) {
        const line = (text || "").trim();
        if (line === "") return;
        const f = line.split("|");
        if (f.length < 13) return;

        const rx      = parseFloat(f[0]) || 0;
        const tx      = parseFloat(f[1]) || 0;
        diskFreeKb    = parseInt(f[2]) || 0;
        diskUsePct    = parseInt(f[3]) || 0;
        volume        = parseInt(f[4]);
        muted         = f[5] === "1";

        const cpuTotal = parseFloat(f[6]) || 0;
        const cpuIdle  = parseFloat(f[7]) || 0;
        if (_prevCpuTotal >= 0) {
            const dTotal = cpuTotal - _prevCpuTotal;
            const dIdle  = cpuIdle - _prevCpuIdle;
            cpuUsage = dTotal > 0 ? Math.round(100 * (1 - dIdle / dTotal)) : 0;
        }
        _prevCpuTotal = cpuTotal;
        _prevCpuIdle  = cpuIdle;

        const rawTemp = parseInt(f[8]);
        cpuTemp = rawTemp < 0 ? -1 : Math.round(rawTemp / 1000);

        const gu = parseInt(f[9]);
        gpuUsage = isNaN(gu) || gu < 0 ? -1 : gu;
        const gt = parseInt(f[10]);
        gpuTemp = isNaN(gt) || gt < 0 ? -1 : gt;

        const bp = parseInt(f[11]);
        batteryPct = isNaN(bp) || bp < 0 ? -1 : bp;
        batteryCharging = f[12] === "1";

        // batStatus was appended last of all, so an older or foreign line is
        // simply a battery whose state we don't know rather than a parse
        // failure — and with no battery at all it stays 0 either way.
        if (f.length >= 32) {
            const bs = parseInt(f[31]);
            batteryStatus = isNaN(bs) || bs < 0 ? 0 : bs;
        } else if (batteryPct >= 0) {
            batteryStatus = batteryCharging ? 2 : 5;
        }

        // One sample per battStepSec — see batteryHist. The first reading is
        // taken immediately so the card is not empty for the first 40s of a
        // fresh login; after that the gate is the wall clock.
        if (batteryPct >= 0) {
            const tb = Date.now();
            if (_battAt <= 0 || tb - _battAt >= battStepSec * 1000) {
                batteryHist = _pushHist(batteryHist, batteryPct);
                _battAt = tb;
            }
        }

        // Everything past here was appended for the task manager (see
        // sysinfo.sh) — guarded so an older/foreign line still parses.
        if (f.length >= 23) {
            memTotalKb  = parseInt(f[13]) || 0;
            memAvailKb  = parseInt(f[14]) || 0;
            swapTotalKb = parseInt(f[15]) || 0;
            swapFreeKb  = parseInt(f[16]) || 0;
            const l1 = parseFloat(f[17]);
            load1 = isNaN(l1) ? -1 : l1;
            uptimeSec = parseInt(f[18]) || 0;
            const gf = parseInt(f[19]);
            gpuFanPct = isNaN(gf) || gf < 0 ? -1 : gf;
            const gp = parseFloat(f[20]);
            gpuPowerW = isNaN(gp) || gp < 0 ? -1 : gp;
            const gmu = parseInt(f[21]);
            gpuMemUsedMb = isNaN(gmu) || gmu < 0 ? -1 : gmu;
            const gmt = parseInt(f[22]);
            gpuMemTotalMb = isNaN(gmt) || gmt < 0 ? -1 : gmt;
            // f[23]/f[24] are the old fanAvgRpm/fanCount. They are still emitted
            // — the fields are POSITIONAL, so dropping two from the middle would
            // renumber eight downstream ones for nothing — but nothing reads
            // them any more: an average is the wrong summary for this data (one
            // fan pinned at 2400 with four idling reads the same as five fans
            // working moderately, and it is the pinned one you can hear), and
            // the per-fan list below supersedes both.
            if (f.length >= 33)
                _setFans(f[32]);

            if (memUsage >= 0) memHist = _pushHist(memHist, memUsage);
            if (load1 >= 0) loadHist = _pushHist(loadHist, load1);
            if (swapUsage >= 0) swapHist = _pushHist(swapHist, swapUsage);
            if (gpuMemUsage >= 0) vramHist = _pushHist(vramHist, gpuMemUsage);
            // the GPU fan's own history now rides in fanPctHist["gpu"], with
            // every other fan's — see _setFans()
        }

        // The pressure/power/disk block (book's replacements for gpu, vram and
        // fan), guarded the same way so a line from an older script still parses.
        let dskR = -1, dskW = -1;
        if (f.length >= 31) {
            dskR = parseFloat(f[25]);
            dskW = parseFloat(f[26]);
            if (isNaN(dskR) || isNaN(dskW)) { dskR = -1; dskW = -1; }
            const pc  = parseFloat(f[27]);
            psiCpu = isNaN(pc) || pc < 0 ? -1 : pc;
            const pio = parseFloat(f[28]);
            psiIo = isNaN(pio) || pio < 0 ? -1 : pio;
            const pm  = parseFloat(f[29]);
            psiMem = isNaN(pm) || pm < 0 ? -1 : pm;
            const pw  = parseFloat(f[30]);
            powerW = isNaN(pw) || pw < 0 ? -1 : pw;

            if (psiCpu >= 0) psiCpuHist = _pushHist(psiCpuHist, psiCpu);
            if (psiIo >= 0) psiIoHist = _pushHist(psiIoHist, psiIo);
            if (psiMem >= 0) psiMemHist = _pushHist(psiMemHist, psiMem);
            if (powerW >= 0) powerHist = _pushHist(powerHist, powerW);
        }

        const now = Date.now();
        if (_prevRx >= 0) {
            // real elapsed time, floored so a fast double-poll can't divide by
            // ~0 and draw a spike off the top of the chart
            const dt = _prevAt > 0 ? Math.max(0.25, (now - _prevAt) / 1000) : intervalSec;
            rxSpeed = Math.max(0, (rx - _prevRx) / dt);
            txSpeed = Math.max(0, (tx - _prevTx) / dt);
            const h = history.slice();
            h.push(rxSpeed + txSpeed);
            while (h.length > historyLen) h.shift();
            history = h;
            rxHist = _pushHist(rxHist, rxSpeed);
            txHist = _pushHist(txHist, txSpeed);

            // Same elapsed-time denominator as the network counters, and the
            // same reason: the first poll after a reload covers a fraction of
            // an interval. 512B sectors (the /proc/diskstats unit).
            if (dskR >= 0 && _prevDskR >= 0) {
                dskRead  = Math.max(0, (dskR - _prevDskR) * 512 / dt);
                dskWrite = Math.max(0, (dskW - _prevDskW) * 512 / dt);
                dskRHist = _pushHist(dskRHist, dskRead);
                dskWHist = _pushHist(dskWHist, dskWrite);
            }
        }
        _prevRx = rx;
        _prevTx = tx;
        _prevAt = now;
        if (dskR >= 0) { _prevDskR = dskR; _prevDskW = dskW; }

        // CPU/temp history for the hover charts (cpuUsage/cpuTemp are set above)
        if (cpuUsage >= 0) cpuHist = _pushHist(cpuHist, cpuUsage);
        if (cpuTemp >= 0) tempHist = _pushHist(tempHist, cpuTemp);
        if (gpuUsage >= 0) gpuHist = _pushHist(gpuHist, gpuUsage);
        if (gpuTemp >= 0) gpuTempHist = _pushHist(gpuTempHist, gpuTemp);

        stateRev++;   // one snapshot per poll (see stateJson above)
    }

    // Human-readable bytes/s -> e.g. "1.2M", "34K", "0"
    function fmtSpeed(bps) {
        if (bps < 1024) return "0";
        if (bps < 1024 * 1024) return Math.round(bps / 1024) + "K";
        return (bps / 1024 / 1024).toFixed(1) + "M";
    }

    function fmtSize(kb) {
        if (kb < 1024 * 1024) return Math.round(kb / 1024) + "M";
        return (kb / 1024 / 1024).toFixed(0) + "G";
    }

    // Scroll-to-adjust from the panel. wpctl is fast (~8ms measured) so this
    // just fires straight through per tick, same as the media-key binds
    // (hypr/hyprland.lua) — 5%-per-tick steps, -l 1 caps at 100%.
    function adjustVolume(step) {
        if (volume < 0) volume = 50;
        volume = Math.max(0, Math.min(100, volume + step));
        Quickshell.execDetached(["wpctl", "set-volume", "-l", "1", SettingsStore.d.audioSink,
            Math.abs(step) + "%" + (step >= 0 ? "+" : "-")]);
        Sounds.playThrottled(SettingsStore.d.soundVolume, 250);
    }

    // Absolute set — the VU meter's draggable level line. Optimistic like
    // adjustVolume; no-op when the target equals the current value so a drag
    // only fires wpctl when the integer actually changes.
    function setVolume(v) {
        v = Math.round(Math.max(0, Math.min(100, v)));
        if (v === volume) return;
        volume = v;
        Quickshell.execDetached(["wpctl", "set-volume", "-l", "1", SettingsStore.d.audioSink, v + "%"]);
        // (audioSink defaults to "@DEFAULT_AUDIO_SINK@" — the system default.)
        Sounds.playThrottled(SettingsStore.d.soundVolume, 250);
    }

    // Optimistic local update (instant panel feedback) + a debounced actual
    // ddcutil write — see the brightness property doc above for why.
    //
    // ddcBusy mutually excludes the periodic read poll and the write below,
    // as a defensive measure against overlapping I2C/DDC transactions (the
    // actual bug found live was elsewhere — Osd.qml independently re-read
    // brightness via a stale/broken command and clobbered this property
    // right before the debounced write picked it up — but two ddcutil
    // calls racing the same I2C bus is still worth avoiding on its own).
    property bool ddcBusy: false

    function adjustBrightness(step) {
        if (useGammaBrightness) {
            if (brightness < 0) brightness = SettingsStore.d.brightnessExternal;
            brightness = Math.max(5, Math.min(100, brightness + step));
            SettingsStore.d.brightnessExternal = brightness;
            SettingsStore.save();
            Osd.trigger("brightness");
            return;
        }
        if (brightness < 0) brightness = 50;
        // Below hardware zero, and back up again: lowering at 0 eats gamma,
        // and raising gives all of the gamma back BEFORE the hardware level
        // starts climbing again, so the two halves of the range are one
        // continuous line.
        if (step < 0 && brightness === 0) { adjustGamma(step); return; }
        if (step > 0 && gamma < 100)      { adjustGamma(step); return; }
        brightness = Math.max(0, Math.min(100, brightness + step));
        // Remember it for the next session. save() is debounced (300ms), so a
        // scroll down the whole range is one disk write, like the DDC one.
        SettingsStore.d.brightnessHw = brightness;
        SettingsStore.save();
        Osd.trigger("brightness");
        // Leading-edge fire: a single tick after being idle writes
        // immediately (0ms artificial delay — ddcutil itself is still
        // ~1.5s, a hard DDC/I2C protocol limit, not something software can
        // speed up). Only coalesce into the trailing debounce when a write
        // is already in flight or another tick landed within the last
        // debounce window, so rapid scrolling still doesn't stack up
        // several overlapping slow calls.
        if (ddcBusy || brightnessWriteDebounce.running) {
            brightnessWriteDebounce.restart();
        } else {
            fireBrightnessWrite();
        }
    }

    // Gamma side of the range. No debounce needed — hyprsunset's IPC is
    // instant (unlike the ~1.5s DDC write), so every tick lands right away.
    function adjustGamma(step) {
        const floor = Math.max(5, Math.min(100, SettingsStore.d.gammaFloor));
        SettingsStore.d.gammaLevel = Math.max(floor, Math.min(100, gamma + step));
        SettingsStore.save();
        Osd.trigger("brightness");
    }

    function fireBrightnessWrite() {
        if (useGammaBrightness) return;
        ddcBusy = true;
        ddcutilWriteProc.command = useBacklight
            ? ["brightnessctl", "set", String(root.brightness) + "%"]
            : ["ddcutil", "setvcp", "10", String(root.brightness)];
        ddcutilWriteProc.running = true;
    }

    Timer {
        id: brightnessWriteDebounce
        interval: 300
        repeat: false
        onTriggered: {
            if (ddcBusy) { brightnessWriteDebounce.restart(); return; }
            fireBrightnessWrite();
        }
    }

    Process {
        id: ddcutilWriteProc
        onExited: ddcBusy = false
    }

    Process {
        id: ddcutilProc
        command: root.useBacklight
            ? ["brightnessctl", "-m", "i"]
            : ["ddcutil", "getvcp", "10", "--brief"]
        onExited: ddcBusy = false
        stdout: StdioCollector {
            onStreamFinished: {
                if (root.useBacklight) {
                    // "<class>,<name>,<current>,<percent>%,<max>"
                    const parts = text.trim().split(",");
                    if (parts.length >= 4) {
                        const v = parseInt(parts[3]);
                        if (!isNaN(v)) root.brightness = v;
                    }
                } else {
                    // "VCP 10 C <current> <max>"
                    const parts = text.trim().split(/\s+/);
                    if (parts.length >= 4) {
                        const v = parseInt(parts[3]);
                        if (!isNaN(v)) root.brightness = v;
                    }
                }
            }
        }
    }

    // Detect a real panel backlight once at startup; output topology then picks
    // brightnessctl for the panel or ddcutil for an attached external display.
    // Runs before the timer below
    // (triggeredOnStart) issues the first read.
    Process {
        id: backlightDetectProc
        command: ["sh", "-c", "ls /sys/class/backlight/*/brightness 2>/dev/null | head -n1"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                root._hasBacklight = text.trim() !== "";
                root._backlightProbed = true;
            }
        }
    }

    // Has the probe above answered? The poll below waits for it: `useBacklight`
    // is false until it has, so a read issued at component completion ran
    // `ddcutil getvcp` on the LAPTOP — an external-monitor command on a machine
    // with no external monitor, whose empty output simply left `brightness` at
    // -1 for the first 30s.
    property bool _backlightProbed: false
    // Is the session-start restore still owed? Cleared by restoreState() too:
    // a panel RELOAD carries the live value across and must not re-drive the
    // hardware (on top that is a 1.5s DDC write per reload).
    property bool _restorePending: true

    // Put the remembered level back, once, before the first read — rather than
    // after one, so nothing can read the old hardware value and clobber it.
    // Returns true if it took the tick.
    function _restoreBrightness() {
        _restorePending = false;
        // A fresh tree evaluates its bindings against the SHIPPED DEFAULTS;
        // settings.json lands ~25ms later, long after this. Imperative code
        // reading the store must pull it in first — see SettingsStore.loadNow().
        SettingsStore.loadNow();
        const want = SettingsStore.d.brightnessHw;
        if (useGammaBrightness) {
            brightness = Math.max(5, Math.min(100, SettingsStore.d.brightnessExternal));
            return true;
        }
        if (want < 0 || want > 100) return false;   // never set here: leave it be
        brightness = want;
        fireBrightnessWrite();
        return true;
    }

    Timer {
        interval: 30000
        running: root._backlightProbed
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            if (root._restorePending && root._restoreBrightness()) return;
            if (root.useGammaBrightness) return;
            if (ddcBusy) return;
            ddcBusy = true;
            ddcutilProc.running = true;
        }
    }

    Process {
        id: proc
        // The two settings sysinfo.sh takes (Widgets > monitoring). As a
        // binding rather than a one-shot read, so editing either in Settings
        // moves the readout on the next poll instead of at the next reload.
        command: ["sh", root.scriptPath,
                  SettingsStore.d.rootMount || "/",
                  SettingsStore.d.netInterface || "auto"]
        stdout: StdioCollector {
            onStreamFinished: root.parse(this.text)
        }
    }

    Timer {
        interval: root.intervalSec * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: proc.running = true
    }
}

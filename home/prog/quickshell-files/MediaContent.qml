import QtQuick
import Quickshell

// The media widget's body: source app, track, cover art, cava spectrum, a
// draggable seekbar and the transport row. Everything it shows — including the
// spectrum feed — belongs to the Media singleton; being on screen is this
// component's only contribution, which is what `active` communicates (and what
// starts and stops cava).
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    // Whether the EQ overlay is out over the spectrum. TRANSIENT, not a
    // SettingsStore key: it is a throwaway view state, and a wallpaper or
    // theme change reloads the panel from shipped defaults, so the overlay
    // coming back closed is the honest state — it should not re-open beside
    // the user on a relog/theme change (see quickshell-files/AGENTS.md on
    // transient state vs a user-picked setting).
    property bool eqOpen: false
    property int pad: 10
    readonly property real inner: Math.max(180, width - 24)
    // A band gain, rendered for the EQ readouts: always one decimal, sign-prefixed.
    function fmtDb(db) {
        const v = db || 0;
        return (v > 0 ? "+" : "") + v.toFixed(1) + " dB";
    }

    // ---- Non-pixel-font queue text: a fallback that FITS the pixel cell ----
    // The pixel font (More Perfect DOS VGA) has no CJK glyphs, so Qt falls back
    // to Noto Sans CJK for a Japanese/Chinese/fullwidth title. Noto's line
    // metrics (ascent 17, height 21 at 15px) overflow the panel's FixedHeight
    // 15px line box, so the whole row is pushed down inside its 16px cell and
    // clipped along the bottom — the "CJK sits low against the Latin rows next
    // to it" report. Unifont is the one installed family whose metrics FIT the
    // pixel cell (ascent 13 / descent 2 / height 15, all measured) AND covers
    // the whole BMP, and it is itself a bitmap font, so such a row keeps the
    // desktop's pixel look instead of clashing with a smooth sans. Draw these
    // rows in Unifont and they sit on (nearly) the same baseline as the ASCII
    // rows, uncropped. A string that mixes Latin with a foreign script takes
    // Unifont for the whole line — one font, one baseline — rather than
    // re-introducing the cross-font ascent mismatch.
    //
    // The same clip hits EVERY script the pixel font lacks that has no ASCII
    // form for Glyphs.px() to map to — not just CJK. The regex ranges are the
    // BMP script blocks More Perfect covers ZERO of (verified against its cmap):
    // ԰-֏ Armenian, then ؀-᣿ — Arabic/Syriac/Thaana/N'Ko,
    // Devanagari and every other Indic, Thai/Lao/Tibetan, Myanmar/Georgian,
    // Hangul Jamo, Ethiopic/Cherokee/Khmer/Mongolian — plus the original CJK
    // ranges. Hebrew (֐-׿) is deliberately EXCLUDED: More Perfect
    // draws its alphabet itself, so it stays in the pixel font. Partially
    // covered Cyrillic/Greek are excluded for the same reason — routing them
    // would uglify text the pixel font renders fine. An allowlist of the major
    // scripts, not exhaustive over the whole BMP; widen it deliberately.
    readonly property var _noPixelRe: /[\u0530-\u058f\u0600-\u18ff\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]/
    function needsUnifont(s) { return s !== null && s !== undefined && _noPixelRe.test(s); }

    onActiveChanged: {
        Media.watch(root, active);
        // An invisible copy must not keep the overlay open (and with it the
        // EasyEffects socket): close it when we stop being watched.
        if (!active) {
            if (root.eqOpen) root.eqOpen = false;
            Media.eqRelease();          // drop the direct-scroll socket too
        }
    }
    onEqOpenChanged: { if (root.active) Media.watchEq(eqOpen); }
    Component.onCompleted: { Media.watch(root, active); Media.watchEq(eqOpen); drawerOut = Media.queueOpen; noteRestSlack(); }
    Component.onDestruction: { Media.watch(root, false); Media.watchEq(false); Media.eqRelease(); }

    // ---- a transport button: pixel-font glyph, themed frame -------------
    component MediaButton: Rectangle {
        id: btn
        property string kind: "play"   // prev | next | play | pause | shuffle | repeat | fav
        property bool active: true
        property bool toggled: false   // lit accent even without hover (repeat/shuffle on)
        // true draws the favourite as a REAL red heart instead of the pixel
        // glyph + fill-invert every other transport toggle uses
        property bool heart: false
        // non-empty replaces the kind-derived glyph — the repeat button uses it
        // to swap `o` (repeat-all) for `1` (repeat-one), matching the app
        property string glyphOverride: ""
        signal clicked()

        // glyph per kind: skip << >>, play/pause > ||, shuffle *, repeat o,
        // favourite heart \u2665
        readonly property string glyph: glyphOverride !== "" ? glyphOverride
            : kind === "prev" ? "<<"
            : kind === "next" ? ">>"
            : kind === "pause" ? "||"
            : kind === "shuffle" ? "*"
            : kind === "fav" ? "\u2665"
            : kind === "repeat" ? "o"
            : ">"   // play

        // 24, not 26: five of these now share a row with the seekbar, and at the
        // narrow end of the panel's range every pixel they take comes straight
        // out of the seekbar's width.
        width: 24
        height: 24
        // toggled (repeat/shuffle on) inverts like the titlebar roll button:
        // accent fill + background-coloured glyph. Hover is the lighter bgAlt tint.
        // The heart does NOT fill-invert — its own red colour carries the state.
        color: btn.heart
            ? ((mba.containsMouse && active) ? Theme.bgAlt : "transparent")
            : btn.toggled ? Theme.accent : ((mba.containsMouse && active) ? Theme.bgAlt : "transparent")
        radius: Theme.windowRounding
        border.width: Theme.ctrlBorder
        border.color: !active ? Theme.border
            : btn.heart ? ((mba.containsMouse ? Theme.accent : Theme.border))
            : (btn.toggled ? Theme.accent : ((mba.containsMouse) ? Theme.accent : Theme.border))
        opacity: active ? 1 : 0.4

        PixelText {
            anchors.centerIn: parent
            visible: !btn.heart
            text: btn.glyph
            color: btn.toggled ? Theme.bg : ((mba.containsMouse && btn.active) ? Theme.accent : Theme.text)
        }
        // The favourite is a REAL red heart, not a single-colour pixel button:
        // U+2665 is not in the pixel font's cmap (docs/DESIGN.md §2.3), so it is
        // drawn with a smooth fallback-font Text and coloured Theme.crit when
        // favourited — the now-playing window's "heart = red" meaning, and the
        // "real red heart in an in-window row" the board question asked for.
        Text {
            anchors.fill: parent
            visible: btn.heart
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: btn.glyph
            textFormat: Text.PlainText
            font.pixelSize: Theme.fontSize + 1
            color: btn.toggled ? Theme.crit : ((mba.containsMouse && btn.active) ? Theme.accent : Theme.dim)
        }

        MouseArea {
            id: mba
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: btn.active ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: if (btn.active) btn.clicked()
        }
    }

    // ---- spectrum: mediaSpectrumBars vertical bars ----------------------
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
        // The measuring grid: `gridRows` hairlines dividing the spectrum into
        // equal rows, top to bottom, in `Theme.border` — the hairline the volume
        // column and the tile frames already use, so the grid arrives without a
        // new colour in it. No labels and no shading, both by request: rules on
        // the plain background, nothing else. (Alternating a subtle fill was
        // tried twice, once on every other BAR and once on every other grid ROW,
        // and rejected both times. Don't re-add either.)
        //
        // EVENLY SPACED IN PIXELS, [his] — a deliberate reversal worth recording
        // so it does not get "fixed" back. It was briefly a gamma-mapped ladder
        // (100/75/50/25/12.5/6.25 of cava's scale, i.e. -0 to -24 dB, each rule
        // landing where that amplitude actually draws) on the reasoning that an
        // evenly-spaced rule measures nothing in particular once `gamma` has
        // bent the axis. True, but it bought a numeric honesty nothing labelled
        // and cost the thing a grid is FOR: rules bunched into the top half,
        // uncountable, most of them dark. Even spacing it is; the dB reading is
        // not coming back without labels to carry it.
        //
        // Eight rows because it halves cleanly — the midpoint, the quarters and
        // the eighths are all rules, so the eye can bisect its way to a level
        // without counting from the bottom — and because it is comfortably more
        // than the "3 or 4" that read as too few.
        readonly property int gridRows: 8
        // Minimum legible row height. Derived from the row COUNT rather than
        // written as a height literal, so changing `gridRows` moves the
        // threshold by itself — below it the grid is a smear rather than
        // something countable, and it also keeps these out of the degenerate
        // layout passes construction and teardown produce.
        readonly property int minGridPx: 6
        Repeater {
            model: spec.gridRows
            Rectangle {
                required property int index
                anchors { left: parent.left; right: parent.right }
                y: Math.round(spec.height * index / spec.gridRows)
                height: 1
                color: Theme.border
                visible: spec.height >= spec.gridRows * spec.minGridPx
            }
        }

        // Bars are gapless, so they can't be laid out by a Row with spacing 0: at
        // 32 buckets the per-bar width is fractional, and rounding each one
        // independently leaves subpixel seams between them. Position from the
        // shared edge instead — bar i spans round(w*i/n)..round(w*(i+1)/n), so one
        // bar's right edge IS the next one's left edge and the row stays exactly
        // `width` wide however the division falls.
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
                        * Math.pow(Math.max(0, Media.spectrumLevels[index] || 0) / 100, spec.gamma))
                    // UNIFORM. Every other BAR was briefly shaded a rung down to
                    // Theme.dim; that was a misreading of "every other" — the
                    // alternation belongs to the grid ROWS above, and the bars
                    // are one series drawn in one colour.
                    color: Theme.textDim
                    // cava already smooths (noise_reduction) and feeds 60fps, so
                    // this is a second low-pass on top. Keep it just long enough
                    // to absorb a dropped frame, not to re-add lag.
                    Behavior on height { NumberAnimation { duration: 25 } }
                }

                // peak marker — same gamma as the bar so it lines up with the bar
                // top on a fresh hit. Deliberately NOT animated: the fall is
                // already interpolated frame-by-frame by the gravity model, and a
                // Behavior here would drag the marker behind the peak it is
                // supposed to be pinning.
                //
                // The bar/marker pair is a light-on-dark split of the same hue:
                // the bars take Theme.textDim (the elapsed/remaining time colour)
                // and the markers the brighter Theme.accent, so a marker reads
                // both against the background it usually floats over and against
                // its own bar on the frames it rides the top. 2px tall — at 1px a
                // falling marker was too faint to track.
                Rectangle {
                    anchors { left: parent.left; right: parent.right }
                    height: 2
                    y: Math.min(spec.height - height, Math.max(0, spec.height - height - spec.height
                        * Math.pow(Math.max(0, Media.spectrumPeaks[index] || 0) / 100, spec.gamma)))
                    color: Theme.accent
                    visible: (Media.spectrumPeaks[index] || 0) > 0
                }
            }
        }
    }

    // ---- in-panel equalizer: the output EQ EasyEffects applies, editable ----
    // Toggled by clicking the spectrum. Draws the EQ's bands as vertical
    // faders whose handles sit at their current gain, on the same 30..16000 Hz
    // axis the spectrum uses. Dragging a fader writes that band's gain to
    // EasyEffects over its local socket (Media.setBandGain), so the change
    // lands in real time.
    //
    // When EasyEffects cannot take a band write (the stock 8.2.7 build does
    // not expose the per-channel field — Media.eqWriteLive is probed, not
    // assumed) the overlay still draws the EQ but disables the edit and says
    // why. docs/DESIGN.md 10.2: refuse visibly, never silently no-op. Closing
    // is "click a spot that is not on a fader".
    component Equalizer: Item {
        id: eq
        readonly property real fmin: 30
        readonly property real fmax: 16000
        readonly property var bands: Media.eqBands
        // `bands` is a property `var`, which arrives UNDEFINED on the other
        // QML engine for a beat during a panel reload (see Media.qml reload
        // continuity). Coerce that to 0 here — it gates delegate creation, so
        // every delegate-level read (freq, refresh's `.gain`) is skipped for
        // the undefined window instead of throwing "Cannot read property gain
        // of undefined" into the cumulative `qs log`.
        readonly property int n: (eq.bands && eq.bands.length) || 0
        readonly property bool editable: Media.eqWriteLive
        // One wheel notch = one 1 dB step (a discrete stepper, §9.2 — not a
        // scroll surface), clamped to the EQ's ±36 dB range in `setBandGain`.
        readonly property real stepDb: 1
        // The band under the cursor — the wheel target and the hover affordance.
        property int hoverBand: -1

        // The faint signal backdrop beneath the faders. Same cava buckets the
        // main spectrum draws, laid out on the SAME linear frequency axis as the
        // hidden-EQ spectrum (evenly across the full width) so the shape matches
        // exactly what he already watches when the EQ is closed — the backdrop IS
        // the ordinary spectrum at low opacity; only the faders, on their own log
        // axis, sit on top of it. A BACKDROP literally: low opacity, in the same
        // textDim tone the real bars use, so the faders stay the bright thing.
        // See DESIGN.md §3.2 (bulk dim, indicator bright).
        readonly property int nbars: SettingsStore.d.mediaSpectrumBars
        readonly property real backOpacity: 0.30

        // Log frequency -> x. A missing or non-positive freq falls back to the
        // low end rather than producing NaN.
        function freqX(f) {
            const ff = (f > 0) ? f : eq.fmin;
            const x = (Math.log(ff) - Math.log(eq.fmin)) / (Math.log(eq.fmax) - Math.log(eq.fmin));
            return Math.round(Math.max(0, Math.min(1, x)) * width);
        }
        // +36 dB at the top, -36 dB at the bottom, 0 dB centred.
        function gainY(g) {
            const c = Math.max(-36, Math.min(36, g || 0));
            return Math.round((36 - c) / 72 * height);
        }
        function freqAt(b) { return (b && b.freq > 0) ? b.freq : eq.fmin; }

        Rectangle {                       // the overlay surface
            anchors.fill: parent
            color: Theme.bgAlt
            border.width: Theme.ctrlBorder
            border.color: Theme.border
        }

        // The signal backdrop: one column per cava bucket, positioned exactly
        // like the main spectrum's bars — evenly across the full width with the
        // same round(w*i/n)..round(w*(i+1)/n) shared-edge layout — plus a
        // hairline gap so a full-height bar does not touch the frame's inner
        // edge. Height maps the level exactly like the main spectrum (gamma
        // 0.55, bottom-anchored), so behind the faders it IS the familiar
        // spectrum; only the opacity (low) is new. The 25ms low-pass mirrors
        // the main bars, so a dropped cava frame does not freeze the backdrop.
        Repeater {
            model: eq.nbars
            Rectangle {
                required property int index
                readonly property int x0: Math.round(eq.width * index / eq.nbars)
                x: x0
                width: Math.max(1, Math.round(eq.width * (index + 1) / eq.nbars) - x0)
                anchors { bottom: eq.bottom; bottomMargin: 1 }
                height: Math.max(1, eq.height
                    * Math.pow(Math.max(0, Media.spectrumLevels[index] || 0) / 100, 0.55))
                color: Theme.textDim
                opacity: eq.backOpacity
                Behavior on height { NumberAnimation { duration: 25 } }
            }
        }

        Rectangle {                       // the 0 dB line
            x: 0; width: parent.width
            y: eq.gainY(0)
            height: 1
            color: Theme.dim
        }

        PixelText {                       // an EQ that has not been read yet
            visible: eq.n === 0
            anchors.centerIn: parent
            text: "no EQ"
            color: Theme.textDim
        }

        Repeater {
            id: bandRep
            model: eq.n
            delegate: Item {
                required property int index
                readonly property real freq: eq.freqAt(eq.bands[index])
                // Read on `refresh`, so a drag writes straight back through the
                // socket without fighting the config file; reopening re-reads.
                property real gain: 0
                x: eq.freqX(freq)
                width: 1
                height: parent.height

                Rectangle {               // hover/scroll target: lights under the cursor
                    visible: eq.editable && eq.hoverBand === index
                    x: -4; y: 0; width: 9; height: parent.height
                    color: Theme.highlight
                }
                Rectangle {               // grab column (a bit wider than drawn)
                    x: -3; y: 0; width: 7; height: parent.height
                    color: "transparent"
                }
                Rectangle {               // vertical track
                    x: -1; y: 1; width: 2; height: parent.height - 2
                    color: (eq.editable && eq.hoverBand === index) ? Theme.accent : Theme.border
                }
                Rectangle {               // the handle, riding at the gain level
                    x: -4; y: eq.gainY(gain) - 1
                    width: 8; height: 3
                    color: eq.editable ? Theme.accent : Theme.textDim
                }
                function refresh() {
                    gain = (eq.bands && index < eq.bands.length && eq.bands[index])
                        ? (eq.bands[index].gain || 0) : 0;
                }
                function setGain(db) { gain = db; }
                Component.onCompleted: refresh()
            }
        }

        // Live gain readout for the band under the cursor (the wheel target).
        // Reads `eq.bands`, which `setBandGain` writes, so it tracks a scroll.
        PixelText {
            visible: eq.editable && eq.hoverBand >= 0
            anchors { top: parent.top; topMargin: 2; horizontalCenter: parent.horizontalCenter }
            text: {
                const b = (eq.bands && eq.hoverBand >= 0 && eq.hoverBand < eq.bands.length)
                    ? eq.bands[eq.hoverBand] : null;
                if (!b) return "";
                return (b.gain > 0 ? "+" : "") + b.gain.toFixed(1) + " dB";
            }
            color: Theme.text
        }

        // The disabled-edit footer (visible only while EQ writes are off).
        PixelText {
            anchors { bottom: parent.bottom; bottomMargin: 2; horizontalCenter: parent.horizontalCenter }
            text: eq.editable ? "" : "EQ read-only"
            color: Theme.textDim
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.ArrowCursor
            property int active: -1
            property real downX: -1
            property real downY: -1
            property bool dragged: false
            function bandAt(x) {
                let best = -1, bestD = 1e9;
                for (let i = 0; i < eq.n; i++) {
                    const d = Math.abs(x - eq.freqX(eq.freqAt(eq.bands[i])));
                    if (d < bestD) { bestD = d; best = i; }
                }
                return bestD <= 7 ? best : -1;
            }
            function setFromY(i, y) {
                const db = Math.round((36 - y / height * 72) * 10) / 10;
                // Only fire the socket when the write path exists; the handle
                // moves either way (a direct-manipulation drag — DESIGN.md 6.4).
                const del = bandRep.itemAt(i);
                if (del) del.setGain(db);
                if (eq.editable) Media.setBandGain(i, db);
            }
            onPressed: (m) => {
                downX = m.x; downY = m.y; dragged = false;
                active = bandAt(m.x);
                if (active >= 0) setFromY(active, m.y);
            }
            onPositionChanged: (m) => {
                // Track the wheel/hover target regardless of press state.
                eq.hoverBand = bandAt(m.x);
                if (active < 0) return;
                if (Math.abs(m.x - downX) > 2 || Math.abs(m.y - downY) > 2) dragged = true;
                setFromY(active, m.y);
            }
            onExited: eq.hoverBand = -1
            onReleased: {
                // A tap that was not on a fader closes the overlay.
                if (active < 0) { root.eqOpen = false; }
                active = -1;
            }

            // Scroll over a band steps its gain (a discrete stepper, so the
            // notch accumulator, never a sign test). The handle and the live
            // readout move immediately — direct manipulation, no easing (§6.4).
            WheelNotch { id: eqNotch }
            onWheel: (wheel) => {
                if (!eq.editable) return;           // read-only: refused, footer says why
                const i = bandAt(wheel.x);
                if (i < 0) return;
                const n = eqNotch.steps(wheel);
                if (n === 0) return;
                const del = bandRep.itemAt(i);
                const cur = del ? del.gain : 0;
                // Clamped to ±36 dB; setBandGain clamps again at the socket.
                const db = Math.max(-36, Math.min(36, Math.round((cur + n * eq.stepDb) * 100) / 100));
                if (del) del.setGain(db);
                Media.setBandGain(i, db);
            }
        }

        // Re-read the band values the moment the overlay opens (and after any
        // EasyEffects autosave while it stays open), so it always reflects the
        // real EQ rather than a stale frame.
        Connections {
            target: root
            function onEqOpenChanged() {
                if (!root.eqOpen) return;
                for (let i = 0; i < bandRep.count; i++) {
                    const d = bandRep.itemAt(i);
                    if (d) d.refresh();
                }
            }
        }
        Connections {
            target: Media
            function onEqBandsChanged() {
                if (!root.eqOpen) return;
                for (let i = 0; i < bandRep.count; i++) {
                    const d = bandRep.itemAt(i);
                    if (d) d.refresh();
                }
            }
        }
    }

    // Layout: the artwork/spectrum row starts at the widget's TOP edge, the
    // seekbar + transport are pinned to the bottom, and that middle row takes
    // EVERYTHING in between. So the widget has no dead space at either end
    // whatever height the grid gives it — and a bigger tile buys a bigger cover
    // and a taller spectrum rather than emptiness.
    //
    // The track line used to be a full-width row ABOVE all of this, which left
    // the cover art and the volume column starting 22px down from the top edge
    // for the sake of a label that only ever described the track. It now lives
    // inside the spectrum's own column (`specCol`), where it labels the one
    // thing it is next to, and the 22px it cost went to the artwork — which is
    // why this constant is 82 (60 + the 16px line + its 6px gap) rather than 60.
    // Keeping the sum identical is deliberate: `implicitHeight` and
    // `naturalRest` are unchanged, so the popup's height, the tile's reported
    // `wants` and the queue drawer's arithmetic all stay exactly where they were.
    readonly property int naturalArt: 82

    // The drawer's own padding, above the first queue row AND below the last.
    // Before it there was 10px above the drawer and nothing below: the last
    // row's bottom edge WAS the handle's top edge, measured gap=0, which is why
    // the toggle was reported as untouchable without hitting the last track.
    //
    // Half of it is paid for by the gap it replaces (10 above became 6 above and
    // 6 below), but only half — the separation does cost queue: measured, the
    // list went from 98px to 87px, so the drawer shows ~5.5 rows where it showed
    // ~6.1. That is the honest price of the margin and it is taken from the
    // drawer's own padding, NOT from `DockGrid`'s row allocation, which is
    // already down to three rows to guarantee the forecast its miniature graph.
    // Do not buy it back by shrinking the artwork: that block is size-invariant
    // by request (see `restSlack`).
    readonly property int drawerPad: 6

    implicitWidth: 300
    // The open drawer's 90 is a CONSTANT, not `queueH`: queueH is derived from
    // the item's height, and feeding it back into implicitHeight — which is what
    // the popup takes its height FROM — is a binding loop.
    implicitHeight: pad + drawerPad + naturalArt + 6 + bottom.height
                    + handle.height + (Media.queueOpen ? 90 : 0)

    // artwork + spectrum, from the widget's top edge down to the transport row
    Row {
        id: mid
        anchors {
            top: parent.top; topMargin: root.pad
            bottom: bottom.top; bottomMargin: 6
            horizontalCenter: parent.horizontalCenter
        }
        width: root.inner
        spacing: 8

        // Vertical output volume, left of the cover. Same value and the same
        // absolute setter the bar's VU meter drags (SysInfo.setVolume), so the
        // two never disagree. Click or drag anywhere in the column to set it;
        // the wheel steps it.
        Item {
            id: vol
            width: 12
            height: mid.height

            readonly property real frac: SysInfo.volume < 0 ? 0 : SysInfo.volume / 100

            Rectangle {
                id: volFrame
                anchors.fill: parent
                color: Theme.bgAlt
                border.width: Theme.ctrlBorder
                border.color: Theme.border
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: volFrame.border.width }
                height: Math.round((parent.height - 2 * volFrame.border.width) * vol.frac)
                color: SysInfo.muted ? Theme.textDim : Theme.accent
            }
            // level line, so the exact setting is readable even at a glance
            Rectangle {
                anchors { left: parent.left; right: parent.right }
                y: Math.max(0, Math.min(parent.height - 1,
                       Math.round((parent.height - 1) * (1 - vol.frac))))
                height: 1
                color: Theme.text
            }

            MouseArea {
                anchors { fill: parent; leftMargin: -3; rightMargin: -3 }
                acceptedButtons: Qt.LeftButton
                function setAt(y) {
                    SysInfo.setVolume(100 * (1 - Math.max(0, Math.min(1, y / vol.height))));
                }
                onPressed: (mouse) => setAt(mouse.y)
                onPositionChanged: (mouse) => { if (pressed) setAt(mouse.y); }
                // Notch-based on purpose (a discrete control), but a notch is a
                // fixed amount of scroll rather than one event — see
                // WheelNotch.qml.
                WheelNotch { id: notch }
                onWheel: (wheel) => {
                    const n = notch.steps(wheel);
                    if (n !== 0) SysInfo.adjustVolume(n * SettingsStore.d.volumeStep);
                }
            }
        }

        Item {
            id: artBox
            width: Math.min(mid.height, mid.width * 0.45)
            height: mid.height
            Rectangle {
                anchors.fill: parent
                color: Theme.bgAlt
                border.width: Theme.ctrlBorder
                border.color: Theme.border
            }
            Image {
                id: art
                anchors { fill: parent; margins: Theme.ctrlBorder }
                source: Media.dispArt
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                clip: true
                // Decoded at twice the natural size so a tall tile's larger
                // cover is still sharp; NOT bound to the item's width, which
                // changes on every frame of a panel drag.
                sourceSize.width: 240
                sourceSize.height: 240
                visible: status === Image.Ready
            }
            // CP437 note glyph placeholder when there's no cover art
            PixelText {
                anchors.centerIn: parent
                visible: !art.visible
                text: "\u266b"
                color: Theme.textDim
            }
        }

        // The spectrum, with the track line as its heading. The line is scoped
        // to this column rather than spanning the widget so the cover and the
        // volume bar reach the top edge; the spectrum is the one thing here with
        // nothing of its own to say, so it is the one that gets the label.
        Item {
            id: specCol
            width: mid.width - artBox.width - vol.width - 16
            height: mid.height

            // ONE line: track on the left, artist on the right. It keeps its
            // height when both are empty, so the spectrum below it does not move
            // when playback stops — which is the whole reason the strings are
            // empty rather than a "nothing playing" placeholder (see
            // Media.dispTitle).
            Item {
                id: trackLine
                anchors { top: parent.top; left: parent.left; right: parent.right }
                height: 16

                // Both elide, and in this column they nearly always will —
                // it is roughly half the width the line used to have. That is
                // safe with the pixel font: Qt drops to three ASCII periods on
                // its own when the family has no U+2026 (measured offscreen —
                // `TextMetrics.elidedText` came back "…tr..." with 0x2e 0x2e
                // 0x2e, pixel-identical to a hand-written "..."), so there is
                // no fallback-font ascent drop and nothing to hand-roll here.
                PixelText {
                    id: trackTitle
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    // Give the artist at most a third, and only what it actually
                    // needs, so a long title uses the rest instead of eliding
                    // against a gap.
                    width: parent.width - artistText.width - (artistText.width > 0 ? 8 : 0)
                    elide: Text.ElideRight
                    text: Media.dispTitle
                    color: Theme.text
                }
                // The natural width of the artist, measured by something that
                // has no width of its own. See `qartistNat` in the queue row
                // below for why an eliding Text may not be asked its own
                // `implicitWidth` when that answer is what sets its width.
                TextMetrics {
                    id: artistNat
                    font: artistText.font
                    text: artistText.text
                }
                PixelText {
                    id: artistText
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    width: Math.min(artistNat.advanceWidth, parent.width / 3)
                    horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                    text: Media.dispArtist
                    color: Theme.textDim
                }
            }

            // The spectrum is the EQ's tap-in: the whole grid is one click
            // band. A tap opens the overlay (which then covers the grid and
            // handles its own close), so while the overlay is down nothing here
            // swallows a click meant for elsewhere.
            Item {
                id: specZone
                anchors {
                    top: trackLine.bottom; topMargin: 4
                    left: parent.left; right: parent.right; bottom: parent.bottom
                }
                Spectrum {
                    anchors.fill: parent
                }
                MouseArea {
                    id: eqTrigger
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.eqOpen = true
                    // The spectrum is a DIRECT EQ surface too: wheeling over it
                    // steps the band under the cursor in place — no click to
                    // open the overlay first. Same 1 dB/notch discrete stepper
                    // and the same setBandGain write/persist path as the
                    // overlay (the overlay's own wheel still handles itself,
                    // sitting above this at z:1 while open).
                    WheelNotch { id: eqSpectrumNotch }
                    property int hoverBand: -1
                    function bandAt(x) {
                        return Media.eqBandAtXFrac(width > 0 ? (x / width) : 0, width);
                    }
                    onWheel: (wheel) => {
                        const n = eqSpectrumNotch.steps(wheel);
                        if (n === 0) return;
                        Media.eqWheelStep(wheel.x, width, n);
                    }
                    onPositionChanged: (m) => { hoverBand = bandAt(m.x); }
                    onExited: hoverBand = -1
                }
                // Direct-scroll readout: the hovered band's gain, no overlay
                // needed. Reads Media.eqBands (which eqWheelStep/setBandGain
                // write), so it tracks every notch live.
                PixelText {
                    id: eqHoverReadout
                    // `Media.eqBands` is a property `var` that arrives undefined
                    // for a beat during a panel reload — gate on it being an
                    // array so neither readout (visible nor text) dereferences
                    // undefined into the cumulative `qs log`.
                    readonly property var bands: Media.eqBands && Media.eqBands.length ? Media.eqBands : []
                    visible: !root.eqOpen && eqTrigger.hoverBand >= 0
                             && eqTrigger.hoverBand < bands.length
                    anchors { bottom: parent.bottom; bottomMargin: 2; horizontalCenter: parent.horizontalCenter }
                    text: Media.eqWriteLive
                        ? (eqTrigger.hoverBand >= 0 && eqTrigger.hoverBand < bands.length
                            ? root.fmtDb(bands[eqTrigger.hoverBand].gain) : "")
                        : "EQ read-only"
                    color: Media.eqWriteLive ? Theme.text : Theme.textDim
                }
                Equalizer {
                    visible: root.eqOpen
                    anchors.fill: parent
                    z: 1
                }
            }
        }
    }

    // Transport to the LEFT of the seekbar, on one line — the controls used to
    // sit on their own row under it, which cost a row for five buttons.
    //
    // Widths are tight at the narrow end of the panel's range (14% of screen),
    // so the buttons are compact and the total duration is dropped below
    // ~300px of inner width rather than squeezing the seekbar to nothing.
    Row {
        id: bottom
        anchors { bottom: queueBox.top; bottomMargin: root.drawerPad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 22
        spacing: 6

        readonly property real timeW: root.inner >= 300 ? 76 : 34

        Row {
            id: transport
            anchors.verticalCenter: parent.verticalCenter
            spacing: 5

            // The favourite heart sits where shuffle used to (the row's left
            // edge) and shuffle moved to the RIGHT of repeat — the two-change
            // order this row was asked for. A real red heart: lit Theme.crit
            // while the current track is favourited, dim otherwise, disabled
            // until the player is up with a current track (Media.canFav).
            MediaButton {
                kind: "fav"
                heart: true
                active: Media.canFav
                toggled: Media.fav
                onClicked: Media.toggleFav()
            }
            MediaButton {
                kind: "prev"
                active: Media.hasPlayer && Media.player.canGoPrevious
                onClicked: Media.player.previous()
            }
            MediaButton {
                kind: Media.playing ? "pause" : "play"
                active: Media.hasPlayer && (Media.player.canPlay || Media.player.canPause)
                onClicked: Media.player.togglePlaying()
            }
            MediaButton {
                kind: "next"
                active: Media.hasPlayer && Media.player.canGoNext
                onClicked: Media.player.next()
            }
            MediaButton {
                kind: "repeat"
                active: Media.canRepeat
                toggled: Media.repeatMode !== 0
                // repeat-one gets its own mark, repeat-all (and off) keep the
                // `o` that also serves the all-loop, per DESIGN.md §12.1
                glyphOverride: Media.repeatMode === 1 ? "1" : "o"
                onClicked: Media.cycleRepeat()
            }
            MediaButton {
                kind: "shuffle"
                active: Media.hasPlayer && Media.player.shuffleSupported
                toggled: Media.hasPlayer && Media.player.shuffle
                onClicked: Media.player.shuffle = !Media.player.shuffle
            }
        }

        Item {
            id: seek
            width: bottom.width - transport.width - bottom.timeW - bottom.spacing * 2
            height: parent.height
            anchors.verticalCenter: parent.verticalCenter

            readonly property bool seekable: Media.hasPlayer && Media.player.canSeek
                && Media.player.lengthSupported && Media.player.length > 0
            // driven by the DISPLAY position/length, not the live player's, so
            // the fill holds its place through the MPRIS reconnect instead of
            // collapsing to zero and springing back
            readonly property real frac: Media.dispLen > 0
                ? Math.max(0, Math.min(1, Media.dispPos / Media.dispLen)) : 0

            // One wheel detent moves the seek by 5% of the track. Taken from
            // hyprvtb's titlebar playbar (VTB_PLAYBAR_SCROLL, ../hyprvtb/
            // vtbDeco.cpp) to the number — the same gesture on the same control
            // in the other codebase that draws one, so scrubbing a titlebar and
            // scrubbing this bar cost the same number of notches. Its finding
            // that 3% is too timid to skim with is not worth re-deriving here.
            //
            // A FRACTION of the track, never a count of SECONDS: this widget
            // plays 90-second interludes and hour-long mixes, and any constant
            // in seconds is either too coarse to land inside the first or too
            // fine to cross the second. A percentage crosses either in the same
            // twenty notches.
            readonly property real wheelFrac: 0.05
            // Under this much movement there is nothing to show and nothing
            // worth putting on the bus; also the "has the player caught up"
            // test below. ~one pixel of a 250px track.
            readonly property real echoEps: 0.004

            // What the bar SHOWS: the seek we last asked for, until the
            // player's own position catches up (or `echo` gives up on it).
            // Both halves are load-bearing, and both are vtbDeco's playbarFrac
            // reasoning one file over:
            //  * the fill moves on the notch, not one MPRIS position sample
            //    later — Media re-emits at 200-500ms, which is long enough to
            //    read as the bar ignoring you;
            //  * the NEXT notch accumulates onto it. Without that, every event
            //    of a burst re-derives its step from a stale position, so three
            //    fast notches move the song by one. That is the actual bug this
            //    property exists for, not the redraw.
            // It is BOUNDED on purpose: a source that reports canSeek and then
            // ignores SetPosition (or clamps to a chapter) must not be able to
            // leave a lie on the bar — after `echo` the fill snaps back to
            // whatever the player really did. Same 1500ms/0.004 as the plugin.
            property real pending: -1
            readonly property real shownFrac: pending >= 0 ? pending : frac
            onFracChanged: if (pending >= 0 && Math.abs(frac - pending) <= echoEps) {
                pending = -1; echo.stop();
            }
            Timer { id: echo; interval: 1500; onTriggered: seek.pending = -1 }

            Rectangle { // track
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 6
                color: Theme.bgAlt
                border.width: Theme.ctrlBorder
                border.color: Theme.border
                Rectangle { // fill
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: parent.border.width }
                    width: Math.round((parent.width - 2 * parent.border.width) * seek.shownFrac)
                    color: Theme.accent
                }
            }

            function seekFrac(f) {
                if (!seek.seekable) return;
                var t = Math.max(0, Math.min(1, f));
                if (seek.pending >= 0 && Math.abs(t - seek.pending) < seek.echoEps) return;
                seek.pending = t;
                echo.restart();
                Media.player.position = t * Media.player.length;
            }
            function seekTo(x) { seek.seekFrac(x / width); }
            MouseArea {
                anchors { fill: parent; topMargin: -4; bottomMargin: -4 }
                // The wheel rides the SAME gate as the click, deliberately: a
                // disabled MouseArea takes no wheel either, so on a source with
                // no SetPosition the bar keeps its arrow cursor, does nothing,
                // and the notch falls through to whatever is under the widget.
                // Same rule the lyrics list already follows a few hundred lines
                // down (a click-to-seek MouseArea only where canSeek, plain
                // text otherwise) — one gate, so there is no state where the
                // bar takes a drag but silently eats a scroll, or the reverse.
                // The fill itself is NOT dimmed when unseekable: it is a
                // READING, and it is still true — dimming it would say the
                // position is unavailable rather than that the control is.
                enabled: seek.seekable
                cursorShape: seek.seekable ? Qt.PointingHandCursor : Qt.ArrowCursor
                onPressed: (mouse) => seek.seekTo(mouse.x)
                onPositionChanged: (mouse) => { if (pressed) seek.seekTo(mouse.x); }
                // WheelNotch, never a sign test (see WheelNotch.qml): a
                // trackpad is ~125Hz of sub-pixel deltas and a sign-only
                // handler would fire a full 5% per event — the exact bug
                // vtbDeco.cpp had to fix in the titlebar copy, where one
                // two-finger flick threw the song forward by minutes. It banks
                // the sub-detent remainder, so slow careful scrubbing still
                // moves, and clamps a burst to maxSteps so a flick cannot stack
                // a fan of SetPosition calls. That clamp IS the debounce — a
                // separate timer would either drop the notch you ended on or
                // lag the fill behind the wheel.
                // (`seekNotch`, not `notch`: ids are scoped to the whole FILE,
                // and the volume column above already took that one.)
                WheelNotch { id: seekNotch }
                onWheel: (wheel) => {
                    var n = seekNotch.steps(wheel);
                    if (n !== 0)
                        seek.seekFrac(seek.shownFrac + n * seek.wheelFrac);
                }
            }
        }

        PixelText {
            width: bottom.timeW
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            text: root.inner >= 300
                ? Media.fmtTime(Media.dispPos) + "/" + Media.fmtTime(Media.dispLen)
                : Media.fmtTime(Media.dispPos)
            color: Theme.textDim
        }
    }

    // ---- the play queue drawer -------------------------------------------
    // The player app serves its own queue over a socket (Media.queue); this is
    // the part of it you can see and click. It slides DOWN out of the bottom of
    // the widget, and the rows it needs come off the forecast tile below, which
    // condenses to its current-conditions line — see DockGrid's `queueRows` and
    // WeatherContent's `condensed`.
    //
    // The drawer takes the height the grid handed over (everything past the
    // widget's natural size) rather than a fixed pixel count, so it is exactly
    // as tall as the rows it was given and the artwork above it goes back to its
    // natural size instead of being squeezed by a guess. A floor of 60 keeps it
    // usable in the popup copy, which has no extra rows to give.
    // pad above the artwork row, drawerPad below the transport row — the two
    // vertical margins the layout below actually uses. It must stay EXACTLY the
    // non-drawer height or the artwork stops being size-invariant.
    readonly property real naturalRest:
        pad + drawerPad + naturalArt + 6 + bottom.height + handle.height
    // EXACTLY the height past the widget's natural size, with NO floor and NO
    // animation of its own. Both were wrong, and together they are why the cover
    // art visibly ballooned before the queue arrived.
    //
    // The artwork row (`mid`) is whatever is left over — root.height minus this
    // drawer and the fixed blocks — so `queueH == height - naturalRest` is the
    // one identity that keeps it at `naturalArt` for EVERY frame of the slide.
    // The tile's own height is already gliding (DockTile's Behavior); a second
    // Behavior here was an animation chasing an animating target, so it retargets
    // every frame and permanently trails. Measured on the open: the tile went
    // 217->270px while queueBox was still stuck at 25px, and the artwork row
    // absorbed the whole difference — 111px, 126, 139, 148, 154, 159, 162, 164 —
    // before snapping back to 60 once the lagging drawer finally landed.
    // The 60px floor did the same thing in the other direction at the start of
    // the motion. It is not needed: the popup copy's implicitHeight already adds
    // a constant 90 for the open state, so there is always something to show.
    // …and it tracks `drawerOut`, not `Media.queueOpen`, which is the same flag
    // held true for one animation on the way DOWN. The flag flips in one frame
    // while the tile takes a full slide (`ViewMode.slideMs`) to shed its rows,
    // so keying the drawer straight
    // off it collapsed the drawer instantly and handed the artwork the whole
    // 124px the tile had not given back yet — measured 60 -> 162px, then
    // shrinking. Holding it lets the drawer ride the tile down, and all that is
    // left at the end is the tile's resting slack (`qs ipc call live tiles`,
    // 7px here), which the artwork picks up in one imperceptible step.
    //
    // A `Behavior on height` gated `enabled: !Media.queueOpen` was tried first
    // and is NOT reliable: both bindings depend on the same flag, and for the
    // dock copy the height was written before `enabled` had been re-evaluated,
    // so the animation was skipped. Measured, not assumed — the popup copy of
    // the same component animated and the tile did not.
    // A CONSTANT initialiser, seeded in Component.onCompleted. Written as
    // `property bool drawerOut: Media.queueOpen` it is a binding, and a binding
    // that has never been overwritten yet wins the first close outright — so a
    // panel reloaded with the drawer already out would balloon the artwork
    // exactly once, on the next close, and behave from then on.
    property bool drawerOut: false

    // The tile's height above the widget's NATURAL size while the drawer is in.
    // The drawer gives back exactly the rows the grid added and no more, so the
    // artwork row — which is the leftover — is the same size open and closed.
    //
    // Without it the drawer took everything above `naturalRest`, including the
    // slack the tile already had (`qs ipc call live tiles` reports it: 7px
    // here, and a whole row on a taller grid). That slack belongs to the
    // artwork when the drawer is in, so the cover measured 65x65 closed and
    // 60x60 open — and because `artBox.width` follows `mid.height`, the cover
    // changed in BOTH dimensions and the spectrum's left edge moved with it.
    // The entire top of the widget visibly reflowed around a queue that is
    // supposed to open underneath it.
    //
    // It is sampled, not derived, because it is only knowable while the drawer
    // is in — and the sample has to be taken on `drawerOut` as well as on
    // height, since the tile has finished gliding by the time the close hold
    // expires and no further height change is coming.
    property real restSlack: 0
    // Both flags, and `Media.queueOpen` is the load-bearing half. On a reload
    // with the drawer already out, the tile is laid out at its OPEN height
    // before this component has decided that the drawer is out — `drawerOut` is
    // seeded from a setting that arrives at the end of the load pass — so a
    // sample taken on `!drawerOut` alone recorded the open slack (measured: 98px
    // instead of 5) and the drawer then computed a height of zero for the rest
    // of the session. `Media.queueOpen` is already true at that point.
    function noteRestSlack() {
        if (!drawerOut && !Media.queueOpen)
            restSlack = Math.max(0, height - naturalRest);
    }
    onHeightChanged: noteRestSlack()
    onDrawerOutChanged: noteRestSlack()

    // The dock tile's height with NO queue rows (its closed configuration), so
    // the drawer can be sized to exactly the rows the grid handed over. That
    // makes the artwork row above it its closed size on every frame and in
    // EVERY state — including a panel that loads with the drawer already out,
    // which the sampled `restSlack` above can never know: it had only ever seen
    // the open height, so it sat at 0 and the cover rendered at its natural,
    // smaller size until the queue was toggled once. The grid is the one thing
    // that always knows the closed height, so it supplies it. The popup has no
    // grid, so `gridClosedH` stays -1 there and it keeps the `restSlack` path
    // (a flat 90, its artwork being size-invariant already).
    property real gridClosedH: -1
    readonly property real queueH: drawerOut
        ? (root.gridClosedH >= 0
            ? Math.max(0, root.height - root.gridClosedH)
            : Math.max(0, root.height - naturalRest - restSlack)) : 0

    // The hold must OUTLAST the tile's glide, which is the drawer's only actual
    // animation — so it is derived from `ViewMode.slideMs` plus a frame's margin,
    // never a literal. It was 220 against a 200ms glide; when the glide moved to
    // the desktop's canonical 260 a literal here would have released the drawer
    // 40ms early and handed the artwork the rows the tile had not given back yet
    // — the exact ballooning this hold exists to prevent.
    Timer {
        id: closeHold
        interval: ViewMode.ms(ViewMode.slideMs + 20)
        onTriggered: root.drawerOut = false
    }
    // Re-centre the playing track once the drawer's glide settles, so it sits
    // in the middle the moment you open it too — the advance-time centring on
    // the list above only fires when the track changes, not on opening. The
    // glide is the drawer's only real animation, so this must outlast it the
    // same way closeHold does.
    Timer {
        id: centerOnOpen
        interval: ViewMode.ms(ViewMode.slideMs + 20)
        onTriggered: queueList.positionViewAtIndex(Media.queueIndex, ListView.Center)
    }
    Connections {
        target: Media
        function onQueueOpenChanged() {
            if (Media.queueOpen) { closeHold.stop(); root.drawerOut = true; centerOnOpen.restart(); }
            else closeHold.restart();
        }
    }

    // ---- the lyrics column, inside the drawer -----------------------------
    // When the playing track has words, the right-hand side of the queue
    // becomes the same lyrics box the player app draws in its now-playing view:
    // centred lines, the current one lit and the rest dimmed, clicking one seeks
    // there. It takes the space the ARTIST column was using, and the durations
    // move left to sit against its divider — so the queue keeps its two most
    // useful columns (what is next, and how long) and gives up the one the
    // header line above already names for the current track.
    //
    // It is a deliberate PARALLEL implementation of `apps/player/qml/
    // LyricsView.qml`, not a shared component: that tree is plain Qt QML and
    // this one is Quickshell's, and the panel cannot import `apps/qmlcommon`.
    // Same rule as `PixelText` and the `Kinetic*` types — retune both or the
    // desktop stops feeling like one thing. What is deliberately NOT copied is
    // that pane's `lyrics · <source>` header (docs/DESIGN.md 5.4 — the content
    // identifies itself, and a header would cost a line out of five) and its
    // "mark instrumental" control, which needs a library the panel does not
    // have.
    //
    // NO height of any kind is involved: the column lives entirely inside the
    // drawer the grid already handed over, so `naturalRest`, `implicitHeight`
    // and the tile's reported `wants` are untouched and the weather tile below
    // does not move.
    // `=== true`, deliberately. `Media` coerces at the source (see its `!!`), so
    // this is not defending against a malformed payload — it is defending
    // against a Media.qml that does not have the property yet. A rebuild swaps
    // the store symlinks file by file, so for one reload the panel can run this
    // file against the PREVIOUS Media.qml; `undefined` assigned to a `bool` is a
    // warning per evaluation, on three bindings, and the drawer would be the
    // only thing in the log. Observed once, live.
    readonly property bool showLyrics: Media.hasLyrics === true
    // A FRACTION of the drawer, not a pixel budget standing in for a character
    // count (docs/DESIGN.md 2.7): the panel is 14-33% of the screen and the font size
    // is a user setting, so the only honest split here is a proportional one.
    // 0.42 is the artist column's old third plus the duration column that now
    // sits inside the queue's own width.
    readonly property int lyricsGap: 6       // either side of the divider
    readonly property real lyricsW: showLyrics
        ? Math.round(Math.max(0, queueBox.width - pad * 2) * 0.42) : 0
    // A scroll of your own outranks the follow for 3s, exactly as in the
    // player's pane: the follow jumps the view at every lyric boundary, which
    // lands mid-gesture if you are reading ahead.
    property real lyricScrollMs: 0

    Item {
        id: queueBox
        anchors { bottom: handle.top; left: parent.left; right: parent.right }
        height: root.queueH
        clip: true

        KineticListView {
            id: queueList
            anchors {
                fill: parent
                leftMargin: root.pad
                rightMargin: root.pad + (root.showLyrics
                    ? root.lyricsW + root.lyricsGap * 2 + 1 : 0)
                // Clamped, so a closed drawer (height 0) does not hand the
                // list a NEGATIVE height on its way down.
                bottomMargin: Math.min(root.drawerPad, queueBox.height)
            }
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: Media.queue
            // Keep the playing track CENTRED as it advances, as the lyrics
            // column does — the tracks that played sit above it, what is next
            // below, so the drawer reads as a position in the queue rather
            // than a tail of one.
            currentIndex: Media.queueIndex
            highlightFollowsCurrentItem: true
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Center)

            delegate: Item {
                id: qrow
                required property var modelData
                required property int index
                width: queueList.width
                height: 16

                readonly property bool isCurrent: index === Media.queueIndex

                Rectangle {
                    anchors.fill: parent
                    color: qrow.isCurrent ? Theme.highlight
                         : (qma.containsMouse ? Theme.bgAlt : "transparent")
                }
                PixelText {
                    id: qnum
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    width: 22
                    // The playing row is marked, not numbered: its number is the
                    // one thing about it you already know.
                    text: qrow.isCurrent ? ">" : (qrow.index + 1)
                    color: qrow.isCurrent ? Theme.accent : Theme.textDim
                }
                PixelText {
                    id: qdur
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    text: Media.fmtTime(qrow.modelData.dur || 0)
                    color: Theme.textDim
                }
                // The artist column is as wide as its text, capped at a third of
                // the row — but that natural width may NOT be read off the item
                // itself. A `Text` with `elide` lays out against the width it has
                // been given, and until something has asked it for its implicit
                // width it publishes the ELIDED width as `implicitWidth`; so
                // `width: Math.min(implicitWidth, …)` is width defined in terms
                // of width, and whichever of the two evaluates first at delegate
                // creation decides whether it converges or spins. It spun:
                // 27 `Binding loop detected for property "width"` in one panel
                // generation, one per realized row, invisible on screen because
                // the loop settles at a width that merely looks a little short.
                // Same class as the zero-size popup in AGENTS.md — an implicit
                // size must be computed only from things that do not follow the
                // item's own size. `TextMetrics` has no geometry at all, so it
                // answers the same question (`advanceWidth` == the unelided
                // `implicitWidth`, measured) with nothing to feed back.
                TextMetrics {
                    id: qartistNat
                    font: qartist.font
                    text: qartist.text
                }
                PixelText {
                    id: qartist
                    anchors {
                        right: qdur.left
                        // Collapsed to nothing, margin included, when the lyrics
                        // column has taken this space — otherwise the title
                        // would stop 8px short of a column that is not there.
                        rightMargin: root.showLyrics ? 0 : 8
                        verticalCenter: parent.verticalCenter
                    }
                    visible: !root.showLyrics
                    width: root.showLyrics ? 0
                         : Math.min(qartistNat.advanceWidth, parent.width / 3)
                    horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                    text: qrow.modelData.artist || ""
                    // Rows in a script the pixel font lacks render in Unifont
                    // (fits the pixel line box) instead of the overflowing Noto
                    // fallback — see the `_noPixelRe`/`needsUnifont` note above.
                    font.family: root.needsUnifont(qrow.modelData.artist) ? "Unifont" : Theme.font
                    color: Theme.textDim
                }
                PixelText {
                    anchors {
                        left: qnum.right; right: qartist.left; rightMargin: 8
                        verticalCenter: parent.verticalCenter
                    }
                    elide: Text.ElideRight
                    text: qrow.modelData.title || ""
                    font.family: root.needsUnifont(qrow.modelData.title) ? "Unifont" : Theme.font
                    color: qrow.isCurrent ? Theme.accent : Theme.text
                }
                MouseArea {
                    id: qma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // Click a row to play it. GOTO goes back down the same
                    // socket the queue arrived on; the player answers with a new
                    // snapshot, so the highlight moves because the PLAYER moved,
                    // never because the panel assumed it would.
                    onClicked: Media.playIndex(qrow.index)
                }
            }
        }

        // Centred on the LIST, not on the drawer: with the lyrics column out the
        // drawer's centre is under it, and the label would read half-covered.
        PixelText {
            anchors.centerIn: queueList
            visible: Media.queue.length === 0
            text: Media.queueAvailable ? "queue is empty" : "player not running"
            color: Theme.textDim
        }

        // The divider, and the column. Both collapse to nothing when the track
        // has no words — the common case, in which the drawer is byte-for-byte
        // what it was before this existed.
        Rectangle {
            id: lyricSep
            anchors {
                top: parent.top; bottom: parent.bottom
                right: lyricsCol.left; rightMargin: root.lyricsGap
            }
            width: 1
            visible: root.showLyrics
            color: Theme.border
        }

        Item {
            id: lyricsCol
            anchors {
                top: parent.top; bottom: parent.bottom
                right: parent.right; rightMargin: root.pad
            }
            width: root.lyricsW
            visible: root.showLyrics
            clip: true

            // ---- synced: one row per timed line, the current one lit --------
            KineticListView {
                id: lyricsList
                anchors.fill: parent
                visible: Media.lyricsSynced === true
                clip: true
                // Guarded on `Media.lyrics` ITSELF, not on `lyricsSynced`. The
                // two are separate bindings over the same push and QML gives no
                // ordering between them, so on the frame a track loses its
                // lyrics this can be re-evaluated while `lyricsSynced` is still
                // true and `lyrics` is already null — measured as
                // "TypeError: Value is null and could not be converted to an
                // object" on the transition back to a track with none.
                model: (Media.lyricsSynced === true && Media.lyrics)
                       ? Media.lyrics.lines : []
                // Any motion the FOLLOW did not cause is the user driving.
                // `positionViewAtIndex` is an instant jump and never sets
                // `moving`, so this cannot suppress itself the way binding to
                // `contentY` would.
                onMovingChanged: if (moving) root.lyricScrollMs = Date.now()

                delegate: Item {
                    id: lrow
                    required property var modelData
                    required property int index
                    width: lyricsList.width
                    // A wrapped line is N font cells tall and nothing more —
                    // PixelText pins its line height to the cell (docs/DESIGN.md
                    // 2.1), so this is kitty-tight at any font size.
                    height: Math.max(Theme.lineHeight, lineText.implicitHeight)

                    PixelText {
                        id: lineText
                        width: parent.width
                        anchors.verticalCenter: parent.verticalCenter
                        text: lrow.modelData.line
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                        color: lrow.index === Media.lyricIndex ? Theme.text
                                                               : Theme.textDim
                    }
                    // Click a line to seek to it, like the player's pane. Drawn
                    // only when it would actually do something (docs/DESIGN.md 10) —
                    // a source with no SetPosition gets plain text.
                    MouseArea {
                        anchors.fill: parent
                        enabled: Media.hasPlayer && Media.player.canSeek
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Media.player.position = lrow.modelData.t
                    }
                }
            }

            // ---- plain: no timings, so nothing to follow -------------------
            KineticFlickable {
                id: plainLyrics
                anchors.fill: parent
                visible: Media.hasLyrics === true && Media.lyricsSynced !== true
                clip: true
                contentHeight: plainText.implicitHeight

                PixelText {
                    id: plainText
                    // NOT parent.width — parent is the Flickable's contentItem,
                    // whose width stays 0 when only contentHeight is set.
                    width: plainLyrics.width
                    // `Media.lyrics`, not `Media.hasLyrics` — same ordering trap
                    // as the model above.
                    text: Media.lyrics ? Media.lyrics.text : ""
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: Theme.textDim
                }
            }

            Connections {
                target: Media
                function onLyricIndexChanged() {
                    if (Media.lyricIndex >= 0
                        && Date.now() - root.lyricScrollMs > 3000)
                        lyricsList.positionViewAtIndex(Media.lyricIndex,
                                                       ListView.Center);
                }
            }
        }
    }

    // ---- the handle: the widget's bottom edge -----------------------------
    // A strip across the very bottom that lights up under the pointer and says
    // which way it will go. It is the affordance AND the close button: with the
    // drawer open it is the bottom edge of the drawer, which is where the user
    // reaches for it.
    Item {
        id: handle
        anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
        height: 14

        Rectangle {
            anchors.fill: parent
            color: hma.containsMouse ? Theme.bgAlt : "transparent"
            // A hairline that only appears on hover: the widget already has a
            // tile border, and a second permanent line across the bottom would
            // read as a division rather than a control.
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1
                color: Theme.border
                visible: hma.containsMouse || Media.queueOpen
            }
        }
        PixelText {
            id: chevron
            // ONE glyph, flipped — never "^" for the open state. More Perfect
            // DOS VGA has no arrow or triangle at all (checked against the
            // cmap: U+2191/2193, U+25B2/25BC/25B4/25BE are all absent), so the
            // pair has to come out of ASCII, and "^" is not "v" upside down in
            // this font: measured from the glyf table, "v" is 1792 units tall
            // sitting on the baseline while "^" is 1024 units hard against the
            // ascender. Rendered into this 14px strip that put the caret's ink
            // on rows 0-2 — on top of the hover hairline and effectively
            // outside the button — against rows 4-10 for the "v". So the open
            // state is the SAME "v", mirrored about its own centre: identical
            // shape, identical band, and it reads as one control.
            //
            // The flip is vertical only and the item's y is ROUNDED, which is
            // what keeps NativeRendering crisp: an integer origin maps pixel
            // centres onto pixel centres, so the mirrored glyph rasterises to
            // pure Theme colour with no antialiased edge (verified offscreen —
            // rows 4-10, one shade). The rounding also drops a stray pixel the
            // old `anchors.centerIn` produced from its half-pixel y (15px of
            // line in a 14px strip).
            text: "v"
            x: Math.round((parent.width - implicitWidth) / 2)
            y: Math.round((parent.height - implicitHeight) / 2)
            transform: Scale {
                yScale: Media.queueOpen ? -1 : 1
                origin.y: chevron.implicitHeight / 2
            }
            // Dim until hovered, so the strip is a hint rather than a permanent
            // chevron.
            color: hma.containsMouse ? Theme.accent : Theme.textDim
            opacity: hma.containsMouse || Media.queueOpen ? 1 : 0.55
        }
        MouseArea {
            id: hma
            // The TARGET is bigger than the strip. Growing the drawn chrome
            // instead would cost a queue row for every pixel and put a heavier
            // line across the bottom of the widget; a negative margin costs
            // nothing at all.
            //
            // `drawerPad - 1`, not `drawerPad`: the extension has to stop one
            // pixel SHORT of the gap it grows into, or it starts swallowing
            // clicks meant for something else. Open, the pixel keeps it clear of
            // the last queue row's own MouseArea (which fills its 16px row and
            // plays that track). Closed there is no drawer, so it grows into the
            // gap under the transport row instead — where the 24px buttons
            // overhang their 22px row by a pixel at each end.
            anchors.fill: parent
            anchors.topMargin: -(root.drawerPad - 1)
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: Media.setQueueOpen(!Media.queueOpen)
        }
        Tooltip {
            target: handle
            show: hma.containsMouse
            text: Media.queueOpen ? "hide the queue" : "show the play queue"
        }
    }
}

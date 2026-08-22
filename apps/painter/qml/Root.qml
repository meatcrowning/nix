import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// Painter's whole surface, as an ITEM rather than a Window — because it has two
// roofs, and only one of them is a QML window (docs/DESIGN.md §7.6):
//
//   Hyprland session:  Main.qml wraps this in a `Window`; chrome is the hyprvtb
//                      titlebar column (the Titlebar block at the bottom).
//   Plasma session:    main.py hosts this file directly in a `QQuickWidget`
//                      inside a real `QMainWindow` (`pylib/kdeshell.py`), so the
//                      menubar, toolbar and statusbar are genuine KDE widgets
//                      painted by the system style, and the styled window
//                      background shows through behind everything here that does
//                      not paint itself.
//
// Two panes: the controls on the left, results on the right.
Item {
    id: root

    // The desktop's one slide duration + curve (docs/DESIGN.md 6.2).
    Motion { id: motion }

    // In a Plasma session, the KDE style's own window background, drawn behind
    // everything here so this content sits on the same surface the menubar and
    // toolbar do. Invisible and inert in the Hyprland session.
    StyledBackground { anchors.fill: parent }

    property int view: 0            // 0 = params, 1 = gallery
    // THE PARAMETERS COLUMN MAY NOT BE IN THIS WINDOW'S CONTENT AT ALL. Under
    // Plasma it is a real QDockWidget beside the central widget
    // (pylib/kdeshell.py `dock`), which is a second scene: this file must then
    // not build one of its own, the splitter has nothing to split, and the
    // parameters/gallery pane switch is meaningless because both are visible.
    // Set from main.py, false everywhere else.
    property bool paramsDocked: false
    property bool showSettings: false
    // The preview viewport above the history — off by default, remembered.
    property bool showPreview: false

    // THE OUTPUT PANE IS NOT A LUXURY OF WIDE WINDOWS. Both panes used to vanish
    // below 900px unless they were the selected view, so in the parameters view
    // on a narrower window the results pane was simply not there — resize the
    // window and your images disappeared, with nothing saying why. The split now
    // holds at every width: the controls take their share, the gallery takes the
    // rest and adapts its own cell size (GalleryView), down to a single column.
    // Only below `splitFloor`, where neither pane could be read, does it fall
    // back to one-at-a-time on the p/g buttons (docs/DESIGN.md §5.6).
    readonly property int splitFloor: 560
    readonly property bool split: !root.paramsDocked && root.width >= root.splitFloor

    // ...and WHERE the divider sits is yours, dragged and remembered. The
    // clamps are the same two minimums as before, so the handle cannot starve
    // either side: the controls stop reading below ~300px and the gallery below
    // ~200px. Same shape as filer's splitter.
    // THE RESULTS LEAD. The controls used to be on the left; they are on the
    // right now, so `paneLeadW` sizes the RESULTS pane and the two floors swap
    // with them — a gallery stops being readable at ~200px, the controls at
    // ~300px. A ratio saved before the swap is inverted once on restore, so the
    // divider comes back where it looked rather than mirrored.
    readonly property real splitDefault: 0.58
    property real splitRatio: splitDefault
    readonly property int splitterW: 4
    readonly property int minLead: 200      // results
    readonly property int minTrail: 300     // controls
    readonly property int paneLeadW: Math.max(minLead,
        Math.min(root.width - splitterW - minTrail,
                 Math.round((root.width - splitterW) * splitRatio)))

    // Chrome greys to the SAME tone the hyprvtb titlebar fades to when the
    // window loses focus, so painter reads as inactive in lock-step with its
    // own titlebar instead of staying brighter than the bar beside it — the
    // idiom filer uses (docs/DESIGN.md §3.1). Body text and values keep their own
    // colours; only the accented chrome follows.
    // §3.1.1's app-side fade is RETIRED — his board call, 2026-08-09: with
    // "dim unfocused" on, the native decoration:dim_inactive scrim is the ONE
    // dimming mechanism, and an app that also greys its own foreground reads
    // darker than a plain window. The window always renders its focused tones;
    // the compositor dims the whole surface. Re-arm by restoring `root.active`
    // here — the plumbing is all still wired.
    readonly property bool winActive: true
    readonly property color fgAccent: winActive ? Theme.accent : Theme.inactive

    // Live generation settings, seeded from the selected model's family.
    property var gen: ({
        positive: "", negative: "",
        steps: 20, cfg: 1.0, denoise: 1.0,
        sampler_name: "euler", scheduler: "simple",
        seed: 0, randomSeed: true, reuseSeed: false, batch_size: 1, count: 1,
        // The aspect is two integers the user types; `aspect` is the "w:h"
        // string they compose, which is what App.dims (registry.calc_dims)
        // parses. Width and height are DERIVED — never set by hand, so there is
        // one source of truth for the size and the header badge cannot disagree
        // with the graph.
        aspectW: 1, aspectH: 1, megapixels: 1.0, multiple: 64,
        width: 1024, height: 1024,
        // Video only (a `kind: video` family). `useInputImage` is the mode
        // switch: on, the dropped image is the first frame AND the thing that
        // decides the aspect, so only MP is left to choose; off, it is plain
        // text-to-video with painter's usual aspect + MP. The image itself is a
        // file path and lives on App, not in here.
        duration: 5.0, fps: 24.0, useInputImage: false, useLastFrame: false,
        // Edit only. The output size is the dropped image's, scaled: `editNoScale`
        // keeps its exact width and height, otherwise `editMegapixels` is the
        // pixel budget the image is scaled to (its aspect kept), the same MP
        // control the video path offers. See EditScalePanel.qml and
        // registry._build_edit.
        editNoScale: true, editMegapixels: 1.5,
        negpip: false, modelSampling: false,
        ms: ({ shift_start: 3.5, shift_end: 1.2, start_percent: 0.0,
               end_percent: 0.5, curve: "ease_in", outside_window: "hold",
               multiplier: 1.0 }),
        promptTransform: "none"
    })

    // MUTATING `gen` IN PLACE DOES NOTHING TO THE SCREEN. Every panel used to do
    // `var g = root.gen; g.x = v; root.gen = g` — and assigning a `property var`
    // the object it already holds emits NO change signal, so not one binding
    // re-evaluated. Measured, not guessed: the same edit through a fresh object
    // updates, through the same object does not. The values still reached
    // submit() (it reads `gen` at click time), which is why this looked like it
    // worked: what was broken was everything DISPLAYED from gen — the resolution
    // badge, the "= WxH" readout, a Spin showing a family's default, the seed box
    // grey-out, and the whole ModelSampling parameter block, which is bound to
    // `root.gen.modelSampling` and so never appeared when the toggle was flipped.
    //
    // So there is one way to change a setting, and it hands out a NEW object.
    function clone(o) {
        var c = {}
        for (var k in o) c[k] = o[k]
        return c
    }

    // set("steps", 30) — the only way a panel should write a setting.
    function set(key, value) {
        var g = clone(gen)
        g[key] = value
        gen = g
    }

    // ...and the same for the nested ModelSampling block, which needs both
    // levels copied or the inner object is shared with the old one.
    function setMs(key, value) {
        var g = clone(gen)
        g.ms = clone(gen.ms)
        g.ms[key] = value
        gen = g
    }

    // "3:2" -> [3, 2], and anything unparseable -> 1:1 rather than a NaN that
    // would propagate into the size and out into the graph.
    function parseAspect(s) {
        var m = String(s || "").split(":")
        var w = Math.round(parseFloat(m[0]))
        var h = Math.round(parseFloat(m[1]))
        if (!(w > 0) || !(h > 0)) return [1, 1]
        return [w, h]
    }

    // Which model's defaults `gen` currently reflects. A restored session sets
    // it to the model that was selected when it was saved, so the selection that
    // happens at startup does not immediately overwrite everything remembered.
    property string defaultsFor: ""

    // EACH PRESET KEEPS ITS OWN SETTINGS. The whole `gen` is remembered per
    // model name, so switching AWAY to another preset and back restores exactly
    // what was last set for it — resolution, prompts, sampler, toggles, the lot —
    // rather than resetting to the family default or bleeding one preset's values
    // into another. It used to be one shared `gen`: only a four-field sampling
    // subset survived a round-trip and everything else was reset (and shared
    // meanwhile). This map is PERSISTED (Prefs key `genByModel`, saved and
    // restored alongside `gen`), so a preset's settings also survive a relaunch.
    // LoRAs stay App-side (cleared per switch by selectModel) and the dropped
    // input image is deliberately one shared slot — neither lives in `gen`.
    property var genByModel: ({})

    // A deep-enough copy of the live `gen` to stash: `clone` is shallow, so the
    // nested `ms` block has to be copied too or a later setMs would reach into a
    // stashed preset's settings.
    function snapshotGen() {
        var out = clone(gen)
        out.ms = clone(gen.ms)
        return out
    }

    // Lay a remembered preset's settings over the current shape, so a key the
    // saved object predates (a new field) keeps its default instead of vanishing.
    function mergeGen(base, saved) {
        var g = clone(base)
        for (var k in saved) if (k !== "ms" && g[k] !== undefined) g[k] = saved[k]
        g.ms = clone(base.ms)
        if (saved.ms) for (var mk in saved.ms) if (g.ms[mk] !== undefined) g.ms[mk] = saved.ms[mk]
        return g
    }

    function applyDefaults() {
        if (App.selectedName === root.defaultsFor) return

        // A preset we already have settings for: restore them wholesale. This is
        // the round-trip case, and (via the persisted map) the relaunch case too.
        var saved = App.selectedName !== "" ? root.genByModel[App.selectedName] : undefined
        if (saved) {
            if (root.defaultsFor) root.genByModel[root.defaultsFor] = snapshotGen()
            root.defaultsFor = App.selectedName
            gen = mergeGen(gen, saved)
            recomputeDims()
            if (root.restored) saveSoon.restart()
            return
        }

        // First time on this preset: seed it from the family's defaults. The
        // modelDefaults() gate stays BEFORE defaultsFor is touched, so the startup
        // pass (no model loaded yet) leaves the restored session's defaultsFor
        // alone and does not overwrite what was just restored.
        var d = App.modelDefaults()
        if (!d || !d.steps) return
        if (root.defaultsFor) root.genByModel[root.defaultsFor] = snapshotGen()
        root.defaultsFor = App.selectedName
        var g = clone(gen)
        g.steps = d.steps
        // A video family has no CFG at all (BasicGuider takes none), so it
        // declares no default for it — keep what was there rather than writing
        // an undefined into the settings every time such a model is selected.
        if (d.cfg !== undefined) g.cfg = d.cfg
        g.denoise = d.denoise !== undefined ? d.denoise : 1.0
        if (d.duration !== undefined) g.duration = d.duration
        if (d.fps !== undefined) g.fps = d.fps
        g.sampler_name = d.sampler_name; g.scheduler = d.scheduler
        var a = parseAspect(d.aspect)
        g.aspectW = a[0]; g.aspectH = a[1]
        g.megapixels = d.megapixels; g.multiple = d.multiple
        g.negpip = d.toggles && d.toggles.negpip === true
        g.modelSampling = d.toggles && d.toggles.model_sampling === true
        if (d.model_sampling) {
            var m = clone(g.ms)
            for (var k in d.model_sampling) m[k] = d.model_sampling[k]
            g.ms = m
        }
        g.promptTransform = d.promptTransform
        var wh = App.dims(g.aspectW + ":" + g.aspectH, g.megapixels, g.multiple)
        g.width = wh.width; g.height = wh.height
        gen = g
        if (root.restored) saveSoon.restart()
    }

    // The ONE place width/height are computed. Every control that can change
    // the size (both aspect boxes, MP, and a family default landing) ends here,
    // so the header badge, the "= WxH" readout and what submit() sends are the
    // same three numbers by construction.
    function recomputeDims() {
        var g = clone(gen)
        var wh = App.dims(g.aspectW + ":" + g.aspectH, g.megapixels, g.multiple)
        g.width = wh.width; g.height = wh.height
        gen = g
    }

    function submit() {
        var g = gen
        // EDIT SENDS THE PROMPT AND THE SEED, and lets the family's edit block
        // supply the rest (steps, cfg, shift, the pixel budget). The controls
        // for those are not on screen in this mode, so sending `gen`'s values
        // would submit numbers he was never shown — the graph would run at
        // whatever the last image family left behind.
        if (App.isEdit) {
            App.generate({
                edit: true,
                positive: g.positive,
                editNoScale: g.editNoScale, editMegapixels: g.editMegapixels,
                seed: g.seed, randomSeed: g.randomSeed, reuseSeed: g.reuseSeed
            }, g.count)
            return
        }
        // A video job is a different set of controls, not a superset: one
        // prompt, a duration instead of a batch, no CFG and no patches. Sending
        // the image fields anyway would have painter claim settings the video
        // graph never reads.
        if (App.isVideo) {
            App.generate({
                positive: g.positive,
                steps: g.steps, denoise: g.denoise,
                sampler_name: g.sampler_name, scheduler: g.scheduler,
                seed: g.seed, randomSeed: g.randomSeed, reuseSeed: g.reuseSeed,
                duration: g.duration, fps: g.fps,
                megapixels: g.megapixels,
                width: g.width, height: g.height,
                use_input_image: g.useInputImage,
                use_last_frame: g.useLastFrame
            }, g.count)
            return
        }
        App.generate({
            positive: g.positive, negative: g.negative,
            steps: g.steps, cfg: g.cfg, denoise: g.denoise,
            sampler_name: g.sampler_name, scheduler: g.scheduler,
            seed: g.seed, randomSeed: g.randomSeed, reuseSeed: g.reuseSeed,
            batch_size: g.batch_size,
            width: g.width, height: g.height,
            toggles: ({ negpip: g.negpip, model_sampling: g.modelSampling }),
            model_sampling: g.ms
        }, g.count)
    }

    Connections {
        target: App
        function onModelChanged() {
            root.applyDefaults()
            // The LoRA chain the model landed with (startup restore only —
            // `selectModel` always clears the stack, so this is what puts it
            // back, once, for the remembered selection). A later switch in
            // the same session clears it same as before.
            if (!root.lorasRestored && App.selectedName === (Prefs.get("model") || "")) {
                root.lorasRestored = true
                try { App.restoreLoras(JSON.parse(Prefs.get("loras") || "[]")) }
                catch (e) { /* a corrupt list just leaves the stack empty */ }
            }
        }
        function onToast(msg, isError) { toast.show(msg, isError) }
    }

    // ---------------------------------------------------------------- panes

    // Explicit rects rather than a Row, because the divider between them is
    // DRAGGABLE and the two panes are sized from one ratio — the same shape as
    // filer's splitter (apps/filer/qml/Main.qml), including the 4px bar with a
    // ±3px grab margin and the accent-on-hover.
    // results, and the preview above them
    ResultsPane {
        id: results
        app: root
        x: 0
        // the Plasma menubar's height, 0 in the Hyprland session
        y: menuBar.height
        width: root.split ? root.paneLeadW : root.width
        height: parent.height - root.barH - menuBar.height
        visible: root.paramsDocked || root.split || root.view === 1
    }

    Rectangle {
        id: splitBar
        visible: root.split
        z: 10
        x: root.paneLeadW
        y: menuBar.height
        width: root.splitterW
        // Stops at the status bar: a handle drawn over it also GRABS over it,
        // so the last 26px of the divider swallowed clicks meant for the bar.
        height: parent.height - root.barH - menuBar.height
        color: splitDrag.pressed || splitDrag.containsMouse ? Theme.accent : Theme.border

        MouseArea {
            id: splitDrag
            anchors.fill: parent
            // a 4px divider is a 10px grab target, across the divider
            anchors.leftMargin: -3
            anchors.rightMargin: -3
            hoverEnabled: true
            cursorShape: Qt.SplitHCursor
            preventStealing: true
            onPositionChanged: function (m) {
                if (!pressed) return
                var p = mapToItem(root, m.x, m.y)
                root.splitRatio = Math.max(0, Math.min(1, p.x / Math.max(1, root.width)))
            }
            // Written on release, not on every pixel of the drag: a ratio is one
            // decision, not sixty file writes.
            onReleased: Prefs.set("splitRatio", root.splitRatio)
            // Double-click restores the default share, since a handle dragged
            // to an edge is otherwise hard to get back.
            onDoubleClicked: {
                root.splitRatio = root.splitDefault
                Prefs.set("splitRatio", root.splitRatio)
            }
        }
    }

    // controls, on the right — unless they are in a dock, in which case this
    // window has none and the Loader builds nothing.
    Loader {
        id: controls
        active: !root.paramsDocked
        x: root.split ? root.paneLeadW + root.splitterW : 0
        y: menuBar.height
        width: root.split ? Math.max(1, root.width - x) : root.width
        height: parent.height - menuBar.height
        visible: root.split || root.view === 0
        sourceComponent: ParamsPane {
            app: root
            // The QueueBar is drawn over the bottom of this column in the
            // Hyprland roof; under Plasma the status bar is the window's own
            // and takes no room from the content.
            bottomInset: root.barH
        }
    }

    // ------------------------------------------------------------- overlays

    // The status bar owns the bottom strip of the window; the splitter stops
    // above it (see splitBar) rather than crossing it, which put a drag target
    // on top of the generate button.
    // The status strip. Under Plasma it is a real QStatusBar on the QMainWindow
    // (pylib/kdeshell.py), fed by `statusLine`/`statusProgress` below, so this
    // one stands down and gives its 26px back to the content.
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    readonly property int barH: plasma ? 0 : 26

    // What that native status bar says. QueueBar is the Hyprland roof's richer
    // strip (node, rate, ETA, queue) and a KDE status bar is one line, so this
    // is the SUMMARY of the same state, not a second source of it.
    readonly property string statusLine: {
        var s = App.ready ? App.status : (App.status + " …")
        if (App.queue > 0) s += "  ·  queued " + App.queue
        return s
    }
    // -1 when nothing is running: a KDE status bar shows no progress bar at all
    // rather than an empty one (docs/DESIGN.md §10 — never draw a control that
    // says nothing).
    readonly property real statusProgress: App.busy ? App.progress : -1

    QueueBar {
        visible: !root.plasma
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.barH
    }

    // Not a centred modal: it slides out from the "st" titlebar cell that owns
    // it, the way player's and surfer's do (docs/DESIGN.md §7.4). It owns its own
    // visibility off `open` — assigning `visible` from here would override the
    // slide's binding.
    SettingsDrawer {
        id: settings
        anchors { top: menuBar.bottom; left: parent.left
                  right: parent.right; bottom: parent.bottom }
        open: root.showSettings
        onClosed: root.showSettings = false
    }

    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        width: Math.min(msg.implicitWidth + 24, root.width - 60)
        height: 30
        opacity: 0
        color: Theme.bgAlt
        radius: Theme.rounding
        border.color: error ? Theme.crit : Theme.border
        border.width: Theme.ctrlBorder
        property bool error: false

        function show(text, isError) {
            msg.text = text
            error = isError === true
            fade.restart()
        }

        PixelText {
            id: msg
            anchors.centerIn: parent
            width: parent.width - 20
            elide: Text.ElideRight
            color: parent.error ? Theme.crit : Theme.text
        }

        // The two FADES go through motion.ms() so they follow reduceMotion and
        // animSpeed like everything else (docs/DESIGN.md §6.2 — "never write a
        // duration literal into a widget"). They keep their own lengths rather
        // than taking slideMs: §6.2.1 lists a crossfade as a deliberate
        // non-participant, because opacity has no travel to read.
        //
        // The PAUSE deliberately does NOT scale. It is how long the message is
        // READABLE, not motion — and under reduceMotion `ms()` returns 0, which
        // would blink the toast out of existence the moment it appeared. That is
        // §10: a report the user cannot read is a report that did not happen.
        SequentialAnimation {
            id: fade
            NumberAnimation { target: toast; property: "opacity"; to: 1; duration: motion.ms(120) }
            PauseAnimation { duration: 3200 }
            NumberAnimation { target: toast; property: "opacity"; to: 0; duration: motion.ms(400) }
        }
    }

    // -------------------------------------------------------------- chrome

    // ONE TABLE OF VERBS, TWO CHROMES THAT READ DIFFERENT COLUMNS OF IT.
    //
    // `actions` is everything painter can be told to do. What each consumer
    // takes from a row:
    //
    //   hyprvtb titlebar   id, label, state, tip, bottom   — and ONLY the rows
    //                      marked `tb:`, because a titlebar column has six
    //                      cells, not a menubar's worth. `tbButtons` below is
    //                      that filter, and it is what `pushButtons()` sends.
    //   KDE menubar/       menu, menuText, icon, bar, shortcut, checkable,
    //   toolbar            group  (pylib/kdeshell.py) — every row, since a menu
    //                      IS the complete set.
    //
    // Everything the other side does not read is inert, which is what lets one
    // array serve both: vtbclient.py ignores unknown keys, and kdeshell never
    // sees `label`.
    //
    // Labels are lowercase ASCII, one or two characters, and the settings cell
    // is "st" — the same label player and surfer use for the same button
    // (docs/DESIGN.md §12.1: a function that already has a glyph keeps it in every
    // app). A menu row instead shows `menuText` or `tip`, in sentence case with
    // the desktop's own capitalisation, because it is a row of words.
    //
    // `state`: 0 normal, 1 lit/checked, 2 disabled. A row whose target does not
    // exist is DISABLED rather than absent, since a menu whose contents move
    // around is a menu you cannot learn (docs/DESIGN.md §10.1).
    //
    // `shortcut` is the KDE face's alone: the QML `Shortcut`s at the bottom of
    // this file stand down under Plasma so exactly one thing owns each key.
    // "@Name" takes the platform's standard sequence rather than a literal.
    readonly property var actions: root.paramsDocked
        ? root.allActions.filter((a) => a === "-" || (a.id !== "p" && a.id !== "g"))
        : root.allActions

    readonly property var allActions: [
        // ------------------------------------------------------------- file
        { id: "gen",  label: "gen",  tb: true, state: App.busy ? 2 : 0,
          tip: "Generate", menu: "file", icon: "media-playback-start",
          bar: true, shortcut: "Ctrl+Return" },
        { id: "stop", label: "x",    tb: true, state: App.busy ? 0 : 2,
          tip: "Cancel all", menu: "file", icon: "process-stop",
          bar: true, shortcut: "Ctrl+." },
        "-",
        { id: "open", tip: "Open in Viewer", menu: "file",
          icon: "document-open", state: root.selOne === "" ? 2 : 0 },
        { id: "folder", tip: "Open Output Folder", menu: "file",
          icon: "folder-open" },
        // ------------------------------------------------------------- edit
        // The gallery's right-click verbs, hoisted: the same three subsets of a
        // finished job (its words, its numbers, both) plus its prompt on the
        // clipboard. They act on the selected output, and there being no
        // selection is what greys them.
        { id: "injall",    tip: "Reuse All Settings", menu: "edit",
          icon: "edit-paste", state: root.selParams ? 0 : 2 },
        { id: "injprompt", tip: "Reuse Prompt", menu: "edit",
          state: root.selParams ? 0 : 2 },
        { id: "injparams", tip: "Reuse Parameters", menu: "edit",
          state: root.selParams ? 0 : 2 },
        "-",
        { id: "copyprompt", tip: "Copy Prompt", menu: "edit", icon: "edit-copy",
          state: root.selOne === "" ? 2 : 0 },
        { id: "clearprompt", tip: "Clear Prompt", menu: "edit",
          icon: "edit-clear", state: root.gen.positive === "" ? 2 : 0 },
        // ------------------------------------------------------------- view
        // Parameters and Gallery are a RADIO PAIR — Gwenview's Browse/View —
        // so `group` makes them exclusive in the menu and the toolbar instead
        // of two checkboxes that can both be off.
        { id: "p",    label: "p",    tb: true, state: root.view === 0 ? 1 : 0,
          tip: "Parameters", menu: "view", icon: "view-list-details",
          bar: true, checkable: true, group: "pane", shortcut: "Ctrl+1" },
        { id: "g",    label: "g",    tb: true, state: root.view === 1 ? 1 : 0,
          tip: "Gallery", menu: "view", icon: "view-list-icons",
          bar: true, checkable: true, group: "pane", shortcut: "Ctrl+2" },
        { id: "pv",   label: "pv",   tb: true, state: root.showPreview ? 1 : 0,
          tip: "Preview viewport", menu: "view", icon: "document-preview",
          bar: true, checkable: true, shortcut: "F7" },
        // ------------------------------------------------------------ tools
        { id: "rescan", tip: "Rescan Models", menu: "tools",
          icon: "view-refresh", shortcut: "Ctrl+R" },
        "-",
        { id: "backendstart", tip: "Start Backend", menu: "tools",
          icon: "system-run", state: App.backendRunning ? 2 : 0 },
        { id: "backendstop", tip: "Stop Backend", menu: "tools",
          icon: "process-stop", state: App.backendRunning ? 0 : 2 },
        { id: "unload", tip: "Unload Models", menu: "tools",
          icon: "edit-clear-history", state: App.backendRunning ? 0 : 2 },
        // --------------------------------------------------------- settings
        { id: "set",  label: "st",   tb: true, state: root.showSettings ? 1 : 0,
          tip: "Settings", bottom: true, menu: "settings",
          menuText: "Configure painter…", icon: "configure",
          shortcut: "@Preferences" }
    ]

    // The KDE menubar's menu order. `help` is appended by kdeshell, after
    // whatever an app names here (pylib/kdeshell.py MENU_ORDER).
    readonly property var menuOrder: ["file", "edit", "view", "tools", "settings"]

    // What the hyprvtb titlebar column gets: the six cells it had before this
    // table grew a menubar's worth of rows around them. Nothing about the
    // Hyprland face changed.
    readonly property var tbButtons: root.actions.filter(
        (a) => a === "-" || a.tb === true)

    // The selected output, for the rows above that act on one. A multi-select
    // has no single answer, so it counts as none (the gallery's own right-click
    // still handles the set).
    readonly property string selOne: results.gallery.selection.length === 1
                                     ? results.gallery.selection[0] : ""
    // ...and the parameters stored in it, which is what "reuse" needs and what
    // a file written by something else does not have.
    readonly property var selParams: root.selOne === "" ? null
        : Gallery.paramsAt(Gallery.indexOf(root.selOne))

    function pushButtons() {
        Titlebar.setButtons(root.tbButtons)
        Titlebar.setFooter(App.queue > 0 ? ("Q" + App.queue) : "")
        Titlebar.setLoading(App.busy)
    }

    // ONE handler, TWO chromes: the hyprvtb titlebar column clicks it, and in a
    // Plasma session `menuBar` does (qmlcommon/DeskMenuBar.qml). Same ids.
    function tbAction(id) {
        if (id === "gen") root.submit()
        else if (id === "stop") App.cancel()
        else if (id === "p") root.view = 0
        else if (id === "g") root.view = 1
        else if (id === "pv") root.showPreview = !root.showPreview
        else if (id === "set") root.showSettings = !root.showSettings
        else if (id === "open") { if (root.selOne !== "") App.openExternally(root.selOne) }
        else if (id === "folder") App.openFolder()
        else if (id === "copyprompt") { if (root.selOne !== "") App.copyPrompt(root.selOne) }
        else if (id === "clearprompt") root.set("positive", "")
        else if (id === "rescan") App.rescan()
        else if (id === "backendstart") App.startBackend()
        else if (id === "backendstop") App.stopBackend()
        else if (id === "unload") App.unloadModels()
        // The three reuse verbs are the gallery menu's, on the selected output.
        // `view = 0` after, because injecting settings you cannot see happen is
        // the same as not reporting it (docs/DESIGN.md §10).
        else if (id === "injall" || id === "injprompt" || id === "injparams") {
            var p = root.selParams
            if (!p) return
            if (id === "injall") root.injectAll(p)
            else if (id === "injprompt") root.injectPrompt(p)
            else root.injectParams(p)
            root.view = 0
        }
    }

    // The menubar the Plasma session gets in place of the titlebar column;
    // 0-height and invisible in the Hyprland one.
    DeskMenuBar {
        id: menuBar
        // painter's Plasma face is a real QMainWindow with a real QMenuBar
        // (pylib/kdeshell.py), so this one stands down in BOTH sessions and is
        // kept only for its 0-height contribution to the layout above.
        systemBar: true
        anchors { top: parent.top; left: parent.left; right: parent.right }
        // The FULL table, not the titlebar's six: this is a menubar, and it
        // draws nothing here anyway (`systemBar`) — painter's Plasma menubar is
        // a real QMenuBar.
        buttons: root.actions
        menuOrder: root.menuOrder
        onTriggered: (id) => root.tbAction(id)
    }

    Connections {
        target: Titlebar
        function onClicked(id) { root.tbAction(id) }
    }

    Connections {
        target: App
        function onBusyChanged() { root.pushButtons() }
        function onStatusChanged() { root.pushButtons() }
    }

    onShowSettingsChanged: pushButtons()
    onShowPreviewChanged: {
        pushButtons()
        if (root.restored) Prefs.set("showPreview", root.showPreview)
    }
    Component.onCompleted: {
        restoreState()
        pushButtons()
        applyDefaults()
        // The model list arrives after this (the registry scan is one tick
        // later), so the remembered selection is restored when it lands.
        App.selectModelByName(Prefs.get("model") || "")
        // ...and the mode with it, which re-selects its own model when the rows
        // land. It is applied second because it outranks the remembered name.
        App.restoreMode(Prefs.get("mode") || "")
    }

    // The mode changes what the left column is, and (for edit) which graph is
    // built, so it is worth remembering as promptly as the view is.
    Connections {
        target: App
        function onModeChanged() { if (root.restored) saveSoon.restart() }
    }

    // The one context menu, over everything: a prompt box is 64-130px tall and
    // `CtxMenu` clamps into its own root, so a menu parented inside one would be
    // trimmed to a couple of rows. Its coordinates are the scene's, which is
    // what `mapToItem(null, ...)` at the call site hands it.
    readonly property Item ctxMenu: sceneMenu
    CtxMenu {
        id: sceneMenu
        anchors.fill: parent
    }

    // The one dropdown list, for every Picker in the app — same reason as the
    // menu above: a list parented to its own picker is clipped by the left
    // column's Flickable and drawn under the panels that follow it. Below
    // CtxMenu in z, since a right-click menu is raised on top of whatever is
    // already open.
    readonly property Item pickerOverlay: sceneOverlay
    PickerOverlay {
        id: sceneOverlay
        anchors.fill: parent
    }

    // ESCAPE LETS GO OF A TEXT BOX. IT DOES NOT STOP ANYTHING. It used to cancel
    // every queued job, which is a destructive action on the key people press to
    // back out of one — and there was no way to leave a text box at all, so the
    // one thing Escape should do was the one thing it could not. Cancelling is
    // the titlebar's `x`, deliberately: a click, not a reflex.
    //
    // The sink is a plain focusable Item. Focus has to LAND somewhere; clearing
    // it without a destination leaves the window with no focus item and the next
    // keystroke going nowhere.
    Item { id: focusSink; focus: false; activeFocusOnTab: false }
    function releaseFocus() { focusSink.forceActiveFocus() }

    // ONE OWNER PER KEY. Under Plasma these sequences are on the QActions the
    // menubar builds (`shortcut:` in `actions` above) — two things claiming
    // Ctrl+Return in one window is an ambiguous shortcut, and Qt answers an
    // ambiguous shortcut by firing NEITHER. So the QML side stands down there,
    // exactly as the QML menubar and the queue strip do.
    Shortcut {
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        enabled: !root.plasma
        onActivated: root.submit()
    }
    // A window-level Shortcut sees a key BEFORE any focused item's Keys handler,
    // so this one has to say what Escape means for the whole window — adding it
    // for the text boxes alone silently took Escape away from the dropdown and
    // the context menu, which were closing on it perfectly well. Innermost
    // thing first, exactly as it looks on screen.
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (sceneOverlay.visible) sceneOverlay.close()
            else if (sceneMenu.visible) sceneMenu.close()
            else if (root.showSettings) root.showSettings = false
            else root.releaseFocus()
        }
    }
    Shortcut { sequence: "Ctrl+R"; enabled: !root.plasma; onActivated: App.rescan() }

    // Ctrl+V INTO A FRAME WELL.
    //
    // A window-level Shortcut sees a key before the focused item's own handler
    // (see Escape above), so an unconditional Ctrl+V would take paste away from
    // the prompt boxes — the one place in painter where Ctrl+V already meant
    // something. `textFocused` is what keeps that impossible, and it is the ONLY
    // condition: requiring the pointer to be over a well as well (which this
    // was until 2026-08-07) made the shortcut do nothing at all for anyone who
    // pressed Ctrl+V the way people press Ctrl+V — pointer wherever it happened
    // to be — with no message, because a shortcut that is not enabled is not a
    // failure to report. Discoverability beat the tidier rule.
    property string hoveredWell: ""
    readonly property bool textFocused: root.Window.activeFocusItem !== null
                                        && root.Window.activeFocusItem.selectedText !== undefined

    // Which well Ctrl+V means: the one under the pointer if there is one, then
    // the only one on screen, then the empty one — and with both frames set, the
    // first, which is the one a single pasted image is nearly always for.
    function pasteWell() {
        if (hoveredWell !== "") return hoveredWell
        if (App.isEdit) return "input"
        if (!App.isVideo) return ""
        var first = gen.useInputImage, last = gen.useLastFrame
        if (first !== last) return first ? "input" : "last"
        if (!first) return ""                       // text-to-video: no well
        return App.inputImage === "" || App.lastImage !== "" ? "input" : "last"
    }

    Shortcut {
        // Spelled out rather than StandardKey.Paste: the standard key resolves
        // to a set, and a Shortcut given one matched nothing here.
        sequences: ["Ctrl+V", "Shift+Ins"]
        enabled: !root.textFocused && root.pasteWell() !== ""
        onActivated: root.pasteWell() === "last" ? App.pasteLastImage()
                     : root.pasteWell() === "editadd" ? App.pasteEditImage()
                     : App.pasteInputImage()
    }

    // ------------------------------------------------------- injecting params

    // What "inject" means, in one place, for the gallery's menu. An output
    // carries the whole job (a still in its PNG chunk, a clip in its MP4 tag —
    // `outmeta.params_for`), and these are the three useful subsets of it:
    // its words, its numbers, or both. Each hands back a NEW gen object (see
    // `set` above) — mutating in place would change nothing on screen.
    function injectPrompt(p) {
        var g = clone(gen)
        if (p.positive !== undefined) g.positive = p.positive
        if (p.negative !== undefined) g.negative = p.negative
        gen = g
    }

    function injectParams(p) {
        var g = clone(gen)
        if (p.steps !== undefined) g.steps = p.steps
        if (p.cfg !== undefined) g.cfg = p.cfg
        if (p.denoise !== undefined) g.denoise = p.denoise
        if (p.sampler_name !== undefined) g.sampler_name = p.sampler_name
        if (p.scheduler !== undefined) g.scheduler = p.scheduler
        if (p.batch_size !== undefined) g.batch_size = p.batch_size
        // The seed is a parameter, and reusing one is the whole point of
        // reusing an image's numbers — so it also stops being random.
        if (p.seed !== undefined) { g.seed = p.seed; g.randomSeed = false }
        // Size comes back as the CONTROLS that produce it, not as raw pixels:
        // width/height are derived, so setting them here would be undone by the
        // next recompute and the panel would quietly disagree with the image it
        // came from. Reduce the ratio (gcd) and back out the megapixels.
        if (p.width > 0 && p.height > 0) {
            var a = p.width, b = p.height
            while (b) { var t = a % b; a = b; b = t }
            g.aspectW = Math.round(p.width / a)
            g.aspectH = Math.round(p.height / a)
            g.megapixels = Math.round(p.width * p.height / 100000) / 10
        }
        if (p.toggles) {
            g.negpip = p.toggles.negpip === true
            g.modelSampling = p.toggles.model_sampling === true
        }
        if (p.model_sampling) {
            g.ms = clone(g.ms)
            for (var k in p.model_sampling) g.ms[k] = p.model_sampling[k]
        }
        // A CLIP's settings are a different set, not a subset: seconds and a
        // frame rate instead of a batch, a pixel budget instead of a size, and
        // the two frame slots. `megapixels` is taken from the job rather than
        // backed out of width/height above — an image-to-video clip has no
        // width and height of its own, the dropped frame's budget IS the size.
        if (p.kind === "video") {
            if (p.duration !== undefined) g.duration = p.duration
            if (p.fps !== undefined) g.fps = p.fps
            if (p.megapixels > 0) g.megapixels = p.megapixels
            // The frames are part of the job, so they come back with it — and a
            // toggle whose picture has since moved comes back OFF rather than
            // arming a generate that could only refuse (docs/DESIGN.md §10).
            g.useInputImage = p.use_input_image === true
                              && App.restoreInputImage(p.input_image_local || "")
            g.useLastFrame = p.use_last_frame === true
                             && App.restoreLastImage(p.last_image_local || "")
        }
        gen = g
        recomputeDims()
    }

    function injectAll(p) { injectPrompt(p); injectParams(p) }

    // ------------------------------------------------------------ remembering

    // The window comes back the way it was left: size, which view, where the
    // divider sits, what was typed, and the numbers. Panels remember their own
    // collapsed state (Panel.qml, `persistKey`). Written on change, debounced,
    // because `gen` changes on every keystroke.
    property bool restored: false
    // Set once the startup selection's own LoRA chain has been put back
    // (Connections.onModelChanged, above) — guards against a later in-session
    // model switch re-applying a stale, already-consumed restore.
    property bool lorasRestored: false

    function saveState() {
        if (!restored) return          // never persist the pre-restore defaults
        Prefs.set("win.width", root.width)
        Prefs.set("win.height", root.height)
        Prefs.set("view", root.view)
        Prefs.set("splitRatio", root.splitRatio)
        Prefs.set("gen", JSON.stringify(root.gen))
        // Keep the current preset's entry in the per-model store level with the
        // live `gen` before persisting the whole map, so each preset's settings
        // come back across a relaunch (see genByModel / applyDefaults above).
        if (root.defaultsFor) root.genByModel[root.defaultsFor] = snapshotGen()
        Prefs.set("genByModel", JSON.stringify(root.genByModel))
        Prefs.set("model", App.selectedName)
        Prefs.set("mode", App.mode)
        Prefs.set("inputImage", App.inputImage)
        Prefs.set("editExtra", JSON.stringify(App.editExtraImages))
        Prefs.set("lastImage", App.lastImage)
        Prefs.set("lastSeed", App.lastSeed)
        Prefs.set("loras", JSON.stringify(App.lorasSnapshot()))
    }

    Timer {
        id: saveSoon
        interval: 700
        onTriggered: root.saveState()
    }
    Connections {
        target: App
        function onInputImageChanged() { if (root.restored) saveSoon.restart() }
        function onEditExtraChanged() { if (root.restored) saveSoon.restart() }
    }
    Connections {
        target: Loras
        function onStackChanged() { if (root.restored) saveSoon.restart() }
    }
    onGenChanged: if (root.restored) saveSoon.restart()
    onViewChanged: { pushButtons(); if (root.restored) saveSoon.restart() }
    onWidthChanged: if (root.restored) saveSoon.restart()
    onHeightChanged: if (root.restored) saveSoon.restart()

    // A setting changed right before closing (typical of video: tweak, hit
    // generate, close while the long job runs) must not lose the 700ms
    // debounce window — flush immediately rather than waiting for a timer
    // that the process may not live to see fire.
    //
    // `onClosing` is a WINDOW signal and this is an Item, so it is reached
    // through the window this tree happens to be in — which under Plasma is the
    // QQuickWidget's, closed with the QMainWindow around it. Destruction is the
    // backstop that covers both roofs whatever the compositor does.
    function flushState() {
        if (saveSoon.running) { saveSoon.stop(); root.saveState() }
    }
    Connections {
        target: root.Window.window
        ignoreUnknownSignals: true
        function onClosing() { root.flushState() }
    }
    Component.onDestruction: root.flushState()

    // The remembered window size is the WINDOW's business, not this Item's:
    // under Hyprland Main.qml owns the Window and under Plasma the QMainWindow
    // does (main.py). Assigning root.width here would fight the anchors that
    // fill either one.
    signal requestResize(int w, int h)

    function restoreState() {
        var w = Prefs.get("win.width"), h = Prefs.get("win.height")
        if (w > 0 && h > 0) root.requestResize(w, h)
        var v = Prefs.get("view"); if (v === 0 || v === 1) root.view = v
        root.showPreview = Prefs.get("showPreview") === true
        var r = Prefs.get("splitRatio")
        if (r > 0 && r < 1) {
            // The panes swapped sides on 2026-08-05; a ratio saved before that
            // describes the other pane. Flip it once, and record that it was.
            root.splitRatio = Prefs.get("splitSwapped") === true ? r : (1 - r)
        }
        Prefs.set("splitSwapped", true)
        // Each preset's remembered settings (the per-model store). Restored
        // before `gen`, so a switch to another preset in this session lands on
        // what it was last left at rather than a family default.
        var gbm = Prefs.get("genByModel")
        if (gbm) {
            try { root.genByModel = JSON.parse(gbm) }
            catch (e) { /* a corrupt map just leaves every preset at its default */ }
        }
        var raw = Prefs.get("gen")
        if (raw) {
            try {
                var saved = JSON.parse(raw)
                var g = clone(gen)
                for (var k in saved) if (g[k] !== undefined) g[k] = saved[k]
                gen = g
            } catch (e) {
                // A corrupt prefs file must not cost him the app; defaults stand.
            }
        }
        // The model whose defaults are already reflected in the restored `gen`.
        // Without this, the startup selection fires modelChanged and applyDefaults
        // overwrites everything that was just restored.
        root.defaultsFor = Prefs.get("model") || ""
        // The dropped first frame comes back too, quietly: a file that has since
        // moved just leaves the well empty.
        App.restoreInputImage(Prefs.get("inputImage") || "")
        try { App.restoreEditImages(JSON.parse(Prefs.get("editExtra") || "[]")) }
        catch (e) { /* a corrupt list just leaves the extras empty */ }
        App.restoreLastImage(Prefs.get("lastImage") || "")
        var ls = Prefs.get("lastSeed"); if (ls !== undefined && ls !== null) App.restoreLastSeed(ls)
        root.restored = true
    }
}

import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// Two panes: the controls on the left, results on the right.  Window chrome is
// the hyprvtb titlebar (see the Titlebar block at the bottom), so there is no
// in-app decoration.
Window {
    id: root
    visible: true
    width: 1280
    height: 900
    minimumWidth: 720
    minimumHeight: 560
    title: "painter"
    color: Theme.bg

    // The desktop's one slide duration + curve (docs/DESIGN.md 6.2).
    Motion { id: motion }

    property int view: 0            // 0 = params, 1 = gallery
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
    readonly property bool split: root.width >= root.splitFloor

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
        // keeps it 1:1, otherwise `editScale` multiplies each side. See
        // EditScalePanel.qml and registry._build_edit.
        editNoScale: true, editScale: 2.0,
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

    // The sampling settings a model was last left at, keyed by model name, so a
    // switch AWAY to another preset and back restores what was edited rather
    // than resetting to the family default. Without it applyDefaults() reapplies
    // the checkpoint's defaults on every return, which lost the video sampler
    // (steps/sampler/scheduler/denoise) on a preset round-trip. In-session only:
    // the whole `gen` is already persisted across launches under one key.
    property var sampleByModel: ({})

    // The subset applyDefaults() overwrites from the family and submit() sends as
    // the video sampling set — the fields a round-trip must preserve.
    function samplingOf(g) {
        return { steps: g.steps, denoise: g.denoise,
                 sampler_name: g.sampler_name, scheduler: g.scheduler }
    }

    function applyDefaults() {
        if (App.selectedName === root.defaultsFor) return
        var d = App.modelDefaults()
        if (!d || !d.steps) return
        // Stash the OUTGOING model's sampling edits before its defaults are
        // replaced, so returning to it restores them (below).
        if (root.defaultsFor) root.sampleByModel[root.defaultsFor] = samplingOf(gen)
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
            var m = g.ms
            for (var k in d.model_sampling) m[k] = d.model_sampling[k]
            g.ms = m
        }
        g.promptTransform = d.promptTransform
        // Restore this model's remembered sampling edits over its family
        // defaults, so a switch back to it lands on what he left rather than the
        // checkpoint default.
        var saved = root.sampleByModel[App.selectedName]
        if (saved) {
            if (saved.steps !== undefined) g.steps = saved.steps
            if (saved.denoise !== undefined) g.denoise = saved.denoise
            if (saved.sampler_name !== undefined) g.sampler_name = saved.sampler_name
            if (saved.scheduler !== undefined) g.scheduler = saved.scheduler
        }
        var wh = App.dims(g.aspectW + ":" + g.aspectH, g.megapixels, g.multiple)
        g.width = wh.width; g.height = wh.height
        gen = g
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
                editNoScale: g.editNoScale, editScale: g.editScale,
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
    Item {
        id: results
        x: 0
        y: 0
        width: root.split ? root.paneLeadW : root.width
        height: parent.height - root.barH
        visible: root.split || root.view === 1

        PreviewPane {
            id: preview
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: results.width < 320 ? 4 : 10
            anchors.bottomMargin: 0
            open: root.showPreview
        }

        // Margins shrink with the pane: 10px either side of a 220px column is
        // 9% of it spent on nothing (docs/DESIGN.md §5.2).
        GalleryView {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: preview.visible ? preview.bottom : parent.top
            anchors.bottom: parent.bottom
            anchors.margins: results.width < 320 ? 4 : 10
            anchors.topMargin: preview.visible ? 8 : (results.width < 320 ? 4 : 10)
            onMenuRequested: (sx, sy, items) => ctxMenu.open(sx, sy, items)
        }
    }

    Rectangle {
        id: splitBar
        visible: root.split
        z: 10
        x: root.paneLeadW
        y: 0
        width: root.splitterW
        // Stops at the status bar: a handle drawn over it also GRABS over it,
        // so the last 26px of the divider swallowed clicks meant for the bar.
        height: parent.height - root.barH
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
                var p = mapToItem(root.contentItem, m.x, m.y)
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

    // controls, on the right
    Rectangle {
        id: controls
        x: root.split ? root.paneLeadW + root.splitterW : 0
        y: 0
        width: root.split ? Math.max(1, root.width - x) : root.width
        height: parent.height
        color: Theme.bg
        visible: root.split || root.view === 0

        KineticFlickable {
            id: controlsFlick
            anchors.fill: parent
            anchors.margins: 10
            anchors.bottomMargin: root.barH
            contentHeight: controlsCol.implicitHeight
            clip: true
            // NO BAR ON THIS SIDE. The parameter column is a stack of panels
            // that collapse — its length is something he sets, not something he
            // has to navigate — and the gutter cost every control 11-16px of a
            // 300px column. The scrollbar that §9.2 asks for is on the results
            // side, where the content really is unbounded. The wheel and the
            // compositor's kinetic scroll are untouched.

            Column {
                id: controlsCol
                width: controlsFlick.width
                spacing: 10

                ModelPicker { width: parent.width; persistKey: "panel.model" }
                // EDIT MODE IS AN IMAGE AND A PROMPT, and nothing else: the
                // graph reads the size out of the picture, has no negative to
                // encode and carries the family's own steps/cfg/shift, so every
                // panel below this one would be a control that changes nothing
                // (docs/DESIGN.md §10). A Column skips invisible children, so
                // they leave no gaps.
                EditPanel {
                    width: parent.width
                    persistKey: "panel.edit"
                    visible: App.isEdit
                }
                EditScalePanel {
                    width: parent.width
                    persistKey: "panel.editscale"
                    visible: App.isEdit
                }
                // The seed IS read by the edit graph, so the edit preset gets
                // its own seed control — the sampling panel that normally holds
                // it is hidden here. Same SeedField, so it behaves identically.
                SeedPanel {
                    width: parent.width
                    persistKey: "panel.editseed"
                    visible: App.isEdit
                }
                PromptEditor {
                    width: parent.width
                    persistKey: "panel.prompt"
                    onMenuRequested: (sx, sy, items) => ctxMenu.open(sx, sy, items)
                }
                LoraStack {
                    width: parent.width
                    persistKey: "panel.lora"
                    visible: !App.isEdit
                }
                // Only for a video family, and the two below it follow the same
                // rule from the inside: no negative prompt, no CFG, no batch, and
                // no aspect while a first frame is deciding it. A Column skips
                // invisible children, so these leave no gap.
                VideoPanel {
                    width: parent.width
                    persistKey: "panel.video"
                    visible: App.isVideo && !App.isEdit
                }
                ParamsPanel {
                    width: parent.width
                    persistKey: "panel.sampling"
                    visible: !App.isEdit
                }
                ResolutionPanel {
                    width: parent.width
                    persistKey: "panel.resolution"
                    visible: !App.isEdit
                    // In image-to-video the size comes out of the dropped image,
                    // and MP is the only part of it left to choose — that is
                    // handled inside the panel, which keeps its MP box.
                }
                TogglePanel {
                    width: parent.width
                    persistKey: "panel.patches"
                    visible: !App.isVideo && !App.isEdit
                }
                Item { width: 1; height: 6 }
            }
        }
    }

    // ------------------------------------------------------------- overlays

    // The status bar owns the bottom strip of the window; the splitter stops
    // above it (see splitBar) rather than crossing it, which put a drag target
    // on top of the generate button.
    readonly property int barH: 26

    QueueBar {
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
        anchors.fill: parent
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

    // Labels are lowercase ASCII, one or two characters, and the settings cell
    // is "st" — the same label player and surfer use for the same button
    // (docs/DESIGN.md §12.1: a function that already has a glyph keeps it in every
    // app). They were UPPERCASE, with "*" for settings, which was painter's
    // alone on this desktop.
    function pushButtons() {
        Titlebar.setButtons([
            { id: "gen",  label: "gen",  state: App.busy ? 2 : 0, tip: "Generate" },
            { id: "stop", label: "x",    state: App.busy ? 0 : 2, tip: "Cancel all" },
            "-",
            { id: "p",    label: "p",    state: root.view === 0 ? 1 : 0, tip: "Parameters" },
            { id: "g",    label: "g",    state: root.view === 1 ? 1 : 0, tip: "Gallery" },
            { id: "pv",   label: "pv",   state: root.showPreview ? 1 : 0,
              tip: "Preview viewport" },
            "-",
            { id: "set",  label: "st",   state: root.showSettings ? 1 : 0,
              tip: "Settings", bottom: true }
        ])
        Titlebar.setFooter(App.queue > 0 ? ("Q" + App.queue) : "")
        Titlebar.setLoading(App.busy)
    }

    Connections {
        target: Titlebar
        function onClicked(id) {
            if (id === "gen") root.submit()
            else if (id === "stop") App.cancel()
            else if (id === "p") root.view = 0
            else if (id === "g") root.view = 1
            else if (id === "pv") root.showPreview = !root.showPreview
            else if (id === "set") root.showSettings = !root.showSettings
        }
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
    CtxMenu {
        id: ctxMenu
        anchors.fill: parent
    }

    // The one dropdown list, for every Picker in the app — same reason as the
    // menu above: a list parented to its own picker is clipped by the left
    // column's Flickable and drawn under the panels that follow it. Below
    // CtxMenu in z, since a right-click menu is raised on top of whatever is
    // already open.
    PickerOverlay {
        id: pickerOverlay
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

    Shortcut { sequences: ["Ctrl+Return", "Ctrl+Enter"]; onActivated: root.submit() }
    // A window-level Shortcut sees a key BEFORE any focused item's Keys handler,
    // so this one has to say what Escape means for the whole window — adding it
    // for the text boxes alone silently took Escape away from the dropdown and
    // the context menu, which were closing on it perfectly well. Innermost
    // thing first, exactly as it looks on screen.
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (pickerOverlay.visible) pickerOverlay.close()
            else if (ctxMenu.visible) ctxMenu.close()
            else if (root.showSettings) root.showSettings = false
            else root.releaseFocus()
        }
    }
    Shortcut { sequence: "Ctrl+R"; onActivated: App.rescan() }

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
    readonly property bool textFocused: activeFocusItem !== null
                                        && activeFocusItem.selectedText !== undefined

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

    // What "inject" means, in one place, for the gallery's menu. An image's PNG
    // carries the whole job, and these are the three useful subsets of it:
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
    onClosing: if (saveSoon.running) { saveSoon.stop(); root.saveState() }

    function restoreState() {
        var w = Prefs.get("win.width"), h = Prefs.get("win.height")
        if (w > 0 && h > 0) { root.width = w; root.height = h }
        var v = Prefs.get("view"); if (v === 0 || v === 1) root.view = v
        root.showPreview = Prefs.get("showPreview") === true
        var r = Prefs.get("splitRatio")
        if (r > 0 && r < 1) {
            // The panes swapped sides on 2026-08-05; a ratio saved before that
            // describes the other pane. Flip it once, and record that it was.
            root.splitRatio = Prefs.get("splitSwapped") === true ? r : (1 - r)
        }
        Prefs.set("splitSwapped", true)
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

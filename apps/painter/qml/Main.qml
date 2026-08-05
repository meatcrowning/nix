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

    property int view: 0            // 0 = params, 1 = gallery
    property bool showSettings: false

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

    // Chrome greys to the SAME tone the hyprvtb titlebar fades to when the
    // window loses focus, so painter reads as inactive in lock-step with its
    // own titlebar instead of staying brighter than the bar beside it — the
    // idiom filer uses (docs/DESIGN.md §3.1). Body text and values keep their own
    // colours; only the accented chrome follows.
    readonly property bool winActive: root.active
    readonly property color fgAccent: root.active ? Theme.accent : Theme.inactive

    // Live generation settings, seeded from the selected model's family.
    property var gen: ({
        positive: "", negative: "",
        steps: 20, cfg: 1.0, denoise: 1.0,
        sampler_name: "euler", scheduler: "simple",
        seed: 0, randomSeed: true, batch_size: 1, count: 1,
        // The aspect is two integers the user types; `aspect` is the "w:h"
        // string they compose, which is what App.dims (registry.calc_dims)
        // parses. Width and height are DERIVED — never set by hand, so there is
        // one source of truth for the size and the header badge cannot disagree
        // with the graph.
        aspectW: 1, aspectH: 1, megapixels: 1.0, multiple: 64,
        width: 1024, height: 1024,
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

    function applyDefaults() {
        var d = App.modelDefaults()
        if (!d || !d.steps) return
        var g = clone(gen)
        g.steps = d.steps; g.cfg = d.cfg; g.denoise = d.denoise !== undefined ? d.denoise : 1.0
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
        App.generate({
            positive: g.positive, negative: g.negative,
            steps: g.steps, cfg: g.cfg, denoise: g.denoise,
            sampler_name: g.sampler_name, scheduler: g.scheduler,
            seed: g.seed, randomSeed: g.randomSeed,
            batch_size: g.batch_size,
            width: g.width, height: g.height,
            toggles: ({ negpip: g.negpip, model_sampling: g.modelSampling }),
            model_sampling: g.ms
        }, g.count)
    }

    Connections {
        target: App
        function onModelChanged() { root.applyDefaults() }
        function onToast(msg, isError) { toast.show(msg, isError) }
    }

    // ---------------------------------------------------------------- panes

    Row {
        anchors.fill: parent
        spacing: 0

        // left: everything you set
        Rectangle {
            id: left
            // Never wider than half the split: the controls are legible from
            // ~300px, and beyond that every extra pixel is worth more to the
            // images than to a column of 20px boxes.
            width: root.split ? Math.max(300, Math.min(520, Math.min(root.width * 0.42,
                                                                     root.width - 220)))
                              : root.width
            height: parent.height
            color: Theme.bg
            visible: root.split || root.view === 0

            KineticFlickable {
                id: leftFlick
                anchors.fill: parent
                anchors.margins: 10
                contentHeight: leftCol.implicitHeight
                clip: true
                ScrollBar.vertical: VScroll { id: vscroll }

                Column {
                    id: leftCol
                    // The scrollbar's own width, never a literal — it is a
                    // desktop-wide setting (docs/DESIGN.md 9.2), 11-16px.
                    width: leftFlick.width - vscroll.barW
                    spacing: 10

                    ModelPicker { width: parent.width }
                    PromptEditor {
                        width: parent.width
                        onMenuRequested: (sx, sy, items) => ctxMenu.open(sx, sy, items)
                    }
                    LoraStack { width: parent.width }
                    ParamsPanel { width: parent.width }
                    ResolutionPanel { width: parent.width }
                    TogglePanel { width: parent.width }
                    Item { width: 1; height: 6 }
                }
            }
        }

        Rectangle {
            width: 1
            height: parent.height
            color: Theme.border
            visible: left.visible && right.visible
        }

        // right: what came out
        Item {
            id: right
            width: root.split ? parent.width - left.width - 1 : parent.width
            height: parent.height
            visible: root.split || root.view === 1
            // Margins shrink with the pane: 10px either side of a 220px column
            // is 9% of it spent on nothing (docs/DESIGN.md §5.2).
            GalleryView {
                anchors.fill: parent
                anchors.margins: right.width < 320 ? 4 : 10
            }
        }
    }

    // ------------------------------------------------------------- overlays

    QueueBar {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 26
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
        border.color: error ? Theme.crit : Theme.border
        border.width: 1
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

        SequentialAnimation {
            id: fade
            NumberAnimation { target: toast; property: "opacity"; to: 1; duration: 120 }
            PauseAnimation { duration: 3200 }
            NumberAnimation { target: toast; property: "opacity"; to: 0; duration: 400 }
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
            else if (id === "set") root.showSettings = !root.showSettings
        }
    }

    Connections {
        target: App
        function onBusyChanged() { root.pushButtons() }
        function onStatusChanged() { root.pushButtons() }
    }

    onViewChanged: pushButtons()
    onShowSettingsChanged: pushButtons()
    Component.onCompleted: { pushButtons(); applyDefaults() }

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

    // Keyboard: Ctrl+Enter generates, Escape cancels.
    Shortcut { sequences: ["Ctrl+Return", "Ctrl+Enter"]; onActivated: root.submit() }
    Shortcut { sequence: "Escape"; onActivated: App.cancel() }
    Shortcut { sequence: "Ctrl+R"; onActivated: App.rescan() }
}

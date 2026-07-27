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

    // Live generation settings, seeded from the selected model's family.
    property var gen: ({
        positive: "", negative: "",
        steps: 20, cfg: 1.0, denoise: 1.0,
        sampler_name: "euler", scheduler: "simple",
        seed: 0, randomSeed: true, batch_size: 1, count: 1,
        aspect: "1:1", megapixels: 1.0, multiple: 64,
        width: 1024, height: 1024,
        negpip: false, modelSampling: false,
        ms: ({ shift_start: 3.5, shift_end: 1.2, start_percent: 0.0,
               end_percent: 0.5, curve: "ease_in", outside_window: "hold",
               multiplier: 1.0 }),
        promptTransform: "none"
    })

    function applyDefaults() {
        var d = App.modelDefaults()
        if (!d || !d.steps) return
        var g = gen
        g.steps = d.steps; g.cfg = d.cfg; g.denoise = d.denoise !== undefined ? d.denoise : 1.0
        g.sampler_name = d.sampler_name; g.scheduler = d.scheduler
        g.aspect = d.aspect; g.megapixels = d.megapixels; g.multiple = d.multiple
        g.negpip = d.toggles && d.toggles.negpip === true
        g.modelSampling = d.toggles && d.toggles.model_sampling === true
        if (d.model_sampling) {
            var m = g.ms
            for (var k in d.model_sampling) m[k] = d.model_sampling[k]
            g.ms = m
        }
        g.promptTransform = d.promptTransform
        var wh = App.dims(g.aspect, g.megapixels, g.multiple)
        g.width = wh.width; g.height = wh.height
        gen = g
    }

    function recomputeDims() {
        var g = gen
        var wh = App.dims(g.aspect, g.megapixels, g.multiple)
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
            width: Math.min(520, Math.max(340, root.width * 0.42))
            height: parent.height
            color: Theme.bg
            visible: root.view === 0 || root.width > 900

            KineticFlickable {
                id: leftFlick
                anchors.fill: parent
                anchors.margins: 10
                contentHeight: leftCol.implicitHeight
                clip: true
                ScrollBar.vertical: VScroll {}

                Column {
                    id: leftCol
                    width: leftFlick.width - 12
                    spacing: 10

                    ModelPicker { width: parent.width }
                    PromptEditor { width: parent.width }
                    LoraStack { width: parent.width }
                    ParamsPanel { width: parent.width }
                    ResolutionPanel { width: parent.width }
                    TogglePanel { width: parent.width }
                    Item { width: 1; height: 6 }
                }
            }
        }

        Rectangle { width: 1; height: parent.height; color: Theme.border }

        // right: what came out
        Item {
            width: parent.width - left.width - 1
            height: parent.height
            visible: root.view === 1 || root.width > 900
            GalleryView { anchors.fill: parent; anchors.margins: 10 }
        }
    }

    // ------------------------------------------------------------- overlays

    QueueBar {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 26
    }

    SettingsDrawer {
        id: settings
        anchors.fill: parent
        visible: root.showSettings
        onClosed: root.showSettings = false
    }

    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        width: Math.min(msg.implicitWidth + 24, root.width - 60)
        height: 30
        radius: 2
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

    function pushButtons() {
        Titlebar.setButtons([
            { id: "gen",  label: "GEN",  state: App.busy ? 2 : 0, tip: "Generate" },
            { id: "stop", label: "X",    state: App.busy ? 0 : 2, tip: "Cancel all" },
            "-",
            { id: "p",    label: "P",    state: root.view === 0 ? 1 : 0, tip: "Parameters" },
            { id: "g",    label: "G",    state: root.view === 1 ? 1 : 0, tip: "Gallery" },
            "-",
            { id: "set",  label: "*",    state: root.showSettings ? 1 : 0,
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

    // Keyboard: Ctrl+Enter generates, Escape cancels.
    Shortcut { sequences: ["Ctrl+Return", "Ctrl+Enter"]; onActivated: root.submit() }
    Shortcut { sequence: "Escape"; onActivated: App.cancel() }
    Shortcut { sequence: "Ctrl+R"; onActivated: App.rescan() }
}

import QtQuick

Panel {
    title: App.encoderControls ? "Encoder and sampling" : "References"
    Toggle {
        visible: App.encoderControls
        objectName: "kreaNegpip"
        label: "NegPiP"
        checked: root.gen.negpip
        onToggled: function(v) { root.set("negpip", v) }
    }
    PixelText {
        visible: App.encoderControls && root.gen.negpip
        width: parent.width
        wrapMode: Text.WordWrap
        text: "Negative box is applied at CFG 1. Signed weights such as (blur:-1) also work in the positive prompt."
        color: Theme.textDim
    }
    // Keep the editor's visual parent stable when Panel parks collapsed rows.
    Column {
        visible: App.encoderControls
        width: parent.width
        spacing: 5
        PixelText { text: "System prompt"; color: Theme.textDim }
        PromptBox {
            objectName: "kreaSystemPrompt"
            width: parent.width
            boxHeight: Prefs.get("unity.systemH") > 0 ? Prefs.get("unity.systemH") : 100
            onResized: h => Prefs.set("unity.systemH", h)
            placeholder: "Encoder system prompt (empty for no instruction)"
            value: root.gen.system_prompt
            onEdited: function(t) { root.set("system_prompt", t) }
            onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
        }
    }
    Field {
        visible: App.encoderControls
        label: "Schedule"
        hint: "Native keeps the model's schedule. turbo_fixed pins the Krea Turbo shift to 1.15."
        Picker {
            width: 180
            options: ["native", "manual", "turbo_fixed"]
            value: root.gen.krea_sampling
            onPicked: function(v) { root.set("krea_sampling", v) }
        }
    }
    Field {
        label: "Shift"
        visible: App.encoderControls && root.gen.krea_sampling === "manual"
        Spin {
            width: 80
            value: root.gen.krea_shift; from: 0; to: 100; step: 0.01; decimals: 2
            onEdited: function(v) { root.set("krea_shift", v) }
        }
    }
    Toggle {
        label: "Use reference images"
        checked: root.gen.useReferences
        onToggled: function(v) { root.set("useReferences", v) }
    }
    PixelText {
        visible: App.layoutSupport && root.gen.useReferences
        width: parent.width
        wrapMode: Text.WordWrap
        text: "References use whole images. Heatmaps and PPM weighting are unavailable with references."
        color: Theme.textDim
    }
    Field {
        label: "Reference MP"
        visible: root.gen.useReferences
        hint: "Pixel budget for each whole reference image; aspect ratio is preserved."
        Spin {
            width: 80
            value: root.gen.reference_megapixels; from: 0.01; to: 16; step: 0.05; decimals: 2
            onEdited: function(v) { root.set("reference_megapixels", v) }
        }
    }
}

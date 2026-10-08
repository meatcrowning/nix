import QtQuick

Panel {
    title: "Encoder and sampling"
    PixelText { text: "System prompt"; color: Theme.textDim }
    PromptBox {
        objectName: "kreaSystemPrompt"
        width: parent.width
        boxHeight: 100
        placeholder: "Encoder system prompt (empty for no instruction)"
        value: root.gen.system_prompt
        onEdited: function(t) { root.set("system_prompt", t) }
        onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
    }
    Field {
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
        visible: root.gen.krea_sampling === "manual"
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
    Field {
        label: "Ref MP"
        visible: root.gen.useReferences
        hint: "Encoder image budget per reference. This controls detail and memory, not reference strength."
        Spin {
            width: 80
            value: root.gen.reference_megapixels; from: 0.01; to: 4; step: 0.05; decimals: 2
            onEdited: function(v) { root.set("reference_megapixels", v) }
        }
    }
}

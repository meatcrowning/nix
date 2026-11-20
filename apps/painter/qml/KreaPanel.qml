import QtQuick
import QtQuick.Controls

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
        label: "Use images"
        checked: root.gen.useReferences
        onToggled: function(v) { root.set("useReferences", v) }
    }
    Field {
        label: "MP"
        visible: root.gen.useReferences
        hint: "Pixel budget for each whole reference image; aspect ratio is preserved."
        Row {
            spacing: 8
            Spin {
                width: 80
                value: root.gen.reference_megapixels; from: 0.01; to: 16; step: 0.05; decimals: 2
                onEdited: function(v) { root.set("reference_megapixels", v) }
            }
            Toggle {
                objectName: "referencePositive"
                visible: App.layoutSupport
                anchors.verticalCenter: parent.verticalCenter
                label: "Pos"
                checked: root.gen.reference_positive
                onToggled: function(v) { root.set("reference_positive", v) }
            }
            Toggle {
                objectName: "referenceNegative"
                visible: App.layoutSupport
                anchors.verticalCenter: parent.verticalCenter
                label: "Neg"
                checked: root.gen.reference_negative
                onToggled: function(v) { root.set("reference_negative", v) }
            }
        }
    }
    Field {
        label: "Timing"
        visible: App.layoutSupport && root.gen.useReferences
        hint: "Drag either handle, or drag the shaded interval. References apply only inside this portion of sampling steps."
        Column {
            width: parent.width
            property string value: timing.first.value === timing.second.value
                ? "No steps (of " + timing.to + ")"
                : "Steps " + (timing.first.value+1) + "–" + timing.second.value + " of " + timing.to
            RangeSlider {
                id: timing
                objectName: "referenceRange"
                width: parent.width
                from: 0; to: Math.max(1, root.gen.steps); stepSize: 1
                snapMode: RangeSlider.SnapAlways
                first.value: Math.ceil(root.gen.reference_start * to - 1e-9)
                second.value: Math.ceil(root.gen.reference_end * to - 1e-9)
                first.onMoved: root.set("reference_start", first.value / timing.to)
                second.onMoved: root.set("reference_end", second.value / timing.to)
                function moveRange(start, end) {
                    root.set("reference_start", start)
                    root.set("reference_end", end)
                }
                readonly property real firstCenter: leftPadding + first.position * (availableWidth-first.handle.width) + first.handle.width/2
                readonly property real secondCenter: leftPadding + second.position * (availableWidth-second.handle.width) + second.handle.width/2
                MouseArea {
                    x: timing.firstCenter + timing.first.handle.width/2
                    width: Math.max(0, timing.secondCenter-timing.second.handle.width/2-x)
                    height: parent.height
                    cursorShape: Qt.SizeHorCursor
                    property real origin
                    property real low
                    property real high
                    onPressed: function(mouse) {
                        origin = mapToItem(timing, mouse.x, mouse.y).x
                        low = timing.first.value; high = timing.second.value
                    }
                    onPositionChanged: function(mouse) {
                        if (!pressed) return
                        var delta = (mapToItem(timing, mouse.x, mouse.y).x-origin)/(timing.availableWidth-timing.first.handle.width)
                        delta = Math.max(-low, Math.min(timing.to-high, Math.round(delta * timing.to)))
                        timing.moveRange((low+delta)/timing.to, (high+delta)/timing.to)
                    }
                }
            }
            PixelText { text: parent.value; color: Theme.textDim }
        }
    }
    ImageInputs {
        visible: App.layoutSupport && root.gen.useReferences
    }
}

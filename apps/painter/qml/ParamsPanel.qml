import QtQuick
import QtQuick.Controls

// Sampling controls.  The sampler and scheduler lists are whatever the running
// ComfyUI reports, not a fixed list, so they follow backend updates.
Panel {
    // `id: panel` is not decoration: every row in here reaches its panel by
    // that id (Field.qml, Toggle.qml), so without it nothing in the sampling
    // section could be pinned — silently, since the lookup is guarded.
    id: panel
    title: "Sampling"
    badge: App.nativeScheduler ? "Euler + native recommended" : App.samplers.length + " samplers"

    Field {
        label: "Steps"
        Spin {
            value: root.gen.steps; from: 1; to: 300; step: 1
            onEdited: function (v) { root.set("steps", v) }
        }
    }

    // CFG and batch are image-only. The video graph guides with BasicGuider,
    // which takes no CFG, and its "batch" is the frame count — set as a duration
    // in the video panel. Both would be controls that change nothing here.
    Field {
        label: "CFG"
        visible: !App.isVideo
        Spin {
            value: root.gen.cfg; from: 0; to: 30; step: 0.1; decimals: 2
            onEdited: function (v) { root.set("cfg", v) }
        }
    }

    Field {
        label: "Denoise"
        hint: App.nativeScheduler ? "Experimental schedule truncation; not source-image preservation strength." : ""
        visible: !App.fixedSampling
        Spin {
            value: root.gen.denoise; from: 0; to: 1; step: 0.01; decimals: 2
            onEdited: function (v) { root.set("denoise", v) }
        }
    }

    Field {
        label: "Sampler"
        hint: App.nativeScheduler ? "Euler is the reference sampler; other choices are experimental." : ""
        visible: !App.fixedSampling
        Picker {
            width: 200
            options: App.samplers
            value: root.gen.sampler_name
            onPicked: function (v) { root.set("sampler_name", v) }
        }
    }

    Field {
        label: "Scheduler"
        hint: App.nativeScheduler ? "llada_image is the reference schedule; other choices are experimental." : ""
        visible: !App.fixedSampling
        Picker {
            width: 200
            options: App.nativeScheduler ? [App.nativeScheduler].concat(App.schedulers) : App.schedulers
            value: root.gen.scheduler
            onPicked: function (v) { root.set("scheduler", v) }
        }
    }

    Field {
        label: "SLG layers"
        visible: App.layoutSupport
        hint: "Single-stream block indices on the negative pass, comma-separated. Empty disables skipping. MOSS has no double-stream blocks."
        TextField {
            objectName: "slgLayers"
            width: parent.width
            text: root.gen.slg_single_layers
            Accessible.name: "SLG single layers"
            onTextEdited: root.set("slg_single_layers", text)
        }
    }
    Field {
        label: "SLG start"
        visible: App.layoutSupport
        hint: "Sampling fraction where skipping starts (0 to 1)."
        Spin {
            objectName: "slgStart"
            value: root.gen.slg_start_percent; from: 0; to: 1; step: 0.001; decimals: 3
            onEdited: function(v) { root.set("slg_start_percent", v) }
        }
    }
    Field {
        label: "SLG end"
        visible: App.layoutSupport
        hint: "Sampling fraction where skipping ends (0 to 1)."
        Spin {
            objectName: "slgEnd"
            value: root.gen.slg_end_percent; from: 0; to: 1; step: 0.001; decimals: 3
            onEdited: function(v) { root.set("slg_end_percent", v) }
        }
    }


    Field {
        label: (App.isVideo || App.isEdit) ? "Count" : "Batch"
        hint: (App.isVideo || App.isEdit)
              ? "How many separate jobs to queue."
              : "Images per submitted job (one sampler run); count queues separate jobs."
        Row {
            spacing: 8
            Spin {
                width: 56
                visible: !App.isVideo && !App.isEdit
                value: root.gen.batch_size; from: 1; to: 16; step: 1
                onEdited: function (v) { root.set("batch_size", v) }
            }
            PixelText {
                text: "Count"
                visible: !App.isVideo && !App.isEdit
                color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
            }
            Spin {
                width: 56
                value: root.gen.count; from: 1; to: 100; step: 1
                onEdited: function (v) { root.set("count", v) }
            }
        }
    }
    Toggle {
        label: "PPM"
        visible: App.layoutSupport
        checked: root.gen.negpip
        onToggled: function (v) { root.set("negpip", v) }
        ToolTipArea { anchors.fill: parent; text: "Enable NegPiP and prompt weighting for MOSS-Image, e.g. (detail:1.5) or (detail:-1)." }
    }

}

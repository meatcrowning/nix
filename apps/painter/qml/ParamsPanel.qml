import QtQuick

// Sampling controls.  The sampler and scheduler lists are whatever the running
// ComfyUI reports, not a fixed list, so they follow backend updates.
Panel {
    title: "sampling"
    badge: App.samplers.length + " samplers"

    Field {
        label: "steps"
        Spin {
            value: root.gen.steps; from: 1; to: 300; step: 1
            onEdited: function (v) { root.set("steps", v) }
        }
    }

    // CFG and batch are image-only. The video graph guides with BasicGuider,
    // which takes no CFG, and its "batch" is the frame count — set as a duration
    // in the video panel. Both would be controls that change nothing here.
    Field {
        label: "cfg"
        visible: !App.isVideo
        Spin {
            value: root.gen.cfg; from: 0; to: 30; step: 0.1; decimals: 2
            onEdited: function (v) { root.set("cfg", v) }
        }
    }

    Field {
        label: "denoise"
        Spin {
            value: root.gen.denoise; from: 0; to: 1; step: 0.01; decimals: 2
            onEdited: function (v) { root.set("denoise", v) }
        }
    }

    Field {
        label: "sampler"
        Picker {
            width: 200
            options: App.samplers
            value: root.gen.sampler_name
            onPicked: function (v) { root.set("sampler_name", v) }
        }
    }

    Field {
        label: "scheduler"
        Picker {
            width: 200
            options: App.schedulers
            value: root.gen.scheduler
            onPicked: function (v) { root.set("scheduler", v) }
        }
    }

    Field {
        label: "seed"
        Row {
            spacing: 8
            Spin {
                width: 150
                value: root.gen.seed; from: 0; to: 9007199254740992; step: 1
                enabled: !root.gen.randomSeed
                opacity: root.gen.randomSeed ? 0.45 : 1
                onEdited: function (v) { root.set("seed", v) }
            }
            Toggle {
                label: "random"
                checked: root.gen.randomSeed
                anchors.verticalCenter: parent.verticalCenter
                onToggled: function (v) { root.set("randomSeed", v) }
            }
        }
    }

    Field {
        label: App.isVideo ? "count" : "batch"
        hint: App.isVideo
              ? "How many separate video jobs to queue."
              : "Images per submitted job (one sampler run); count queues separate jobs."
        Row {
            spacing: 8
            Spin {
                width: 56
                visible: !App.isVideo
                value: root.gen.batch_size; from: 1; to: 16; step: 1
                onEdited: function (v) { root.set("batch_size", v) }
            }
            PixelText {
                text: "count"
                visible: !App.isVideo
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
}

import QtQuick

// Sampling controls.  The sampler and scheduler lists are whatever the running
// ComfyUI reports, not a fixed list, so they follow backend updates.
Panel {
    title: "SAMPLING"
    badge: App.samplers.length + " samplers"

    Field {
        label: "steps"
        Spin {
            value: root.gen.steps; from: 1; to: 300; step: 1
            onEdited: function (v) { var g = root.gen; g.steps = v; root.gen = g }
        }
    }

    Field {
        label: "cfg"
        Spin {
            value: root.gen.cfg; from: 0; to: 30; step: 0.1; decimals: 2
            onEdited: function (v) { var g = root.gen; g.cfg = v; root.gen = g }
        }
    }

    Field {
        label: "denoise"
        Spin {
            value: root.gen.denoise; from: 0; to: 1; step: 0.01; decimals: 2
            onEdited: function (v) { var g = root.gen; g.denoise = v; root.gen = g }
        }
    }

    Field {
        label: "sampler"
        Picker {
            width: 200
            options: App.samplers
            value: root.gen.sampler_name
            onPicked: function (v) { var g = root.gen; g.sampler_name = v; root.gen = g }
        }
    }

    Field {
        label: "scheduler"
        Picker {
            width: 200
            options: App.schedulers
            value: root.gen.scheduler
            onPicked: function (v) { var g = root.gen; g.scheduler = v; root.gen = g }
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
                onEdited: function (v) { var g = root.gen; g.seed = v; root.gen = g }
            }
            Toggle {
                label: "random"
                checked: root.gen.randomSeed
                anchors.verticalCenter: parent.verticalCenter
                onToggled: function (v) { var g = root.gen; g.randomSeed = v; root.gen = g }
            }
        }
    }

    Field {
        label: "batch"
        hint: "Images per submitted job (one sampler run); count queues separate jobs."
        Row {
            spacing: 8
            Spin {
                width: 56
                value: root.gen.batch_size; from: 1; to: 16; step: 1
                onEdited: function (v) { var g = root.gen; g.batch_size = v; root.gen = g }
            }
            PixelText {
                text: "count"
                color: Theme.textDim
                anchors.verticalCenter: parent.verticalCenter
            }
            Spin {
                width: 56
                value: root.gen.count; from: 1; to: 100; step: 1
                onEdited: function (v) { var g = root.gen; g.count = v; root.gen = g }
            }
        }
    }
}

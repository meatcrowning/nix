import QtQuick

// The two optional nodes in the graph.  Both default per family and both can be
// flipped here; ModelSampling exposes its full parameter set, seeded with the
// values from the workflow this was built from.
Panel {
    id: panel
    title: "patches"
    badge: (root.gen.negpip ? "negpip " : "") + (root.gen.modelSampling ? "shift" : "")

    Toggle {
        label: "CLIPNegPip"
        checked: root.gen.negpip
        onToggled: function (v) { var g = root.gen; g.negpip = v; root.gen = g }
    }
    PixelText {
        text: "  lets (tag:-1.0) act as a negative weight inside the positive prompt"
        color: Theme.dim
        width: parent.width
        wrapMode: Text.Wrap
    }

    Item { width: 1; height: 4 }

    Toggle {
        label: "ModelSamplingSD3Advanced"
        checked: root.gen.modelSampling
        onToggled: function (v) { var g = root.gen; g.modelSampling = v; root.gen = g }
    }

    Column {
        visible: root.gen.modelSampling
        width: parent.width
        spacing: 4

        Field {
            label: "shift"
            hint: "Shift moves from start to end across the denoise window."
            Row {
                spacing: 6
                Spin {
                    width: 62
                    value: root.gen.ms.shift_start; from: 0; to: 100; step: 0.01; decimals: 2
                    onEdited: function (v) { var g = root.gen; g.ms.shift_start = v; root.gen = g }
                }
                PixelText { text: "->"; color: Theme.dim; anchors.verticalCenter: parent.verticalCenter }
                Spin {
                    width: 62
                    value: root.gen.ms.shift_end; from: 0; to: 100; step: 0.01; decimals: 2
                    onEdited: function (v) { var g = root.gen; g.ms.shift_end = v; root.gen = g }
                }
            }
        }

        Field {
            label: "window"
            hint: "Fraction of the denoise run over which the shift transition happens."
            Row {
                spacing: 6
                Spin {
                    width: 62
                    value: root.gen.ms.start_percent; from: 0; to: 1; step: 0.01; decimals: 2
                    onEdited: function (v) { var g = root.gen; g.ms.start_percent = v; root.gen = g }
                }
                PixelText { text: "->"; color: Theme.dim; anchors.verticalCenter: parent.verticalCenter }
                Spin {
                    width: 62
                    value: root.gen.ms.end_percent; from: 0; to: 1; step: 0.01; decimals: 2
                    onEdited: function (v) { var g = root.gen; g.ms.end_percent = v; root.gen = g }
                }
            }
        }

        Field {
            label: "curve"
            Picker {
                width: 150
                options: App.curves
                value: root.gen.ms.curve
                onPicked: function (v) { var g = root.gen; g.ms.curve = v; root.gen = g }
            }
        }

        Field {
            label: "outside"
            hint: "What the shift does before start_percent and after end_percent."
            Picker {
                width: 150
                options: App.outsideWindows
                value: root.gen.ms.outside_window
                onPicked: function (v) { var g = root.gen; g.ms.outside_window = v; root.gen = g }
            }
        }

        Field {
            label: "multiplier"
            Spin {
                value: root.gen.ms.multiplier; from: 0; to: 10; step: 0.01; decimals: 2
                onEdited: function (v) { var g = root.gen; g.ms.multiplier = v; root.gen = g }
            }
        }
    }
}

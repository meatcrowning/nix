import QtQuick

// Audio & Media = output/volume, the panel VU meter, and the media widget's
// spectrum + player selection (all share the cava backend).
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    SetSection {
        title: "output"
        SetRow {
            label: "volume step"
            desc: "change per scroll / key press"
            SetSlider {
                from: 1; to: 20; step: 1; unit: "%"
                value: page.d.volumeStep
                onMoved: (v) => { page.d.volumeStep = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "output sink"
            desc: "wpctl target; @DEFAULT_AUDIO_SINK@ follows the system default"
            SetTextField {
                fieldWidth: 200
                value: page.d.audioSink
                onCommitted: (t) => { page.d.audioSink = t; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "VU meter (bar)"
        SetRow {
            label: "bars"
            SetSlider {
                from: 1; to: 4; step: 1
                value: page.d.vuBars
                onMoved: (v) => { page.d.vuBars = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "smoothing"
            desc: "cava noise reduction; higher = smoother, slower"
            SetSlider {
                from: 0; to: 100; step: 1
                value: page.d.vuSmoothing
                onMoved: (v) => { page.d.vuSmoothing = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "frame rate"
            SetSlider {
                from: 15; to: 144; step: 1; unit: "fps"
                value: page.d.vuFramerate
                onMoved: (v) => { page.d.vuFramerate = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "media widget"
        SetRow {
            label: "spectrum bars"
            SetSlider {
                from: 4; to: 32; step: 1
                value: page.d.mediaSpectrumBars
                onMoved: (v) => { page.d.mediaSpectrumBars = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "prefer playing source"
            desc: "auto-follow whichever player is actively playing"
            SetToggle {
                checked: page.d.mediaPreferPlaying
                onToggled: (v) => { page.d.mediaPreferPlaying = v; SettingsStore.save(); }
            }
        }
    }
}

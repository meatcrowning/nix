import QtQuick

// Apps & Utilities — the on-demand tools: launcher, file browser, and the
// screenshot / screen-recording overlay.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    SetSection {
        title: "launcher"
        SetRow {
            label: "terminal"
            desc: "used to run terminal apps"
            SetTextField {
                fieldWidth: 160
                value: page.d.launcherTerminal
                onCommitted: (t) => { page.d.launcherTerminal = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "max results"
            desc: "0 = show all matches"
            SetSlider {
                from: 0; to: 30; step: 1
                value: page.d.launcherMaxResults
                onMoved: (v) => { page.d.launcherMaxResults = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "placeholder text"
            SetTextField {
                fieldWidth: 180
                value: page.d.launcherPlaceholder
                onCommitted: (t) => { page.d.launcherPlaceholder = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "search applications"
            SetToggle {
                checked: page.d.launcherProviderApps
                onToggled: (v) => { page.d.launcherProviderApps = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "calculator results"
            desc: "evaluate arithmetic in the search box"
            SetToggle {
                checked: page.d.launcherProviderCalc
                onToggled: (v) => { page.d.launcherProviderCalc = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "file browser"
        SetRow {
            label: "start folder"
            SetTextField {
                fieldWidth: 220
                value: page.d.fileBrowserStart
                onCommitted: (t) => { page.d.fileBrowserStart = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "show hidden files"
            SetToggle {
                checked: page.d.fileBrowserHidden
                onToggled: (v) => { page.d.fileBrowserHidden = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "folders first"
            SetToggle {
                checked: page.d.fileBrowserDirsFirst
                onToggled: (v) => { page.d.fileBrowserDirsFirst = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "confirm permanent delete"
            SetToggle {
                checked: page.d.fileBrowserConfirmDelete
                onToggled: (v) => { page.d.fileBrowserConfirmDelete = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "screenshot & recording"
        SetRow {
            label: "screenshot folder"
            SetTextField {
                fieldWidth: 220
                value: page.d.screenshotDir
                onCommitted: (t) => { page.d.screenshotDir = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "copy to clipboard"
            desc: "also place captures on the clipboard"
            SetToggle {
                checked: page.d.screenshotCopy
                onToggled: (v) => { page.d.screenshotCopy = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "recording folder"
            SetTextField {
                fieldWidth: 220
                value: page.d.recordingDir
                onCommitted: (t) => { page.d.recordingDir = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "record audio"
            SetToggle {
                checked: page.d.recordingAudio
                onToggled: (v) => { page.d.recordingAudio = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "recording frame rate"
            desc: "capped to the monitor's refresh rate"
            SetSlider {
                from: 24; to: 144; step: 1; unit: "fps"
                value: page.d.recordingFps
                onMoved: (v) => { page.d.recordingFps = v; SettingsStore.save(); }
            }
        }
    }
}

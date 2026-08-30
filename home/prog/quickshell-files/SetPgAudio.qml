import QtQuick
import Quickshell
import Quickshell.Io

// Audio = output/volume and the panel VU meter (both share the cava backend).
// The media widget's spectrum + player selection live on the Widgets page.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // bluetoothctl is used instead of a second BlueZ client so this page sees
    // the same paired devices and connection state as the rest of the desktop.
    // Listing is read-only; connect/disconnect only runs after an explicit
    // button press and is keyed by the address returned by bluetoothctl.
    property var bluetoothDevices: []
    property string bluetoothStatus: ""
    property bool bluetoothBusy: false

    function refreshBluetooth() {
        bluetoothStatus = "reading devices…";
        bluetoothList.running = false;
        bluetoothList.running = true;
    }

    function bluetoothAction(address, action) {
        if (bluetoothBusy || !address || (action !== "connect" && action !== "disconnect"))
            return;
        bluetoothBusy = true;
        bluetoothStatus = action + "ing…";
        bluetoothActionProc.command = ["bluetoothctl", action, address];
        bluetoothActionProc.running = true;
    }

    Process {
        id: bluetoothList
        command: ["sh", "-c",
            "bluetoothctl devices Paired 2>/dev/null | "
            + "while read -r kind address name; do "
            + "[ -n \"$address\" ] || continue; "
            + "connected=$(bluetoothctl info \"$address\" 2>/dev/null "
            + "| sed -n 's/^[[:space:]]*Connected: //p'); "
            + "printf '%s\\t%s\\t%s\\n' \"$address\" \"$name\" \"$connected\"; "
            + "done"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                const out = [];
                for (const line of (this.text || "").split("\n")) {
                    const fields = line.split("\t");
                    if (fields.length >= 3 && fields[0].trim()) {
                        out.push({ address: fields[0].trim(),
                                   name: fields[1].trim() || fields[0].trim(),
                                   connected: fields[2].trim() === "yes" });
                    }
                }
                page.bluetoothDevices = out;
                page.bluetoothStatus = out.length ? "" : "no paired devices";
            }
        }
        onExited: (code) => {
            if (code !== 0) page.bluetoothStatus = "bluetooth unavailable";
        }
    }

    Process {
        id: bluetoothActionProc
        running: false
        stdout: StdioCollector { id: bluetoothActionOutput }
        onExited: (code) => {
            page.bluetoothBusy = false;
            const lines = (bluetoothActionOutput.text || "").trim().split("\n");
            const result = lines[lines.length - 1] || "";
            page.bluetoothStatus = code === 0
                ? (result || "done") : (result || "could not change device");
            bluetoothRefresh.restart();
        }
    }

    Timer {
        id: bluetoothRefresh
        interval: 500
        onTriggered: page.refreshBluetooth()
    }

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
        title: "bluetooth"
        SetRow {
            label: "paired devices"
            desc: "connect or disconnect a remembered device"
            SetButton {
                text: "refresh"
                minWidth: 84
                enabled: !page.bluetoothBusy
                onClicked: page.refreshBluetooth()
            }
        }

        Column {
            width: parent.width - 8
            x: 4
            spacing: 2

            Repeater {
                model: page.bluetoothDevices
                delegate: Item {
                    required property var modelData
                    width: parent.width
                    height: 34

                    Column {
                        anchors { left: parent.left; right: action.left; verticalCenter: parent.verticalCenter }
                        spacing: 1
                        PixelText {
                            width: parent.width
                            text: modelData.name
                            color: Theme.text
                            elide: Text.ElideRight
                        }
                        PixelText {
                            text: (modelData.connected ? "connected · " : "") + modelData.address
                            color: modelData.connected ? Theme.accent : Theme.textDim
                        }
                    }

                    SetButton {
                        id: action
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        minWidth: 96
                        text: modelData.connected ? "disconnect" : "connect"
                        enabled: !page.bluetoothBusy
                        onClicked: page.bluetoothAction(modelData.address,
                                                        modelData.connected ? "disconnect" : "connect")
                    }
                }
            }

            PixelText {
                visible: page.bluetoothStatus.length > 0
                text: page.bluetoothStatus
                color: Theme.textDim
            }
        }
    }

    // NO "bars" row. It was drawn, and it could never have worked: the meter is
    // a STEREO one (one bucket per channel) and cava's stereo mode is mirrored,
    // so 4 bars comes back [L-low, L-high, R-high, R-low] — a frequency split,
    // not the channel levels this widget is. VuMeter.qml has the measurement.
    SetSection {
        title: "VU meter (bar)"
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
}

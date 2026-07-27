import QtQuick
import Quickshell

// Text-only system status: a small dim label over a coloured value for each
// metric. No icons, glyphs, or bars — just the pixel font and numbers. Colour
// still carries state (weak signal equivalents, full disk, mute).
Column {
    id: root
    spacing: 6

    // centerY = the module's scene-Y center, so its popup lines up with it
    signal weatherHovered(bool hovering, real centerY)
    signal diskHovered(bool hovering, real centerY)
    signal mediaHovered(bool hovering)
    signal cpuHovered(bool hovering, real centerY)
    signal gpuHovered(bool hovering, real centerY)
    signal ethHovered(bool hovering, real centerY)

    // scene-Y center of an item (bar spans full screen height, so scene Y
    // equals screen Y)
    function _cy(item) { return item.mapToItem(null, item.width / 2, item.height / 2).y; }

    // one dim label + one coloured value, centred. onWheelUp/onWheelDown are
    // optional function-valued properties — set on "bri"/"vol" below for
    // scroll-to-adjust; left null (no-op) everywhere else.
    //
    // Root has to be a plain Item, not a Column: Column forbids anchors on
    // its own children, and the MouseArea below needs anchors.fill to cover
    // the label+value pair for scroll hit-testing — so the label/value
    // Column is a sibling of the MouseArea instead of Stat's root type.
    component Stat: Item {
        property alias label: cap.text
        property alias value: val.text
        property color valueColor: Theme.text
        property var onWheelUp: null
        property var onWheelDown: null
        signal hovered(bool hovering, real centerY)
        // full bar width so the hover/scroll band covers the whole module
        // section, not just the centred text
        width: parent.width
        height: col.implicitHeight

        Column {
            id: col
            anchors.fill: parent
            spacing: 1
            PixelText {
                id: cap
                anchors.horizontalCenter: parent.horizontalCenter
                color: Theme.textDim
            }
            PixelText {
                id: val
                anchors.horizontalCenter: parent.horizontalCenter
                color: valueColor
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onEntered: parent.hovered(true, root._cy(parent))
            onExited: parent.hovered(false, 0)
            // Discrete stepper, so it stays NOTCH-based (a coast should not
            // walk brightness to 0) — but a notch is a fixed amount of scroll,
            // not "one event". WheelNotch.qml has the measurements; without it
            // a touchpad's ~125 Hz stream fired a full step per event and
            // spawned a brightnessctl/wpctl with it. At most one spawn per
            // event by construction: multi-notch bursts are collapsed, not
            // replayed.
            WheelNotch { id: notch }
            onWheel: (wheel) => {
                const n = notch.steps(wheel);
                if (n > 0) {
                    if (onWheelUp) onWheelUp();
                } else if (n < 0) {
                    if (onWheelDown) onWheelDown();
                }
            }
        }
    }

    // ---------- Network (down / up rates) ----------
    Item {
        width: parent.width
        height: ethCol.implicitHeight
        Column {
            id: ethCol
            anchors.fill: parent
            spacing: 1
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "eth"
                color: Theme.textDim
            }
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: SysInfo.fmtSpeed(SysInfo.rxSpeed)
                color: Theme.info
            }
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: SysInfo.fmtSpeed(SysInfo.txSpeed)
                color: Theme.warn
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.ethHovered(true, root._cy(parent))
            onExited: root.ethHovered(false, 0)
        }
    }

    // ---------- CPU (usage / temp) ----------
    Item {
        width: parent.width
        height: cpuCol.implicitHeight
        Column {
            id: cpuCol
            anchors.fill: parent
            spacing: 1
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "cpu"
                color: Theme.textDim
            }
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: SysInfo.cpuUsage < 0 ? "--" : SysInfo.cpuUsage + ""
                color: SysInfo.cpuUsage >= SettingsStore.d.cpuCrit ? Theme.crit
                     : SysInfo.cpuUsage >= SettingsStore.d.cpuWarn ? Theme.warn : Theme.text
            }
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: SysInfo.cpuTemp < 0 ? "--" : SysInfo.cpuTemp + ""
                color: SysInfo.cpuTemp >= SettingsStore.d.tempCrit ? Theme.crit
                     : SysInfo.cpuTemp >= SettingsStore.d.tempWarn ? Theme.warn : Theme.textDim
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.cpuHovered(true, root._cy(parent))
            onExited: root.cpuHovered(false, 0)
        }
    }

    // ---------- GPU (usage / temp) ----------
    // Auto-hides on a host with no nvidia-smi (e.g. book) — SysInfo.gpuUsage
    // stays -1 on every poll there, same hardware-detection pattern as
    // battery's visible check below.
    Item {
        visible: SysInfo.gpuUsage >= 0
        width: parent.width
        height: gpuCol.implicitHeight
        Column {
            id: gpuCol
            anchors.fill: parent
            spacing: 1
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "gpu"
                color: Theme.textDim
            }
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: SysInfo.gpuUsage < 0 ? "--" : SysInfo.gpuUsage + ""
                color: SysInfo.gpuUsage >= SettingsStore.d.cpuCrit ? Theme.crit
                     : SysInfo.gpuUsage >= SettingsStore.d.cpuWarn ? Theme.warn : Theme.text
            }
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: SysInfo.gpuTemp < 0 ? "--" : SysInfo.gpuTemp + ""
                color: SysInfo.gpuTemp >= SettingsStore.d.tempCrit ? Theme.crit
                     : SysInfo.gpuTemp >= SettingsStore.d.tempWarn ? Theme.warn : Theme.textDim
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.gpuHovered(true, root._cy(parent))
            onExited: root.gpuHovered(false, 0)
        }
    }

    // ---------- Disk (free space) ----------
    Stat {
        label: "disk"
        value: SysInfo.fmtSize(SysInfo.diskFreeKb)
        valueColor: SysInfo.diskUsePct >= SettingsStore.d.diskCrit ? Theme.crit
                  : SysInfo.diskUsePct >= SettingsStore.d.diskWarn ? Theme.warn : Theme.text
        onHovered: (h, cy) => root.diskHovered(h, cy)
    }

    // ---------- Battery ----------
    // Auto-hides on a host where sysinfo.sh discovered no system battery
    // (SysInfo.batteryPct stays -1) — no host check needed here, same
    // hardware-detection pattern as bri's useBacklight below. Contrast the
    // task manager's `batt` card, which IS keyed on Host: a card that appeared
    // two seconds after the grid opened would reshuffle it, while a status row
    // that does is just one more row.
    Stat {
        visible: SysInfo.batteryPct >= 0
        // label flips to "chg" while charging — an unmistakable indicator on
        // top of the green value colour (a colour alone is easy to miss when
        // the pack is near full and the normal colour is already light).
        label: SysInfo.batteryCharging ? "chg" : "bat"
        value: SysInfo.batteryPct + ""
        // battery is "lower is worse" — crit/warn below their thresholds,
        // mirroring the cpu/disk stats above
        valueColor: SysInfo.batteryCharging ? Theme.ok
                  : SysInfo.batteryPct <= SettingsStore.d.batteryCrit ? Theme.crit
                  : SysInfo.batteryPct <= SettingsStore.d.batteryWarn ? Theme.warn : Theme.text
    }

    // ---------- Brightness ----------
    Stat {
        label: "bri"
        // Reads negative ("-20") once scrolling past 0 pulls gamma instead.
        value: SysInfo.brightness < 0 ? "--" : SysInfo.brightnessLevel + ""
        valueColor: SysInfo.negativeBrightness ? Theme.crit : Theme.text
        onWheelUp: () => SysInfo.adjustBrightness(SettingsStore.d.brightnessStep)
        onWheelDown: () => SysInfo.adjustBrightness(-SettingsStore.d.brightnessStep)
    }

    // ---------- Stereo output VU (left / right channel) ----------
    // Full bar width like the other modules; its bars/line stay centred.
    // Hovering it slides out the media widget popup.
    VuMeter {
        onHovered: (h) => root.mediaHovered(h)
    }

    // ---------- Volume ----------
    Stat {
        label: "vol"
        value: SysInfo.volume < 0 ? "--" : (SysInfo.muted ? "mute" : SysInfo.volume + "")
        valueColor: SysInfo.muted ? Theme.crit : Theme.text
        onWheelUp: () => SysInfo.adjustVolume(5)
        onWheelDown: () => SysInfo.adjustVolume(-5)
    }

    // ---------- Weather (Juneau) ----------
    // Text-only like everything else: the CONDITION word is the dim label
    // ("rain", "snow", "clr"...) and the value is the temperature — the
    // word itself does the icon's job. Hover slides out the 7-day forecast.
    Item {
        width: parent.width
        height: wxCol.implicitHeight

        Column {
            id: wxCol
            anchors.fill: parent
            spacing: 1
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Weather.cond
                color: Theme.textDim
            }
            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Weather.tempF === -999 ? "--" : Weather.tempF + ""
                color: Weather.tempF !== -999 && Weather.tempF <= 32 ? Theme.info : Theme.text
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.weatherHovered(true, root._cy(parent))
            onExited: root.weatherHovered(false, 0)
        }
    }
}

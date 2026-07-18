import QtQuick
import Quickshell

// Text-only system status: a small dim label over a coloured value for each
// metric. No icons, glyphs, or bars — just the pixel font and numbers. Colour
// still carries state (weak signal equivalents, full disk, mute).
Column {
    id: root
    spacing: 6

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
        anchors.horizontalCenter: parent.horizontalCenter
        width: col.implicitWidth
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
            enabled: onWheelUp !== null || onWheelDown !== null
            onWheel: (wheel) => {
                if (wheel.angleDelta.y > 0) {
                    if (onWheelUp) onWheelUp();
                } else if (wheel.angleDelta.y < 0) {
                    if (onWheelDown) onWheelDown();
                }
            }
        }
    }

    // ---------- Network (down / up rates) ----------
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
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

    // ---------- CPU (usage / temp) ----------
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 1
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "cpu"
            color: Theme.textDim
        }
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: SysInfo.cpuUsage < 0 ? "--" : SysInfo.cpuUsage + ""
            color: SysInfo.cpuUsage >= 90 ? Theme.crit
                 : SysInfo.cpuUsage >= 75 ? Theme.warn : Theme.text
        }
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: SysInfo.cpuTemp < 0 ? "--" : SysInfo.cpuTemp + ""
            color: SysInfo.cpuTemp >= 80 ? Theme.crit
                 : SysInfo.cpuTemp >= 65 ? Theme.warn : Theme.textDim
        }
    }

    // ---------- Disk (free space) ----------
    Stat {
        label: "disk"
        value: SysInfo.fmtSize(SysInfo.diskFreeKb)
        valueColor: SysInfo.diskUsePct >= 90 ? Theme.crit
                  : SysInfo.diskUsePct >= 75 ? Theme.warn : Theme.text
    }

    // ---------- Brightness ----------
    Stat {
        label: "bri"
        value: SysInfo.brightness < 0 ? "--" : SysInfo.brightness + ""
        valueColor: Theme.text
        onWheelUp: () => SysInfo.adjustBrightness(5)
        onWheelDown: () => SysInfo.adjustBrightness(-5)
    }

    // ---------- Volume ----------
    Stat {
        label: "vol"
        value: SysInfo.volume < 0 ? "--" : (SysInfo.muted ? "mute" : SysInfo.volume + "")
        valueColor: SysInfo.muted ? Theme.crit : Theme.text
        onWheelUp: () => SysInfo.adjustVolume(5)
        onWheelDown: () => SysInfo.adjustVolume(-5)
    }
}

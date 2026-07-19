import QtQuick
import Quickshell
import Quickshell.Io

// Disk-usage popup (SlidePopup): one used/total bar per mounted drive
// (internal + external), plus a SMART line for SSDs that report it. Data
// scripts run on open and every 5s while open (SMART can spin a disk up,
// so it's on-demand only).
SlidePopup {
    id: root

    popupNamespace: "qs-disk"
    implicitWidth: 300
    implicitHeight: content.implicitHeight + 20

    onOpened: { usageProc.running = true; smartProc.running = true; }

    property var drives: []  // [{src,label,mount,size,used,rota,model}]
    property var smart: ({}) // "/dev/sdX" -> {health,temp,wear,poh}

    function baseName(mount) {
        if (mount === "/") return "root";
        const p = mount.split("/");
        return p[p.length - 1] || mount;
    }
    function fmtG(bytes) {
        const g = bytes / 1e9;
        if (g >= 1000) return (g / 1000).toFixed(1) + "T";
        return Math.round(g) + "G";
    }

    Process {
        id: usageProc
        command: ["sh", Qt.resolvedUrl("scripts/disk-usage.sh").toString().replace("file://", "")]
        stdout: StdioCollector {
            onStreamFinished: {
                let out = [];
                for (const ln of this.text.trim().split("\n")) {
                    if (!ln) continue;
                    const f = ln.split("|");
                    if (f.length < 7) continue;
                    out.push({ src: f[0], label: f[1], mount: f[2],
                               size: parseFloat(f[3]) || 0, used: parseFloat(f[4]) || 0,
                               rota: f[5] === "1", model: f[6] });
                }
                root.drives = out;
            }
        }
    }
    Process {
        id: smartProc
        command: ["sh", Qt.resolvedUrl("scripts/disk-smart.sh").toString().replace("file://", "")]
        stdout: StdioCollector {
            onStreamFinished: {
                let m = {};
                for (const ln of this.text.trim().split("\n")) {
                    if (!ln) continue;
                    const f = ln.split("|");
                    if (f.length < 5) continue;
                    m[f[0]] = { health: f[1], temp: f[2], wear: f[3], poh: f[4] };
                }
                root.smart = m;
            }
        }
    }
    Timer {
        interval: 5000
        running: root.open
        repeat: true
        onTriggered: { usageProc.running = true; smartProc.running = true; }
    }

    // SMART record for a partition's parent physical drive, or null
    function smartFor(src) {
        for (const dev in root.smart)
            if (src.indexOf(dev) === 0) return root.smart[dev];
        return null;
    }

    Column {
        id: content
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 8

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "disks"
            color: Theme.accent
        }

        Repeater {
            model: root.drives
            Column {
                required property var modelData
                readonly property real pct: modelData.size > 0 ? modelData.used / modelData.size : 0
                readonly property var sm: root.smartFor(modelData.src)
                width: 276
                spacing: 2

                Row {
                    width: parent.width
                    PixelText {
                        width: parent.width - sizeText.width
                        elide: Text.ElideRight
                        text: (modelData.label && modelData.label.length ? modelData.label : root.baseName(modelData.mount))
                              + (modelData.rota ? "" : " •")  // dot marks SSD
                        color: Theme.text
                    }
                    PixelText {
                        id: sizeText
                        text: root.fmtG(modelData.used) + "/" + root.fmtG(modelData.size)
                        color: Theme.textDim
                    }
                }

                // used/total bar
                Rectangle {
                    width: parent.width
                    height: 8
                    color: Theme.bgAlt
                    border.width: 1
                    border.color: Theme.border
                    Rectangle {
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 1 }
                        width: Math.round((parent.width - 2) * parent.parent.pct)
                        color: parent.parent.pct >= 0.9 ? Theme.crit
                             : parent.parent.pct >= 0.75 ? Theme.warn : Theme.accent
                    }
                }

                // SMART line for SSDs that report it
                PixelText {
                    visible: parent.sm !== null
                    text: {
                        const s = parent.sm;
                        if (!s) return "";
                        let bits = [];
                        if (s.health) bits.push(s.health === "PASSED" ? "ok" : "FAIL");
                        if (s.temp) bits.push(s.temp + "C");
                        if (s.wear) bits.push("wear " + s.wear + "%");
                        if (s.poh) bits.push(Math.round(s.poh / 24) + "d on");
                        return "smart: " + bits.join("  ");
                    }
                    color: (parent.sm && parent.sm.health === "FAILED") ? Theme.crit : Theme.textDim
                }
            }
        }

        PixelText {
            visible: root.drives.length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            text: "reading…"
            color: Theme.textDim
        }
    }
}

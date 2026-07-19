import QtQuick
import Quickshell
import Quickshell.Wayland

// Analog clock that slides out when hovering the panel's digital clock —
// same choreography as the Calendar. Drawn on a Canvas in theme colors:
// 12 tick marks, hour/minute hands in text/accent, a thin crit second hand
// ticking while visible.
PanelWindow {
    id: root

    property bool open: false

    visible: open || card.x < card.hidden - 1
    color: "transparent"

    anchors { bottom: true; right: true }
    margins { bottom: Theme.gap * 8; right: Theme.gap }
    implicitWidth: 170
    implicitHeight: 170
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-analog-clock"

    function clockHover(h) {
        if (h) show();
        else closeTimer.restart();
    }
    function show() {
        closeTimer.stop();
        open = true;
        face.requestPaint();
    }
    Timer {
        id: closeTimer
        interval: 350
        onTriggered: root.open = false
    }

    SystemClock {
        id: sc
        precision: SystemClock.Seconds
        onDateChanged: if (root.visible) face.requestPaint()
    }

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        readonly property real shown: 0
        readonly property real hidden: width + Theme.gap
        x: root.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.show()
            onExited: closeTimer.restart()
        }

        Canvas {
            id: face
            anchors.fill: parent
            anchors.margins: 10

            onPaint: {
                const ctx = getContext("2d");
                const w = width, h = height;
                const cx = w / 2, cy = h / 2;
                const r = Math.min(cx, cy) - 4;
                ctx.reset();
                ctx.clearRect(0, 0, w, h);
                ctx.lineCap = "butt";

                // tick marks — longer/brighter at 12/3/6/9
                for (let i = 0; i < 12; i++) {
                    const a = i * Math.PI / 6;
                    const major = i % 3 === 0;
                    const len = major ? 10 : 5;
                    ctx.strokeStyle = major ? Theme.text : Theme.textDim;
                    ctx.lineWidth = major ? 2 : 1;
                    ctx.beginPath();
                    ctx.moveTo(cx + Math.sin(a) * (r - len), cy - Math.cos(a) * (r - len));
                    ctx.lineTo(cx + Math.sin(a) * r, cy - Math.cos(a) * r);
                    ctx.stroke();
                }

                const d = sc.date;
                const hr = (d.getHours() % 12) + d.getMinutes() / 60;
                const mi = d.getMinutes() + d.getSeconds() / 60;
                const se = d.getSeconds();

                function hand(frac, len, wdt, col) {
                    const a = frac * 2 * Math.PI;
                    ctx.strokeStyle = col;
                    ctx.lineWidth = wdt;
                    ctx.beginPath();
                    ctx.moveTo(cx, cy);
                    ctx.lineTo(cx + Math.sin(a) * len, cy - Math.cos(a) * len);
                    ctx.stroke();
                }

                hand(hr / 12, r * 0.50, 3, Theme.text);   // hour
                hand(mi / 60, r * 0.74, 2, Theme.accent); // minute
                hand(se / 60, r * 0.80, 1, Theme.crit);   // second

                // hub
                ctx.fillStyle = Theme.accent;
                ctx.fillRect(cx - 2, cy - 2, 4, 4);
            }
        }
    }
}

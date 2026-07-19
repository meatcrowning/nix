import QtQuick
import Quickshell

// Analog clock popup (SlidePopup: bottom-right, exclusive, hover-kept),
// opened by the clock band of the bar's lower hover strip. Canvas-drawn in
// theme colors: 12 ticks (brighter at the quarters), hour/minute hands in
// text/accent, a thin crit second hand ticking while visible.
SlidePopup {
    id: root

    popupNamespace: "qs-analog-clock"
    implicitWidth: 170
    implicitHeight: 170

    onOpened: face.requestPaint()

    SystemClock {
        id: sc
        precision: SystemClock.Seconds
        onDateChanged: if (root.visible) face.requestPaint()
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

import QtQuick
import Quickshell

// Analog-clock popup — the window around ClockContent.qml, opened by the clock
// band of the bar's lower hover strip. The face repaint and the world-clock
// fetch are gated on `active`, so a closed popup costs nothing.
SlidePopup {
    id: root

    popupNamespace: "qs-analog-clock"
    persistKey: "clock"
    tileRank: 20
    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight

    ClockContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}

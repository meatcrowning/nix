import QtQuick
import Quickshell

// 7-day forecast popup — the window around WeatherContent.qml. Opened by the
// weather block in StatusPanel; the fetch itself belongs to the Weather
// singleton, so this owns nothing but its own geometry.
SlidePopup {
    id: root

    popupNamespace: "qs-weather"
    persistKey: "weather"
    tileRank: 30
    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight

    WeatherContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}

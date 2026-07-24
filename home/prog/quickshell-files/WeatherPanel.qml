import QtQuick
import Quickshell

// 7-day Juneau forecast popup (SlidePopup: bottom-right, exclusive,
// hover-kept), opened by the weather block in StatusPanel. One row per day
// with a labelled footer, sized to content (no empty gap).
SlidePopup {
    id: root

    popupNamespace: "qs-weather"
    persistKey: "weather"
    tileRank: 30
    implicitWidth: 252
    implicitHeight: content.implicitHeight + 20

    Column {
        id: content
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 4

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: SettingsStore.d.weatherPlace
            color: Theme.accent
        }

        Repeater {
            model: Weather.days
            Row {
                required property var modelData
                spacing: 0
                PixelText { width: 44; text: parent.modelData.name;  color: Theme.textDim }
                PixelText { width: 56; text: parent.modelData.cond;  color: Theme.info }
                PixelText { width: 74; text: parent.modelData.hi + "/" + parent.modelData.lo; color: Theme.text }
                PixelText {
                    width: 60
                    text: parent.modelData.prob >= 0 ? parent.modelData.prob + "%" : "-"
                    color: parent.modelData.precip >= 0.05 ? Theme.info : Theme.textDim
                }
            }
        }

        PixelText {
            visible: Weather.days.length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            text: "no data yet"
            color: Theme.textDim
        }

        // column labels, directly under the chart
        Rectangle {
            visible: Weather.days.length > 0
            anchors.horizontalCenter: parent.horizontalCenter
            width: 234
            height: 1
            color: Theme.border
        }
        Row {
            visible: Weather.days.length > 0
            spacing: 0
            PixelText { width: 44; text: "day";   color: Theme.textDim }
            PixelText { width: 56; text: "sky";   color: Theme.textDim }
            PixelText { width: 74; text: "hi/lo"; color: Theme.textDim }
            PixelText { width: 60; text: "rain%"; color: Theme.textDim }
        }
    }
}

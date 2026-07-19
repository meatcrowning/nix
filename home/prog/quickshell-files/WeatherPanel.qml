import QtQuick
import Quickshell

// 7-day redacted-city forecast popup (SlidePopup: bottom-right, exclusive,
// hover-kept), opened by the weather block in StatusPanel. One row per
// day, column labels footed at the bottom.
SlidePopup {
    id: root

    popupNamespace: "qs-weather"
    implicitWidth: 252
    implicitHeight: 8 * 19 + 66

    Column {
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 4

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "redacted-city"
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
                    text: (parent.modelData.precip >= 0.05 ? parent.modelData.precip.toFixed(1) + "\"" : "-")
                          + (parent.modelData.prob >= 0 ? " " + parent.modelData.prob + "%" : "")
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
    }

    // column labels, footed in the leftover space at the bottom
    Column {
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 8 }
        spacing: 3

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 234
            height: 1
            color: Theme.border
        }
        Row {
            spacing: 0
            PixelText { width: 44; text: "day";   color: Theme.textDim }
            PixelText { width: 56; text: "sky";   color: Theme.textDim }
            PixelText { width: 74; text: "hi/lo"; color: Theme.textDim }
            PixelText { width: 60; text: "rain%"; color: Theme.textDim }
        }
    }
}

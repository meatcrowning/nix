import QtQuick
import Quickshell

// Month-calendar popup — the window around CalendarContent.qml, opened by the
// date band of the bar's lower hover strip. The grid rebuilds itself (at
// midnight, and on a week-start change), so there is nothing to refresh here.
SlidePopup {
    id: root

    popupNamespace: "qs-calendar"
    persistKey: "calendar"
    tileRank: 40
    implicitWidth: body.implicitWidth
    // fit the content exactly (a month is 5 or 6 rows) — no empty tail
    implicitHeight: body.implicitHeight

    CalendarContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}

import QtQuick
import Quickshell

// Media-player popup — the window around MediaContent.qml, tiled between the
// disk and clock widgets in the fanned row. MPRIS, the cava spectrum and the
// repeat/shuffle logic all belong to the Media singleton.
SlidePopup {
    id: root

    popupNamespace: "qs-media"
    persistKey: "media"
    tileRank: 25    // between the clock (20) and weather (30)
    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight

    MediaContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}

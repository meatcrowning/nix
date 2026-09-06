import QtQuick
import QtQuick.Controls as QQC

// Goetia's body uses the KDE font when its window is wearing Oxygen.  This is
// deliberately a selector variant: the Hyprland roof keeps the pixel face.
QQC.Label {
    id: root
    textFormat: Text.PlainText
    readonly property bool kdeType: typeof DeskStyle !== "undefined" && DeskStyle
                                    && DeskStyle.plasma === true
    font.family: root.kdeType ? Theme.font : Qt.application.font.family
    font.pixelSize: root.kdeType ? Theme.fontSize : Qt.application.font.pixelSize
    color: root.palette.windowText
}

import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// A small first page, not a fake clone of System Settings: it has one job and
// makes the draft/active distinction explicit.  The controller reports the
// only completion state that matters: the desktop and its live participants
// adopted one generation.
Window {
    id: win
    title: "style"
    width: 980
    height: 700
    minimumWidth: 500
    minimumHeight: 380
    visible: true
    color: Theme.bg

    TextMetrics {
        id: metrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real cellW: metrics.width > 0 ? metrics.width / 10 : Theme.fontSize * 0.53

    component Label: PixelText {
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
    }

    component Button: Rectangle {
        id: button
        property string label: ""
        property bool enabled: true
        property bool emphasis: false
        signal activated()
        implicitWidth: Math.max(96, textItem.implicitWidth + 5 * win.cellW)
        implicitHeight: Theme.lineHeight + Theme.gap
        color: !enabled ? Theme.bg
             : mouse.pressed ? Theme.highlight
             : mouse.containsMouse ? Theme.bgAlt : Theme.bg
        border.width: Theme.ctrlBorder
        border.color: !enabled ? Theme.inactive
                    : emphasis ? Theme.accent
                    : mouse.containsMouse ? Theme.accent : Theme.border
        Label {
            id: textItem
            anchors.centerIn: parent
            text: button.label
            color: !button.enabled ? Theme.inactive : Theme.text
        }
        MouseArea {
            id: mouse
            anchors.fill: parent
            enabled: button.enabled
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: button.activated()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
        border.width: Theme.ctrlBorder
        border.color: Theme.accent
    }

    Column {
        anchors.fill: parent
        anchors.margins: 2 * Theme.gap
        spacing: Theme.gap

        Row {
            id: header
            width: parent.width
            spacing: Theme.gap
            Label { text: "appearance"; color: Theme.accent }
            Label { text: "wallpaper"; color: Theme.textDim }
            Item { width: 1; height: 1 }
            Button {
                anchors.verticalCenter: parent.verticalCenter
                label: "refresh"
                enabled: !Appearance.applying
                onActivated: Appearance.refresh()
            }
        }

        Rectangle { width: parent.width; height: 1; color: Theme.border }

        Row {
            width: parent.width
            spacing: Theme.gap
            Label { text: Appearance.applying ? "applying" : (Appearance.hasDraft ? "draft" : "active")
                     color: Appearance.applying ? Theme.warn : (Appearance.hasDraft ? Theme.accent : Theme.ok) }
            Label { text: Appearance.status; color: Theme.textDim; elide: Text.ElideRight
                     width: Math.max(80, parent.width - 150) }
        }

        Label {
            visible: Appearance.error !== ""
            width: parent.width
            text: Appearance.error
            color: Theme.crit
            wrapMode: Text.Wrap
        }

        Item {
            id: gridFrame
            width: parent.width
            height: Math.max(100, win.height - 180)

            readonly property real tileWidth: Math.max(150, Math.min(250, (width - Theme.gap) / 4))
            readonly property real tileHeight: tileWidth * 0.70 + Theme.lineHeight + Theme.gap

            KineticGridView {
                id: grid
                anchors.fill: parent
                anchors.rightMargin: gridScroll.barW
                model: Appearance.wallpapers
                cellWidth: gridFrame.tileWidth
                cellHeight: gridFrame.tileHeight
                clip: true
                delegate: Item {
                    required property var modelData
                    width: grid.cellWidth
                    height: grid.cellHeight
                    readonly property bool selected: modelData.path === Appearance.draftPath
                    readonly property bool active: modelData.path === Appearance.activePath
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: Theme.gap / 2
                        color: selected ? Theme.bgAlt : Theme.bg
                        border.width: selected ? 2 : 1
                        border.color: selected ? Theme.accent : (active ? Theme.ok : Theme.border)
                        Image {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 1
                            height: parent.height - Theme.lineHeight - Theme.gap - 2
                            source: "file://" + modelData.thumbnail
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            retainWhileLoading: true
                        }
                        Label {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.margins: Theme.gap / 2
                            text: modelData.name
                            color: selected ? Theme.text : Theme.textDim
                            elide: Text.ElideMiddle
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: !Appearance.applying
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Appearance.select(modelData.path)
                        }
                    }
                }
                ScrollBar.vertical: VScroll { id: gridScroll }
            }
            Label {
                anchors.centerIn: parent
                visible: Appearance.wallpapers.length === 0
                text: "no wallpapers in ~/Pictures/wall"
                color: Theme.textDim
            }
        }

        Row {
            id: footer
            width: parent.width
            spacing: Theme.gap
            Label {
                width: Math.max(100, parent.width - applyButton.width - cancelButton.width - 2 * Theme.gap)
                text: Appearance.hasDraft ? "the selected wallpaper will also set the desktop palette" : "the active wallpaper owns the desktop palette"
                color: Theme.textDim
                elide: Text.ElideRight
            }
            Button {
                id: cancelButton
                label: "cancel"
                enabled: Appearance.hasDraft && !Appearance.applying
                onActivated: Appearance.cancel()
            }
            Button {
                id: applyButton
                label: Appearance.applying ? "applying" : "apply"
                emphasis: true
                enabled: Appearance.hasDraft && !Appearance.applying
                onActivated: Appearance.apply()
            }
        }
    }
}

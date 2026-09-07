import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../qmlcommon"

// Style's shared content. Under Plasma this is hosted directly by kdeshell's
// QMainWindow; StyledBackground carries Oxygen's titlebar gradient through the
// window body. Under Hyprland Main.qml supplies the ordinary QML window roof.
Item {
    id: root

    Rectangle {
        anchors.fill: parent
        color: Theme.windowFill
        z: -2
    }
    StyledBackground { anchors.fill: parent; z: -1 }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        ToolBar {
            Layout.fillWidth: true
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                Label { text: "appearance"; font.bold: true }
                Label { text: "wallpaper"; opacity: 0.7 }
                Item { Layout.fillWidth: true }
                ToolButton {
                    text: "refresh"
                    icon.name: "view-refresh"
                    enabled: !Appearance.applying
                    onClicked: Appearance.refresh()
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 10
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: Appearance.applying ? "applying" : (Appearance.hasDraft ? "draft" : "active")
                    font.bold: true
                }
                Label {
                    text: Appearance.status
                    opacity: 0.7
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            Label {
                visible: Appearance.error !== ""
                text: Appearance.error
                color: palette.link
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Frame {
                Layout.fillWidth: true
                Layout.fillHeight: true
                padding: 4

                KineticGridView {
                    id: grid
                    anchors.fill: parent
                    anchors.rightMargin: scrollBar.width
                    model: Appearance.wallpapers
                    readonly property int columns: Math.max(1, Math.floor(width / 210))
                    cellWidth: Math.floor(width / columns)
                    cellHeight: 164
                    clip: true

                    delegate: Item {
                        required property var modelData
                        width: grid.cellWidth
                        height: grid.cellHeight

                        Button {
                            anchors.fill: parent
                            anchors.margins: 4
                            checkable: true
                            checked: modelData.path === Appearance.draftPath
                            enabled: !Appearance.applying
                            onClicked: Appearance.select(modelData.path)

                            contentItem: ColumnLayout {
                                spacing: 4
                                Image {
                                    source: "file://" + modelData.thumbnail
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    retainWhileLoading: true
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                }
                                Label {
                                    text: modelData.name
                                    elide: Text.ElideMiddle
                                    horizontalAlignment: Text.AlignHCenter
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }

                    ScrollBar.vertical: ScrollBar { id: scrollBar }
                }

                Label {
                    anchors.centerIn: parent
                    visible: Appearance.wallpapers.length === 0
                    text: "no wallpapers in ~/Pictures/Wallpapers"
                    opacity: 0.7
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: Appearance.hasDraft
                        ? "the selected wallpaper will also set the desktop palette"
                        : "the active wallpaper owns the desktop palette"
                    opacity: 0.7
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Button {
                    text: "cancel"
                    enabled: Appearance.hasDraft && !Appearance.applying
                    onClicked: Appearance.cancel()
                }
                Button {
                    text: Appearance.applying ? "applying" : "apply"
                    icon.name: "dialog-ok-apply"
                    highlighted: true
                    enabled: Appearance.hasDraft && !Appearance.applying
                    onClicked: Appearance.apply()
                }
            }
        }
    }
}

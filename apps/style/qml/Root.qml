import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../../qmlcommon"

// Style's shared content. Under Plasma this is hosted directly by kdeshell's
// QMainWindow; StyledBackground carries Oxygen's titlebar gradient through the
// window body. Under Hyprland Main.qml supplies the ordinary QML window roof.
Item {
    id: root
    focus: true
    property var selectedPaths: []
    property string selectionAnchor: ""

    function isSelected(path) { return selectedPaths.indexOf(path) >= 0 }
    function selectOnly(path) {
        selectedPaths = [path]
        selectionAnchor = path
        Appearance.select(path)
    }
    function selectToggle(path) {
        var next = selectedPaths.slice()
        var index = next.indexOf(path)
        if (index >= 0) next.splice(index, 1); else next.push(path)
        selectedPaths = next
        selectionAnchor = path
        if (index < 0) Appearance.select(path)
    }
    function selectRange(path) {
        var start = -1
        var end = -1
        for (var i = 0; i < Appearance.wallpapers.length; i++) {
            if (Appearance.wallpapers[i].path === selectionAnchor) start = i
            if (Appearance.wallpapers[i].path === path) end = i
        }
        if (start < 0 || end < 0) { selectOnly(path); return }
        var next = []
        for (var j = Math.min(start, end); j <= Math.max(start, end); j++)
            next.push(Appearance.wallpapers[j].path)
        selectedPaths = next
        Appearance.select(path)
    }
    function clickSelect(path, modifiers) {
        if (modifiers & Qt.ShiftModifier) selectRange(path)
        else if (modifiers & Qt.ControlModifier) selectToggle(path)
        else selectOnly(path)
    }
    function deleteSelection() {
        if (selectedPaths.length > 0 && !Appearance.applying)
            Appearance.removeWallpapers(selectedPaths)
    }
    function selectAll() {
        var next = []
        for (var i = 0; i < Appearance.wallpapers.length; i++)
            next.push(Appearance.wallpapers[i].path)
        selectedPaths = next
        if (next.length > 0) selectionAnchor = next[0]
    }

    Shortcut { sequence: "Delete"; enabled: selectedPaths.length > 0; onActivated: root.deleteSelection() }
    Shortcut { sequence: StandardKey.SelectAll; onActivated: root.selectAll() }
    Component.onCompleted: {
        if (Appearance.draftPath !== "") selectedPaths = [Appearance.draftPath]
    }

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
                ToolButton {
                    text: "dark"
                    checkable: true
                    checked: Appearance.activeScheme === "OxygenDarkFlat"
                    enabled: !Appearance.applying
                    onClicked: Appearance.selectScheme("OxygenDarkFlat")
                }
                ToolButton {
                    text: "light"
                    checkable: true
                    checked: Appearance.activeScheme === "OxygenLightFlat"
                    enabled: !Appearance.applying
                    onClicked: Appearance.selectScheme("OxygenLightFlat")
                }
                Item { Layout.fillWidth: true }
                ToolButton {
                    text: "add"
                    icon.name: "list-add"
                    enabled: !Appearance.applying
                    onClicked: importDialog.open()
                }
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
                            checked: root.isSelected(modelData.path)
                            enabled: !Appearance.applying

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
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function(mouse) {
                                root.forceActiveFocus()
                                if (mouse.button === Qt.RightButton) {
                                    if (!root.isSelected(modelData.path)) root.selectOnly(modelData.path)
                                    var point = mapToItem(root, mouse.x, mouse.y)
                                    contextMenu.open(point.x, point.y, [
                                        { label: root.selectedPaths.length > 1
                                                 ? "delete " + root.selectedPaths.length + " wallpapers"
                                                 : "delete",
                                          trigger: function() { root.deleteSelection() } }
                                    ])
                                } else {
                                    root.clickSelect(modelData.path, mouse.modifiers)
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
                    text: selectedPaths.length > 1 ? "delete " + selectedPaths.length : "delete"
                    icon.name: "edit-delete"
                    enabled: selectedPaths.length > 0 && !Appearance.applying
                    onClicked: root.deleteSelection()
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

    FileDialog {
        id: importDialog
        title: "add wallpapers"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["images (*.png *.jpg *.jpeg *.webp *.bmp)"]
        onAccepted: Appearance.importFiles(selectedFiles)
    }

    Connections {
        target: Appearance
        function onSelectionChanged() {
            if (Appearance.applying && Appearance.draftPath !== "")
                selectedPaths = [Appearance.draftPath]
        }
        function onWallpapersChanged() {
            var offered = []
            for (var i = 0; i < Appearance.wallpapers.length; i++)
                offered.push(Appearance.wallpapers[i].path)
            selectedPaths = selectedPaths.filter(function(path) { return offered.indexOf(path) >= 0 })
        }
    }

    CtxMenu { id: contextMenu; anchors.fill: parent }

    Popup {
        id: applyingPopup
        parent: Overlay.overlay
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        width: 280
        height: 94
        modal: true
        focus: true
        closePolicy: Popup.NoAutoClose
        visible: Appearance.applying && !Appearance.nativeProgress
        padding: 12

        contentItem: ColumnLayout {
            spacing: 7
            Label { text: "applying"; font.bold: true }
            RowLayout {
                Layout.fillWidth: true
                BusyIndicator {
                    running: Appearance.applying
                    Layout.preferredWidth: 20
                    Layout.preferredHeight: 20
                }
                Label {
                    text: Appearance.status
                    opacity: 0.7
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
            ProgressBar {
                Layout.fillWidth: true
                indeterminate: true
                value: 0
            }
        }
    }
}

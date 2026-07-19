import QtQuick
import Quickshell
import Quickshell.Widgets
import Quickshell.Wayland

// Program runner. Spawns beside the bar's launcher button.
PanelWindow {
    id: launcher

    property bool open: false

    // Stay mapped through the slide-out so the close animation can play out,
    // then hide once the card has travelled back off the right edge — matching
    // the Cheatsheet.
    visible: open || card.x < card.hidden - 1
    color: "transparent"

    // Sit at the top-right, just left of the bar, so it reads as spawning
    // out of the launcher button.
    anchors { top: true; right: true }
    margins.top: Theme.gap
    // The bar's exclusive zone already reserves its width; this gap sits
    // between the launcher's right edge and the bar, matching margins.top.
    margins.right: Theme.gap
    implicitWidth: 300
    implicitHeight: 460
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-launcher"
    // OnDemand (not Exclusive): the runner accepts keyboard input but never
    // fully steals focus, so you can click into a window and back again. Tie
    // this to `visible` (not `open`) so the layer keeps keyboard focus through
    // the slide-out and only releases it as it unmaps (see Cheatsheet).
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    // ----- data -----
    property var results: []
    property int selected: 0

    function rebuild() {
        const q = input.text.trim().toLowerCase();
        const apps = DesktopEntries.applications.values;
        let list = [];
        for (let i = 0; i < apps.length; i++) {
            const a = apps[i];
            if (a.noDisplay) continue;
            const name = (a.name || "").toLowerCase();
            if (q === "" || name.includes(q))
                list.push(a);
        }
        list.sort((x, y) => (x.name || "").localeCompare(y.name || ""));
        results = list;
        selected = 0;
    }

    function launch(entry) {
        if (!entry) return;
        // Launching an app is an action -> Vista click.
        Sounds.play("Windows Navigation Start.wav");
        entry.execute();
        close();
    }

    function close() {
        open = false;
    }

    onOpenChanged: {
        if (open) {
            input.text = "";
            rebuild();
            input.forceActiveFocus();
        }
    }

    Rectangle {
        id: card
        // Full window height, docked to the right — the edge it slides out from.
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        // Slide in horizontally from the right edge — out from behind the bar.
        // Open: flush against the window's right edge. Closed: fully off the
        // right (a full width to the right, so it tucks behind the panel).
        readonly property real shown: 0
        readonly property real hidden: width
        x: launcher.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        // Clicking anywhere in the runner returns typing focus to the search box
        // (handy after focusing a window and clicking back).
        MouseArea {
            anchors.fill: parent
            onClicked: input.forceActiveFocus()
        }

        Column {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            // search box
            Rectangle {
                width: parent.width
                height: 34
                color: Theme.bgAlt
                border.color: Theme.border
                border.width: 1
                radius: 2

                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: 6

                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: ">"
                        color: Theme.accent
                    }
                    TextInput {
                        id: input
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 20
                        color: Theme.text
                        font.family: Theme.font
                        font.pixelSize: Theme.fontSize
                        font.hintingPreference: Font.PreferFullHinting
                        renderType: Text.NativeRendering
                        clip: true
                        focus: true
                        selectByMouse: true
                        onTextChanged: launcher.rebuild()

                        Keys.onPressed: (event) => {
                            if (event.key === Qt.Key_Down) {
                                launcher.selected = Math.min(launcher.selected + 1, launcher.results.length - 1);
                                event.accepted = true;
                            } else if (event.key === Qt.Key_Up) {
                                launcher.selected = Math.max(launcher.selected - 1, 0);
                                event.accepted = true;
                            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                launcher.launch(launcher.results[launcher.selected]);
                                event.accepted = true;
                            } else if (event.key === Qt.Key_Escape) {
                                launcher.close();
                                event.accepted = true;
                            }
                        }

                        // placeholder
                        PixelText {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: input.text === ""
                            text: "search programs"
                            font: input.font
                            color: Theme.textDim
                        }
                    }
                }
            }

            // results
            ListView {
                id: list
                width: parent.width
                height: parent.height - 42
                clip: true
                model: launcher.results
                currentIndex: launcher.selected
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                boundsBehavior: Flickable.StopAtBounds

                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: list.width
                    height: 32
                    color: index === launcher.selected ? Theme.highlight : "transparent"
                    radius: 2

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        spacing: 8

                        IconImage {
                            anchors.verticalCenter: parent.verticalCenter
                            implicitSize: 22
                            source: Quickshell.iconPath(modelData.icon, "application-x-executable")
                        }
                        PixelText {
                            anchors.verticalCenter: parent.verticalCenter
                            width: list.width - 40
                            text: modelData.name
                            elide: Text.ElideRight
                            color: Theme.text
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: launcher.launch(modelData)
                        onEntered: launcher.selected = index
                        hoverEnabled: true
                    }
                }
            }
        }
    }
}

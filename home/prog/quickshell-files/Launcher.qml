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

    // 0 for our own programs, 1 for everything else — the primary sort key.
    function rank(entry) {
        const kw = entry.keywords || [];
        for (let i = 0; i < kw.length; i++)
            if (String(kw[i]).toLowerCase() === "bespoke") return 0;
        return 1;
    }

    function rebuild() {
        const q = input.text.trim().toLowerCase();
        let list = [];
        // Desktop-apps provider (toggleable).
        if (SettingsStore.d.launcherProviderApps) {
            const apps = DesktopEntries.applications.values;
            for (let i = 0; i < apps.length; i++) {
                const a = apps[i];
                if (a.noDisplay) continue;
                const name = (a.name || "").toLowerCase();
                if (q === "" || name.includes(q))
                    list.push(a);
            }
            // The desktop's own programs (filer, player, painter, surfer,
            // viewer, settings — everything tagged `Keywords=bespoke;` in its
            // .desktop file) sort ahead of the distro's, alphabetical within
            // each group. They're what this runner is mostly for, and it also
            // means the result cap below never drops them.
            list.sort((x, y) => rank(x) - rank(y)
                             || (x.name || "").localeCompare(y.name || ""));
        }
        // Cap the result count (0 = unlimited).
        const cap = SettingsStore.d.launcherMaxResults;
        if (cap > 0 && list.length > cap)
            list = list.slice(0, cap);
        results = list;
        selected = 0;
    }

    function launch(entry) {
        if (!entry) return;
        // Terminal apps launch inside the configured terminal emulator; the
        // rest run directly. entry.command is the parsed argv (field codes
        // stripped), spliced after the terminal's exec flag.
        if (entry.runInTerminal)
            Quickshell.execDetached([SettingsStore.d.launcherTerminal, "-e"].concat(entry.command));
        else
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
        Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

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
                            text: SettingsStore.d.launcherPlaceholder
                            font: input.font
                            color: Theme.textDim
                        }
                    }
                }
            }

            // results
            KineticListView {
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
                    // hug the (now 18px) app icon — was a fixed 32 around a 22px
                    // icon, i.e. ~10px of dead vertical space per result row
                    height: Theme.fontSize + 5
                    color: index === launcher.selected ? Theme.highlight : "transparent"
                    radius: 2

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        spacing: 8

                        IconImage {
                            anchors.verticalCenter: parent.verticalCenter
                            implicitSize: 18
                            source: Quickshell.iconPath(modelData.icon, "application-x-executable")
                        }
                        PixelText {
                            anchors.verticalCenter: parent.verticalCenter
                            width: list.width - 40
                            // Label only. The search above still matches on the
                            // raw `name`, and `entry.command` — the argv that
                            // actually gets executed — never comes near this.
                            text: Glyphs.px(modelData.name)
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

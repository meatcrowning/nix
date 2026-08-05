import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets
import Quickshell.Wayland

// THE ICON BAR, SLID OUT. This is the shortcut notch (DesktopNotch.qml /
// NotchModel.qml) opened into a drawer: the same seals, in the same order, now
// carrying their names — and beside them a runner for EVERY OTHER program on
// the system. [his] "the icon bar on the left side of the panel to slide out,
// revealing a program runner. to the right of the icons when that bar is slid
// out will show the names of the icons, the program runner will be for every
// other program on the system."
//
// TWO COLUMNS, seals on the left and the runner on the right — his pick, and the
// reason the seals are NOT in the runner's list: the notch is the desktop's own
// programs, the runner is everything else, and neither repeats the other.
//
// IT IS ITS OWN SURFACE, not part of the bar. The notch lives inside the bar's
// layer surface so its outline and the bar's accent strip share one coordinate
// space during a width drag; a drawer this wide cannot, because the bar's
// surface width is a constant the exclusive zone is derived from (shell.qml).
// So this is an Overlay-layer card whose right edge sits exactly on the panel's
// face: fully open it covers the notch it grew out of, and its own outline is
// the notch's — three accent sides with the panel-facing one left open, so the
// drawer opens INTO the panel exactly as the notch does.
//
// HOTKEY ONLY. There is no runner button any more (removed from the classic
// bar's top cluster and from DockHeader): mainMod+Super, which is
// `qs ipc call launcher toggle` in hyprland.lua.
PanelWindow {
    id: launcher

    property bool open: false

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"

    // Stay mapped through the slide-out so the close animation can play out,
    // then hide once the card has travelled back off the panel-side edge —
    // matching the Cheatsheet.
    visible: open || Math.abs(card.x - card.hidden) > 1
    color: "transparent"

    // Full height, hard against the panel's face — the notch's own mouth. The
    // card inside is what has a height, and it is centred on the screen like
    // the notch is, so the drawer grows out of it rather than beside it.
    anchors { top: true; bottom: true; left: launcher.barLeft; right: !launcher.barLeft }
    margins.right: 0
    margins.left: 0
    implicitWidth: card.width
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

    // Is this one of the desktop's own programs? `Keywords=bespoke;` on the
    // entry — the same test NotchModel uses to decide what is in the notch, so
    // the two halves of this drawer partition the system's programs between
    // them with nothing counted twice and nothing dropped.
    function bespoke(entry) {
        const kw = entry.keywords || [];
        for (let i = 0; i < kw.length; i++)
            if (String(kw[i]).toLowerCase() === "bespoke") return true;
        return false;
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
                // EVERY OTHER PROGRAM: the seals have their own column an inch
                // to the left, so listing them here again would be the same
                // icon twice on one card.
                if (bespoke(a)) continue;
                const name = (a.name || "").toLowerCase();
                if (q === "" || name.includes(q))
                    list.push(a);
            }
            list.sort((x, y) => (x.name || "").localeCompare(y.name || ""));
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
        // NixPath.launch, not execDetached/entry.execute(): both of those leave
        // the app inside quickshell-panel.service's cgroup, where a panel
        // restart kills it. See NixPath.launch.
        if (entry.runInTerminal)
            NixPath.launch([SettingsStore.d.launcherTerminal, "-e"].concat(entry.command));
        else
            NixPath.launch(entry.command);
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

    // Clicking the strip beside the card (above or below it) closes, the same
    // way Escape does.
    MouseArea {
        anchors.fill: parent
        onClicked: launcher.close()
    }

    Rectangle {
        id: card

        // ---- geometry -----------------------------------------------------
        // The seal column is the notch's own column plus room for a name; the
        // runner is the wider half, because it is the one holding a search box
        // and a hundred elided program names.
        readonly property int pad: NotchModel.gap
        readonly property int sealW: 168
        readonly property int runW: 264
        readonly property int lineW: Theme.windowBorderWidth

        width: pad * 2 + sealW + pad * 2 + 1 + runW
        // Tall enough for a useful list, never taller than the screen, and
        // never shorter than the notch it grew from.
        height: Math.min(launcher.screen ? launcher.screen.height - 2 * Theme.gap : 460,
                         Math.max(NotchModel.slabH, 460))
        anchors.verticalCenter: parent.verticalCenter

        // Slide out from behind the panel — open: flush against the window's
        // panel-side edge; closed: a full width back behind it.
        readonly property real shown: 0
        readonly property real hidden: launcher.barLeft ? -width : width
        x: launcher.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

        color: Theme.bg

        // ---- the outline: three sides, like the notch ----------------------
        // The panel-facing side carries none, so the drawer reads as opening
        // into the panel rather than sitting against it as a box (see
        // DesktopNotch.qml, which this is the slid-out form of).
        Rectangle {   // the desktop-facing side
            x: launcher.barLeft ? card.width - card.lineW : 0
            width: card.lineW
            height: card.height
            color: Theme.accent
        }
        Rectangle {   // top
            width: card.width
            height: card.lineW
            color: Theme.accent
        }
        Rectangle {   // bottom
            y: card.height - card.lineW
            width: card.width
            height: card.lineW
            color: Theme.accent
        }

        // Clicking anywhere in the drawer returns typing focus to the search
        // box (handy after focusing a window and clicking back).
        MouseArea {
            anchors.fill: parent
            onClicked: input.forceActiveFocus()
        }

        // ================= the seals, with their names =====================
        // The notch's column, in the notch's order, at the notch's spacing —
        // what changes when it slides out is only that each one gets its name.
        KineticFlickable {
            id: sealScroll
            anchors {
                left: parent.left; top: parent.top; bottom: parent.bottom
                leftMargin: card.pad + card.lineW; topMargin: card.pad + card.lineW
                bottomMargin: card.pad + card.lineW
            }
            width: card.sealW
            clip: true
            contentHeight: seals.height
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: seals
                width: sealScroll.width
                spacing: NotchModel.gap

                Repeater {
                    model: NotchModel.apps

                    delegate: Item {
                        id: seal
                        required property var modelData

                        width: seals.width
                        height: NotchModel.iconSize

                        // The hover fill is drawn AROUND the row rather than
                        // being the thing the layout spaces — same rule as the
                        // notch, so the gaps stay the notch's gaps.
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width + 8
                            height: NotchModel.hitSize
                            radius: Theme.windowRounding
                            visible: sealHover.containsMouse
                            color: Theme.highlight
                        }

                        AppIcon {
                            id: sealIcon
                            anchors.left: parent.left
                            width: NotchModel.iconSize
                            height: NotchModel.iconSize
                            iconName: seal.modelData.icon
                            // The focus colour, like every other program icon
                            // on this desktop (docs/DESIGN.md §12.2.1).
                            color: Theme.accent
                        }

                        PixelText {
                            anchors {
                                left: sealIcon.right; leftMargin: NotchModel.gap
                                right: parent.right
                                verticalCenter: parent.verticalCenter
                            }
                            // Label only — `entry.command`, the argv that
                            // actually runs, never comes near this.
                            text: Glyphs.px(seal.modelData.name || "")
                            elide: Text.ElideRight
                            color: Theme.text
                        }

                        MouseArea {
                            id: sealHover
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: launcher.launch(seal.modelData)
                        }
                    }
                }
            }
        }

        // the divider between the two halves
        Rectangle {
            id: split
            anchors {
                left: sealScroll.right; leftMargin: card.pad
                top: parent.top; bottom: parent.bottom
                topMargin: card.pad + card.lineW; bottomMargin: card.pad + card.lineW
            }
            width: 1
            color: Theme.border
        }

        // ================= the runner: everything else =====================
        Column {
            anchors {
                left: split.right; leftMargin: card.pad
                right: parent.right; rightMargin: card.pad
                top: parent.top; topMargin: card.pad + card.lineW
                bottom: parent.bottom; bottomMargin: card.pad + card.lineW
            }
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

                        // Never drawn straight: AppIcon tints every icon to the
                        // accent — the focus colour a hyprvtb titlebar gives
                        // the same program. Our own seals land on it EXACTLY
                        // only because their currentColor fallback is white:
                        // colorization scales the tint by the source's own
                        // luminance, so against the old #cc4400 fallback a seal
                        // came out at 36% of the tint (measured), which is what
                        // made the runner's icons read dull and dark.
                        AppIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 18
                            height: 18
                            iconName: modelData.icon
                            color: Theme.accent
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

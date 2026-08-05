import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets
import Quickshell.Wayland

// THE ICON BAR, PULLED OUT. This is the shortcut notch (DesktopNotch.qml /
// NotchModel.qml) pulled away from the panel: the slab moves, and what comes
// out from behind the panel behind it is the runner.
//
// THE MOTION IS THE WHOLE POINT, and it took three attempts to get right. What
// he asked for is [his] "the bar itself pulls out to reveal the runner - the bar
// itself appearing unchanged in its normal state", and then, of attempt two,
// [his] "its still as if a second bar is appearing and exploding out from the
// original bar. it should appear as if the bar literally moves to the left and
// reveals a program runner. in addition it should not grow in height".
//
// SO NOTHING RESIZES. THIS IS A DRAWER. One rigid card, `openW` wide and the
// notch's own height, that only ever TRANSLATES:
//
//   * CLOSED, its leading edge is the notch and the rest of it is behind the
//     panel — clipped away at the panel's face by `frame`, which is the whole
//     illusion. The visible strip is `closedW` = NotchModel.protrusion wide,
//     the notch's height, with the notch's outline and the seals at the notch's
//     inset. Pixel for pixel the notch, so the surface can map and unmap under
//     it with nothing to see.
//   * OPENING, it slides out by `openW - closedW`. The seals ride it because
//     they are part of it; the names and the runner emerge from behind the
//     panel because they are further back in the same drawer. Nothing fades,
//     nothing grows, nothing spawns.
//
// Do NOT reintroduce an animated width, height or opacity here. An animated
// width was attempt two and read as "a second bar exploding out of the first";
// an animated height was the same mistake on the other axis. The reveal is the
// clip, and the only animated property in this file is `x`.
//
// The columns, left to right: the seals (the desktop's own programs, tagged
// `Keywords=bespoke;`), each with its NAME beside it, then the runner — search
// box over every OTHER program on the system. A partition, so neither side
// repeats the other.
//
// IT IS ITS OWN SURFACE, not part of the bar, and that is forced: the notch
// lives inside the bar's layer surface so their outlines share one coordinate
// space during a width drag, but the bar's surface width is the constant the
// exclusive zone derives from, and this drawer is far too wide to add to it. So
// it is an Overlay surface whose right edge sits on the panel's face, covering
// the notch for as long as it is out.
//
// HOTKEY ONLY. There is no runner button any more (removed from the classic
// bar's top cluster and from DockHeader): mainMod+Super, which is
// `qs ipc call launcher toggle` in hyprland.lua.
PanelWindow {
    id: launcher

    property bool open: false

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"

    // Mapped for as long as the drawer is out — gated on the CARD, not on
    // `open`, so it travels all the way home before the surface goes. Closed it
    // is identical to the notch underneath it, so the unmap is invisible.
    visible: open || Math.abs(card.x - card.closedX) > 1
    color: "transparent"

    // Full height, hard against the panel's face — the notch's own mouth.
    anchors { top: true; bottom: true; left: launcher.barLeft; right: !launcher.barLeft }
    margins.right: 0
    margins.left: 0
    implicitWidth: card.openW
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-launcher"
    // OnDemand (not Exclusive): the runner accepts keyboard input but never
    // fully steals focus, so you can click into a window and back again. Tie
    // this to `visible` (not `open`) so the layer keeps keyboard focus through
    // the pull and only releases it as it unmaps (see Cheatsheet).
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
                // EVERY OTHER PROGRAM: the seals are in the drawer's own column,
                // so listing them here too would be the same icon twice.
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

    // Clicking the strip beside the drawer (above or below it) closes, the same
    // way Escape does.
    MouseArea {
        anchors.fill: parent
        onClicked: launcher.close()
    }

    // THE PANEL'S FACE, as a clip. Everything of the drawer that has not been
    // pulled out yet is behind this edge and simply not drawn.
    Item {
        id: frame
        anchors.fill: parent
        clip: true

        Rectangle {
            id: card

            // ---- geometry: rigid, and closed IS the notch -------------------
            readonly property int pad: NotchModel.gap
            readonly property int lineW: Theme.windowBorderWidth
            // The strip that is the notch: exactly what the panel reserves for
            // it, so the closed drawer and the notch are the same object. With
            // the notch turned off (`desktopIcons`) there is nothing to match
            // and both fall back to sane numbers — the drawer then comes
            // straight out of the panel's edge with no seal column.
            readonly property int closedW: NotchModel.protrusion
            readonly property int nameW: 132
            readonly property int runW: 264
            readonly property int openW: NotchModel.columnInset + NotchModel.iconSize
                                       + NotchModel.gap + nameW
                                       + pad + 1 + pad + runW + pad

            // NO HEIGHT ANIMATION, EVER: [his] "it should not grow in height".
            // The drawer is the notch's height, so the runner lives in whatever
            // the seal column comes to — which is what makes the whole thing
            // read as one object being moved rather than opened.
            width: openW
            height: NotchModel.shown ? NotchModel.slabH : 300
            anchors.verticalCenter: parent.verticalCenter

            // Closed: pushed back until only the notch strip is this side of the
            // panel's face. Open: fully out. The ONE animated property here.
            readonly property real closedX: launcher.barLeft ? closedW - openW : openW - closedW
            readonly property real openX: 0
            x: launcher.open ? openX : closedX
            // The desktop's own slide (docs/DESIGN.md §6.2) — the one a window
            // rolls at, and the one the notch's seals already move at.
            Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

            color: Theme.bg

            // Clicking anywhere in the drawer returns typing focus to the search
            // box (handy after focusing a window and clicking back).
            MouseArea {
                anchors.fill: parent
                onClicked: input.forceActiveFocus()
            }

            // ================= the seals, with their names =====================
            // The notch's column, at the notch's inset off the leading edge and
            // centred as the notch centres it — so at rest the icons are where
            // they have always been, and the drawer's travel is the only thing
            // that ever moves them.
            Column {
                id: seals
                spacing: NotchModel.gap

                // The notch shifts its seals when a window is flush against it
                // (NotchModel.columnInsetFlush). Closed, this has to agree with
                // it to the pixel or the icons twitch as the drawer takes over
                // from the notch; open, there is no window against anything and
                // the normal inset applies.
                property int inset: (!launcher.open && NotchModel.flushOn(launcher.screen))
                    ? NotchModel.columnInsetFlush : NotchModel.columnInset
                Behavior on inset { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

                anchors {
                    left: launcher.barLeft ? undefined : parent.left
                    right: launcher.barLeft ? parent.right : undefined
                    leftMargin: launcher.barLeft ? 0 : inset
                    rightMargin: launcher.barLeft ? inset : 0
                    verticalCenter: parent.verticalCenter
                }
                width: NotchModel.iconSize + NotchModel.gap + card.nameW

                Repeater {
                    model: NotchModel.apps

                    delegate: Item {
                        id: seal
                        required property var modelData

                        width: seals.width
                        height: NotchModel.iconSize

                        // The hover fill is drawn AROUND the row rather than
                        // being the thing the layout spaces — the notch's rule,
                        // so the gaps stay the notch's gaps.
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
                            anchors.left: launcher.barLeft ? undefined : parent.left
                            anchors.right: launcher.barLeft ? parent.right : undefined
                            width: NotchModel.iconSize
                            height: NotchModel.iconSize
                            iconName: seal.modelData.icon
                            // The focus colour, like every other program icon
                            // on this desktop (docs/DESIGN.md §12.2.1).
                            color: Theme.accent
                        }

                        // The name, further back in the drawer than its icon —
                        // so it comes out from behind the panel as the bar is
                        // pulled, rather than fading in on top of it.
                        PixelText {
                            anchors {
                                left: launcher.barLeft ? parent.left : sealIcon.right
                                right: launcher.barLeft ? sealIcon.left : parent.right
                                leftMargin: launcher.barLeft ? 0 : NotchModel.gap
                                rightMargin: launcher.barLeft ? NotchModel.gap : 0
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

            // the divider between the two halves
            Rectangle {
                id: split
                anchors {
                    left: launcher.barLeft ? undefined : seals.right
                    right: launcher.barLeft ? seals.left : undefined
                    leftMargin: launcher.barLeft ? 0 : card.pad
                    rightMargin: launcher.barLeft ? card.pad : 0
                    top: parent.top; bottom: parent.bottom
                    topMargin: card.pad + card.lineW; bottomMargin: card.pad + card.lineW
                }
                width: 1
                color: Theme.border
            }

            // ================= the runner: everything else =====================
            Column {
                anchors {
                    left: launcher.barLeft ? parent.left : split.right
                    right: launcher.barLeft ? split.left : parent.right
                    leftMargin: launcher.barLeft ? card.pad : card.pad
                    rightMargin: launcher.barLeft ? card.pad : card.pad
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
                        // hug the (now 18px) app icon — was a fixed 32 around a
                        // 22px icon, i.e. ~10px of dead vertical space per row
                        height: Theme.fontSize + 5
                        color: index === launcher.selected ? Theme.highlight : "transparent"
                        radius: 2

                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            spacing: 8

                            // Never drawn straight: AppIcon tints every icon to
                            // the accent — the focus colour a hyprvtb titlebar
                            // gives the same program. Our own seals land on it
                            // EXACTLY only because their currentColor fallback
                            // is white: colorization scales the tint by the
                            // source's own luminance, so against the old
                            // #cc4400 fallback a seal came out at 36% of the
                            // tint (measured), which is what made the runner's
                            // icons read dull and dark.
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
                                // Label only. The search above still matches on
                                // the raw `name`, and `entry.command` — the argv
                                // that actually gets executed — never comes near
                                // this.
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

            // ---- the outline: three sides, the notch's own ------------------
            // Drawn last, so it frames the whole drawer as ONE object. The
            // panel-facing side carries no line — the drawer opens INTO the
            // panel, exactly as the notch does (DesktopNotch.qml).
            Rectangle {   // the desktop-facing side: the drawer's leading edge
                z: 2
                x: launcher.barLeft ? card.width - card.lineW : 0
                width: card.lineW
                height: card.height
                color: Theme.accent
            }
            Rectangle {   // top
                z: 2
                width: card.width
                height: card.lineW
                color: Theme.accent
            }
            Rectangle {   // bottom
                z: 2
                y: card.height - card.lineW
                width: card.width
                height: card.lineW
                color: Theme.accent
            }
        }
    }
}

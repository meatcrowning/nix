import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets
import Quickshell.Wayland

// THE ICON BAR, PULLED OUT. This is the shortcut notch (DesktopNotch.qml /
// NotchModel.qml) opened into a drawer: the slab itself travels away from the
// panel, carrying its seals, and the space it uncovers IS the runner.
//
// THE MOTION IS THE WHOLE POINT, and it is the second attempt. The first slid a
// separate card in over the notch, which [his] "appear[ed] as if a disjointed
// phantom runner appearing as if out of nowhere" — what he asked for is "the
// bar itself pulls out to reveal the runner - the bar itself appearing
// unchanged in its normal state. only changing when the runner is activated".
// So:
//
//   * CLOSED, THIS CARD IS PIXEL-FOR-PIXEL THE NOTCH. Same width
//     (NotchModel.protrusion), same height (slabH), same centring, same
//     three-sided accent outline, seals at the same inset. It maps and unmaps
//     behind that identity, so nothing appears or vanishes.
//   * OPENING, the RIGHT edge stays welded to the panel's face and the LEFT
//     edge travels outward. The slab rides that left edge — the seals go with
//     it, exactly as if the notch were being pulled — and the widening gap
//     between the slab and the panel is the runner, revealed rather than
//     flown in.
//   * The slab widens as it goes (protrusion -> sealW) so each seal's NAME has
//     somewhere to be: to the right of its icon, which is where he asked for it.
//
// TWO COLUMNS at rest-open: seals on the left, the runner on the right. The
// seals are the desktop's own programs (`Keywords=bespoke;`) and the runner is
// EVERY OTHER program on the system — a partition, so neither repeats the other.
//
// IT IS ITS OWN SURFACE, not part of the bar, and that is forced: the notch
// lives inside the bar's layer surface so their outlines share one coordinate
// space during a width drag, but the bar's surface width is the constant the
// exclusive zone derives from, and this is far too wide to add to it. So it is
// an Overlay card whose right edge sits on the panel's face, covering the notch
// it grew out of for as long as it is out.
//
// HOTKEY ONLY. There is no runner button any more (removed from the classic
// bar's top cluster and from DockHeader): mainMod+Super, which is
// `qs ipc call launcher toggle` in hyprland.lua.
PanelWindow {
    id: launcher

    property bool open: false

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"

    // Mapped for as long as the pull is happening — gated on the CARD, not on
    // `open`, so the slab travels all the way home before the surface goes.
    // Closed it is identical to the notch underneath it, so the unmap is
    // invisible; while it is out, the notch is behind it.
    visible: open || card.width > card.closedW + 1
    color: "transparent"

    // Full height, hard against the panel's face — the notch's own mouth. The
    // card inside carries the height and is centred like the notch is.
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
                // EVERY OTHER PROGRAM: the seals are on the slab an inch to the
                // left, so listing them here too would be the same icon twice.
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

        // ---- geometry: closed IS the notch ---------------------------------
        readonly property int pad: NotchModel.gap
        readonly property int lineW: Theme.windowBorderWidth
        // The slab, before and after the pull: the notch's protrusion, then
        // wide enough for a seal plus its name.
        readonly property int closedW: NotchModel.protrusion
        readonly property int sealW: 176
        readonly property int runW: 264
        readonly property int openW: sealW + pad + 1 + pad + runW + pad
        readonly property int closedH: NotchModel.slabH
        readonly property int openH: Math.min(launcher.screen ? launcher.screen.height - 2 * Theme.gap : 460,
                                              Math.max(closedH, 460))

        // The right edge is welded to the panel's face; only the left one moves.
        anchors {
            left: launcher.barLeft ? parent.left : undefined
            right: launcher.barLeft ? undefined : parent.right
            verticalCenter: parent.verticalCenter
        }
        width: launcher.open ? openW : closedW
        height: launcher.open ? openH : closedH
        clip: true
        color: Theme.bg

        // The desktop's own slide (docs/DESIGN.md §6.2) — the one a window rolls
        // at, and the one the notch's seals already move at.
        Behavior on width { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }
        Behavior on height { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

        // How far out the pull has got, 0..1 — what the revealed content fades
        // on, so nothing is legible until there is room for it.
        readonly property real out: openW > closedW
            ? Math.max(0, Math.min(1, (width - closedW) / (openW - closedW)))
            : 0

        // ================= the runner: everything else =====================
        // Fixed against the panel, revealed by the slab moving off it. It is
        // BELOW the slab in z on purpose: the slab is solid, and closed it is
        // the only thing there is.
        Column {
            id: runner
            anchors {
                right: launcher.barLeft ? undefined : parent.right
                left: launcher.barLeft ? parent.left : undefined
                rightMargin: launcher.barLeft ? 0 : card.pad
                leftMargin: launcher.barLeft ? card.pad : 0
                top: parent.top; topMargin: card.pad + card.lineW
                bottom: parent.bottom; bottomMargin: card.pad + card.lineW
            }
            width: card.runW
            spacing: 8
            opacity: card.out
            visible: opacity > 0

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

        // ================= the slab: the notch, travelling =================
        // Opaque, on the moving edge, above the runner: closed it hides the
        // runner completely and IS the notch; open it is the seal column with
        // the names it made room for.
        Rectangle {
            id: slab
            z: 1
            anchors {
                left: launcher.barLeft ? undefined : parent.left
                right: launcher.barLeft ? parent.right : undefined
                top: parent.top; bottom: parent.bottom
            }
            width: launcher.open ? card.sealW : card.closedW
            color: Theme.bg
            Behavior on width { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

            // The seal column, at the notch's own inset off the outer edge and
            // centred exactly as the notch centres it — so at rest the icons
            // are where they have always been, and the pull is the only thing
            // that ever moves them.
            Column {
                id: seals
                spacing: NotchModel.gap

                // The notch shifts its seals when a window is flush against it
                // (NotchModel.columnInsetFlush). Closed, this has to agree with
                // it to the pixel or the icons twitch as the card takes over;
                // open, there is no window against anything and the normal
                // inset applies. It travels on the desktop's own slide, which
                // is what the notch's column does for the same move.
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
                width: Math.max(NotchModel.iconSize, slab.width - inset - NotchModel.gap)

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
                            anchors.left: parent.left
                            width: NotchModel.iconSize
                            height: NotchModel.iconSize
                            iconName: seal.modelData.icon
                            // The focus colour, like every other program icon
                            // on this desktop (docs/DESIGN.md §12.2.1).
                            color: Theme.accent
                        }

                        // The name the pull makes room for. Faded on the pull's
                        // own progress: at rest there is no room for it and it
                        // must not be there at all.
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
                            opacity: card.out
                            visible: opacity > 0
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

            // The seam between the slab and the cavity it opened. Not an accent
            // side: the notch's mouth has no line across it, and this is the
            // same mouth — just a divider between two columns of text.
            Rectangle {
                anchors {
                    right: launcher.barLeft ? undefined : parent.right
                    left: launcher.barLeft ? parent.left : undefined
                    top: parent.top; bottom: parent.bottom
                    topMargin: card.pad + card.lineW; bottomMargin: card.pad + card.lineW
                }
                width: 1
                color: Theme.border
                opacity: card.out
                visible: opacity > 0
            }
        }

        // ---- the outline: three sides, the notch's own ---------------------
        // Drawn last, so it frames the slab and the cavity as ONE object. The
        // panel-facing side carries no line — the drawer opens INTO the panel,
        // exactly as the notch does (DesktopNotch.qml).
        Rectangle {   // the desktop-facing side, riding the moving edge
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

import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets
import Quickshell.Wayland

// Shortcut notch drawer. It is a rigid Overlay card whose only animated
// property is x: the closed card is exactly the notch, and the clip reveals
// names and the runner as it translates. It never animates width, height, or
// opacity. Desktop entries tagged `Keywords=bespoke;` occupy the seal column;
// the runner lists every other entry. The drawer is hotkey/IPC-only.
PanelWindow {
    id: launcher

    // Keep the singleton on the current primary output so output changes remap
    // it with the panel.
    screen: Quickshell.screens.length ? Quickshell.screens[0] : null

    property bool open: false

    // Diagnostic only: bumped by shell.qml every time the Super tap arrives.
    property int taps: 0

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"
    // On a horizontal bar the card is centered on the unanchored axis.
    readonly property bool hz: ViewMode.barHorizontal
    readonly property bool barTop: SettingsStore.d.barEdge === "top"

    // Keep the surface mapped to avoid configure-race flashes. `out` gates the
    // card, input mask, and keyboard focus while the transparent surface stays.
    visible: true
    readonly property bool out: open
        || (launcher.hz ? Math.abs(card.y - card.closedY) > 1
                        : Math.abs(card.x - card.closedX) > 1)
    color: "transparent"

    // No input region while closed; the notch beneath retains its hover/clicks.
    mask: launcher.out ? null : blank
    property var blankRegion: Region { id: blank }

    // Full height, hard against the panel's FACE — the notch's own mouth.
    //
    // Cancel the notch portion of the exclusive zone so the closed card lands
    // on the notch rather than beside it.
    anchors {
        top: launcher.hz ? launcher.barTop : true
        bottom: launcher.hz ? !launcher.barTop : true
        left: launcher.hz ? false : launcher.barLeft
        right: launcher.hz ? false : !launcher.barLeft
    }
    readonly property int faceOffset: -(ViewMode.notchPx - Theme.windowBorderWidth)
    margins.right: (!launcher.hz && !launcher.barLeft) ? launcher.faceOffset : 0
    margins.left: (!launcher.hz && launcher.barLeft) ? launcher.faceOffset : 0
    margins.top: (launcher.hz && launcher.barTop) ? launcher.faceOffset : 0
    margins.bottom: (launcher.hz && !launcher.barTop) ? launcher.faceOffset : 0
    implicitWidth: card.openW
    // Only read on a horizontal bar (anchored top AND bottom otherwise): the
    // card's own height, so the surface is exactly the drawer and the closed
    // card sits outside it, clipped away by `frame`.
    implicitHeight: card.height
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-launcher"
    // Grab one frame in Exclusive mode so a keybind-opened search receives the
    // keyboard, then settle to OnDemand. Keep OnDemand through the closing slide
    // and release it only when the card is home.
    property bool grab: false
    WlrLayershell.keyboardFocus:
        launcher.grab ? WlrKeyboardFocus.Exclusive
      : launcher.out  ? WlrKeyboardFocus.OnDemand
                      : WlrKeyboardFocus.None

    // The timer bounds Exclusive mode if the keyboard grant never arrives.
    property var grabSettle: Timer {
        interval: 400
        onTriggered: launcher.grab = false
    }

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

    // Build the searchable corpus from DesktopEntries changes, not per open or
    // keystroke. Exclude bespoke seals and NoDisplay entries.
    readonly property var corpus: {
        if (!SettingsStore.d.launcherProviderApps)
            return [];
        const apps = DesktopEntries.applications.values;
        let out = [];
        for (let i = 0; i < apps.length; i++) {
            const a = apps[i];
            if (a.noDisplay || bespoke(a)) continue;
            out.push({
                entry: a,
                lname: (a.name || "").toLowerCase(),
                alias: aliasOf(a)
            });
        }
        out.sort((x, y) => (x.entry.name || "").localeCompare(y.entry.name || ""));
        return out;
    }

    // Search aliases include generic name, desktop id, executable basename, and
    // Keywords; build them once with the corpus and tolerate missing fields.
    function aliasOf(a) {
        let bits = [];
        if (a.genericName) bits.push(String(a.genericName));
        if (a.id) bits.push(String(a.id).replace(/\.desktop$/, ""));
        // The binary, not the whole command line — `%U` and flags are noise, and
        // matching them would make "u" hit half the system.
        const cmd = a.command;
        if (cmd && cmd.length)
            bits.push(String(cmd[0]).split("/").pop());
        const kw = a.keywords || [];
        for (let i = 0; i < kw.length; i++) bits.push(String(kw[i]));
        return bits.join(" ").toLowerCase();
    }

    // Three tiers, in this order: the name STARTS with what he typed, the name
    // contains it, an alias contains it. Without the tiers an alias hit could
    // outrank an exact name — typing "gimp" would put a program whose Keywords
    // mention gimp above GIMP itself. Within a tier the corpus order (alphabetical)
    // survives, because the tiers are appended whole.
    function rebuild() {
        const q = input.text.trim().toLowerCase();
        const src = corpus;
        let list = [];
        if (q === "") {
            for (let i = 0; i < src.length; i++) list.push(src[i].entry);
        } else {
            let pre = [], mid = [], ali = [];
            for (let i = 0; i < src.length; i++) {
                const r = src[i];
                if (r.lname.startsWith(q)) pre.push(r.entry);
                else if (r.lname.includes(q)) mid.push(r.entry);
                else if (r.alias.includes(q)) ali.push(r.entry);
            }
            list = pre.concat(mid, ali);
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

    // What WOULD the runner show for a query, without opening it on his screen.
    // Corpus size first (0 there means DesktopEntries found nothing, which is an
    // XDG_DATA_DIRS problem, not a search one), then the hits, then the first few
    // names in the order they would be drawn. `qs ipc call launcher query gimp`.
    function queryReport(q) {
        const src = corpus;
        const s = String(q || "").trim().toLowerCase();
        let pre = [], mid = [], ali = [];
        for (let i = 0; i < src.length; i++) {
            const r = src[i];
            if (s === "") pre.push(r.entry.name);
            else if (r.lname.startsWith(s)) pre.push(r.entry.name);
            else if (r.lname.includes(s)) mid.push(r.entry.name);
            else if (r.alias.includes(s)) ali.push(r.entry.name);
        }
        const hits = pre.concat(mid, ali);
        return "corpus=" + src.length + " hits=" + hits.length
             + " [" + hits.slice(0, 8).join(" | ") + "]";
    }

    // "Is the closed drawer exactly the notch?" — answerable without opening it
    // on his screen, which is the only way this may be checked. `notchY` is the
    // notch's own centring arithmetic (DesktopNotch's `y`), so notchY == cardY
    // and slabH == cardH is the whole test; `edgeGap` is how far the drawer's
    // panel-side edge is from the panel's face, and must be 0.
    // `qs ipc call launcher geom`.
    function geomReport() {
        const sh = launcher.screen ? launcher.screen.height : -1;
        return "cardY=" + card.y + " notchY=" + Math.round((sh - NotchModel.slabH) / 2)
             + " cardH=" + card.height + " slabH=" + NotchModel.slabH
             + " screenH=" + sh
             + " cardX=" + Math.round(card.x) + " closedX=" + card.closedX
             + " closedW=" + card.closedW + " openW=" + card.openW
             + " edgeGap=" + (launcher.width - card.openW)
             + " faceOffset=" + launcher.faceOffset
             + " notchPx=" + ViewMode.notchPx
             + " open=" + launcher.open
             // How many times the compositor's Super tap has reached the panel
             // (RunnerShortcut.qml -> shell.qml). "Meta does nothing" has two
             // halves — the shortcut never arriving, and the drawer not being
             // drawn — and this is the only way to tell them apart without
             // opening the runner on his screen.
             + " taps=" + launcher.taps;
    }

    onOpenChanged: {
        if (open) {
            // Clearing the box already rebuilds through onTextChanged; calling
            // rebuild() unconditionally as well meant every open did the work
            // twice.
            if (input.text === "")
                rebuild();
            else
                input.text = "";
            input.forceActiveFocus();
            // ...and ask the COMPOSITOR for the keyboard, which the line above
            // cannot do. See `grab`.
            launcher.grab = true;
            grabSettle.restart();
        } else {
            launcher.grab = false;
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
            // MEASURED, not guessed. A constant here is dead space between the
            // names and the runner for every seal set but the one it was picked
            // for (docs/DESIGN.md §5.2) — [his] "theres too much empty space
            // between the icons text and the runner". TextMetrics is
            // synchronous, so one instance driven round the list in the binding
            // gives the widest name at the face the rows actually draw in.
            TextMetrics {
                id: nameMetrics
                font: Theme.fontForScale(Screen.devicePixelRatio)
            }
            //
            // MEASURED IMPERATIVELY, never as a binding: driving `text` round
            // the list inside a binding makes the binding depend on the very
            // `width` it is stepping through, and QML reports it as a binding
            // loop on `nameW` (one warning per app per evaluation, thousands of
            // lines into `qs log`). A Theme change reloads the whole panel, so
            // the app list is the only thing this has to follow.
            property int nameW: 0
            function measureNames() {
                const a = NotchModel.apps;
                let w = 0;
                for (let i = 0; i < a.length; i++) {
                    nameMetrics.text = Glyphs.px(a[i].name || "");
                    w = Math.max(w, nameMetrics.width);
                }
                nameW = Math.ceil(w);
            }
            Component.onCompleted: measureNames()
            // DesktopEntries scans lazily, so the seal list arrives after the
            // first pass (the trap TaskCell.qml documents).
            Connections {
                target: NotchModel
                function onAppsChanged(): void { card.measureNames(); }
            }
            readonly property int runW: 264
            readonly property int openW: NotchModel.columnInset + NotchModel.iconSize
                                       + NotchModel.gap + nameW
                                       + pad + 1 + pad + runW + pad

            // NO HEIGHT ANIMATION, EVER: [his] "it should not grow in height".
            // The drawer is the notch's height, so the runner lives in whatever
            // the seal column comes to — which is what makes the whole thing
            // read as one object being moved rather than opened.
            // Drawn only while the drawer is out. Closed, the notch itself is
            // what is on screen — this card would be the same pixels on top of
            // it, over any window that happens to cover the notch.
            visible: launcher.out
            width: openW
            // The notch's height whether or not the notch is DRAWN. `slabH` is
            // 0 while the notch is off, and the 300 that used to stand in for it
            // was shorter than the seal column the drawer draws either way (measured
            // 385 for the current seal set), so the card's background and outline cut
            // through the icons. `slabH0` is the same arithmetic without the
            // `shown` gate, so the drawer is one size in both states.
            height: NotchModel.slabH0
            // A ROUNDED y OFF THE SCREEN, not a verticalCenter anchor and not
            // `parent.height`. Two traps, both measured:
            //   * the notch rounds its own centring (fractional logical pixels
            //     at this 1.67 scale), so anchor arithmetic lands half a pixel
            //     off it and the closed drawer stops being the notch;
            //   * an UNMAPPED layer surface has no size — `parent.height` reads
            //     0 while the drawer is closed, which centred the card at
            //     y = -161 against the notch's 319 (`qs ipc call launcher
            //     geom`). It mapped that high and settled afterwards: [his]
            //     "its currently higher than the bar itself".
            //
            // On a horizontal bar this is the ANIMATED axis instead, and the
            // card is centred by the surface rather than by arithmetic — so
            // there is no fractional-centring trap to round away.
            y: launcher.hz ? (launcher.open ? 0 : closedY)
                           : Math.round(((launcher.screen ? launcher.screen.height : parent.height) - height) / 2)

            // Closed: pushed back until only the notch strip is this side of the
            // panel's face. Open: fully out. The ONE animated property here —
            // x on a vertical bar, y on a horizontal one. With no notch on a
            // horizontal edge, closedW is 0, so closed there is the card fully
            // behind the bar rather than a strip of it left showing.
            readonly property real closedX: launcher.barLeft ? closedW - openW : openW - closedW
            readonly property real openX: 0
            readonly property real closedY: launcher.barTop ? closedW - height : height - closedW
            x: launcher.hz ? 0 : (launcher.open ? openX : closedX)
            // The desktop's own slide (docs/DESIGN.md §6.2) — the one a window
            // rolls at, and the one the notch's seals already move at.
            Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }
            Behavior on y {
                enabled: launcher.hz
                NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
            }

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

                width: NotchModel.iconSize + NotchModel.gap + card.nameW
                x: launcher.barLeft ? parent.width - inset - width : inset
                anchors.verticalCenter: parent.verticalCenter

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
                            width: NotchModel.iconSize
                            height: NotchModel.iconSize
                            x: launcher.barLeft ? parent.width - width : 0
                            iconName: seal.modelData.icon
                            // The focus colour, like every other program icon
                            // on this desktop (docs/DESIGN.md §12.2.1).
                            color: Theme.accent
                        }

                        // The name, further back in the drawer than its icon —
                        // so it comes out from behind the panel as the bar is
                        // pulled, rather than fading in on top of it.
                        PixelText {
                            x: launcher.barLeft ? 0 : sealIcon.x + sealIcon.width + NotchModel.gap
                            width: launcher.barLeft ? sealIcon.x - NotchModel.gap
                                                    : parent.width - x
                            anchors.verticalCenter: parent.verticalCenter
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
                width: 1
                x: launcher.barLeft ? seals.x - card.pad - width
                                  : seals.x + seals.width + card.pad
                anchors { top: parent.top; bottom: parent.bottom
                    topMargin: card.pad + card.lineW; bottomMargin: card.pad + card.lineW }
                color: Theme.border
            }

            // ================= the runner: everything else =====================
            Column {
                id: runnerBody
                x: launcher.barLeft ? card.pad : split.x + split.width + card.pad
                width: launcher.barLeft ? split.x - card.pad
                                        : parent.width - x - card.pad
                anchors { top: parent.top; topMargin: card.pad + card.lineW
                    bottom: parent.bottom; bottomMargin: card.pad + card.lineW }
                spacing: 8

                // search box
                Rectangle {
                    width: parent.width
                    height: 34
                    color: Theme.bgAlt
                    border.color: Theme.border
                    border.width: Theme.ctrlBorder
                    radius: Math.max(2, Theme.windowRounding)

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
                            font: Theme.fontForScale(Screen.devicePixelRatio)
                            renderType: Text.NativeRendering
                            clip: true
                            focus: true
                            selectByMouse: true
                            onTextChanged: launcher.rebuild()

                            // The window is only ACTIVE while this layer surface
                            // holds the wl_keyboard, so this is the panel being
                            // told the open's Exclusive grab landed. Settle to
                            // OnDemand, which is what hands the keyboard back
                            // when you click into a window.
                            onActiveFocusChanged: if (activeFocus) launcher.grab = false

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
            // PANEL-FACING side carries no line — the drawer opens INTO the
            // panel, exactly as the notch does (DesktopNotch.qml) — and which
            // side that is turns with the bar: the panel-side vertical edge on
            // a left/right bar, the bottom edge on a bottom bar, the top edge
            // on a top one. The bar paints its own accent line out across the
            // drawer's span to match (shell.qml), so the two outlines meet at
            // the corners and the pair reads as one piece.
            Rectangle {   // vertical: the desktop-facing edge on a vertical bar,
                          // the LEFT edge on a horizontal one
                z: 2
                x: launcher.hz ? 0
                               : (launcher.barLeft ? card.width - card.lineW : 0)
                width: card.lineW
                height: card.height
                color: Theme.accent
            }
            Rectangle {   // the RIGHT edge — a horizontal bar has both verticals
                z: 2
                visible: launcher.hz
                x: card.width - card.lineW
                width: card.lineW
                height: card.height
                color: Theme.accent
            }
            Rectangle {   // top
                z: 2
                visible: !(launcher.hz && launcher.barTop)
                width: card.width
                height: card.lineW
                color: Theme.accent
            }
            Rectangle {   // bottom
                z: 2
                visible: !(launcher.hz && !launcher.barTop)
                y: card.height - card.lineW
                width: card.width
                height: card.lineW
                color: Theme.accent
            }
        }
    }
}

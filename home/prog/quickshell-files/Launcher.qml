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
//     inset. Pixel for pixel the notch — and the card is simply not drawn
//     there at all, because the real notch is what is on screen (the surface
//     itself never unmaps; see `visible` below).
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

    // Unlike the bar, this is one persistent surface rather than a per-output
    // Variant. Letting PanelWindow choose its initial output left it attached
    // to a removed eDP screen after the external DP output took over: Meta
    // toggled `open` and the card reached x=0, but there was no qs-launcher
    // surface mapped anywhere to draw it. Keep the singleton attached to the
    // current primary output so an output switch remaps it with the panel.
    screen: Quickshell.screens.length ? Quickshell.screens[0] : null

    property bool open: false

    // Diagnostic only: bumped by shell.qml every time the Super tap arrives.
    property int taps: 0

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"
    // On a top/bottom bar the drawer comes out of the MIDDLE of the bar,
    // downwards or upwards — the same one-rigid-card slide, on the other axis.
    // Anchoring the surface to one horizontal edge and NEITHER side is what
    // centres it: wlr-layer-shell centres a surface on any axis it is not
    // anchored to.
    readonly property bool hz: ViewMode.barHorizontal
    readonly property bool barTop: SettingsStore.d.barEdge === "top"

    // THIS SURFACE IS NEVER UNMAPPED. It is transparent and empty while the
    // drawer is in, and the card inside it is what appears and disappears.
    //
    // Mapping it per open was the last visible glitch: every few opens the
    // drawer flashed at the TOP-RIGHT for a frame — [his] "it'll appear as if
    // the bar glitches out an appears above and to the right … after every like
    // 5 or so times". A layer surface's anchors, margins and size arrive by
    // CONFIGURE, and a client that commits its first buffer before that
    // round-trip completes is drawn at the anchored corner with default margins
    // — which for this window (anchored right, negative margin, full height) is
    // exactly up and to the right. It is a race, so it misses most of the time,
    // and `no_anim` removed the fade that used to hide it.
    //
    // Staying mapped also takes the remaining map round-trip out of the open.
    // The cost is one always-composited transparent surface, and the care below:
    // `out` gates the CARD, the input mask and keyboard focus, so while the
    // drawer is in, this window draws nothing, takes no input (the notch under
    // it keeps its own clicks and hover tooltips) and holds no focus.
    visible: true
    readonly property bool out: open
        || (launcher.hz ? Math.abs(card.y - card.closedY) > 1
                        : Math.abs(card.x - card.closedX) > 1)
    color: "transparent"

    // No input region at all while the drawer is in — anything else would put a
    // 401x323 dead zone over his desktop, and swallow the notch's own hover.
    mask: launcher.out ? null : blank
    property var blankRegion: Region { id: blank }

    // Full height, hard against the panel's FACE — the notch's own mouth.
    //
    // THE NEGATIVE MARGIN IS LOAD-BEARING, and getting it wrong is what made
    // this read as "another bar spawns" no matter how the motion was written.
    // The bar's exclusive zone reserves the bar AND the notch
    // (`liveWidth + notchPx - windowBorderWidth`, shell.qml), so a surface
    // anchored to this edge is placed at the NOTCH'S OUTER FACE — a drawer sat
    // there is beside the notch, never over it, and its closed strip is a
    // second copy of the notch drawn next to the real one (measured on book:
    // reserved 359 of 1536, panel face at 1209, surface edge at 1177). Cancel
    // exactly what the zone added and the closed drawer lands ON the notch.
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
    // ONE FRAME OF Exclusive TO TAKE THE KEYBOARD, then OnDemand to hold it.
    //
    // OnDemand alone was the "the runner is open and typing goes to the window
    // behind it" bug. This drawer opens from a KEYBIND (RunnerShortcut.qml), so
    // the only thing that happens on open is a None->OnDemand commit — and
    // Hyprland grants an on-demand layer surface the keyboard on the next
    // pointer MOTION over it, never on a commit and never on a click. Tap Super
    // with the pointer over a window and the box was drawn, QML-focused, cursor
    // blinking, and had no wl_keyboard: `input.forceActiveFocus()` moves focus
    // inside the scene and cannot ask the compositor for anything. So the open
    // arms `grab`, which flips this surface to Exclusive — the one mode a commit
    // can switch to that grabs the keyboard outright. Same fix as the dock's
    // filter box (shell.qml's `Procs.filterGrab`), which had it first.
    //
    // AND THEN STRAIGHT BACK TO OnDemand, the moment the box actually holds
    // focus. Sticky Exclusive keeps sending us the keyboard after you click into
    // a window, so the next keystroke would land in the search box instead of
    // what you just clicked on.
    //
    // The OnDemand term is tied to `out`, not `open`, so the layer keeps the
    // keyboard through the closing pull and gives it back only once the drawer
    // is home — and holds none of it the rest of the time, which matters now
    // that the surface is permanent. No `filterLatch` equivalent is needed here:
    // the bar hands back while the pointer is still over it (the case Hyprland's
    // refocusLastWindow gets wrong), whereas this drawer is gone by then.
    property bool grab: false
    WlrLayershell.keyboardFocus:
        launcher.grab ? WlrKeyboardFocus.Exclusive
      : launcher.out  ? WlrKeyboardFocus.OnDemand
                      : WlrKeyboardFocus.None

    // Drop the grab as soon as the box has the keyboard. The timer is the
    // backstop: if the grant never arrives, a surface left Exclusive would eat
    // every keystroke on the desktop, so it is never held longer than this.
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

    // THE CORPUS IS BUILT ONCE, not on every open and not on every keystroke.
    // Scanning `DesktopEntries.applications.values`, dropping the seals and the
    // `NoDisplay` entries, and sorting the ~300 that remain is work that only
    // changes when the SYSTEM's programs do — so it is a binding on that list,
    // and pressing Super does none of it. Each row carries its own lowercased
    // name, because the search would otherwise redo that per program per
    // keystroke.
    //
    // EVERY OTHER PROGRAM: the seals are in the drawer's own column, so listing
    // them here too would be the same icon twice.
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

    // What ELSE a program answers to. `Name` alone is not what a person types:
    // gimp's entry is called "GNU Image Manipulation Program", vlc's generic
    // name is "Media player", steam's id is `steam.desktop` while its name is
    // "Steam". So each row carries a second lowercased haystack — generic name,
    // desktop id, the executable's basename and the entry's own Keywords — built
    // ONCE with the corpus, never per keystroke. Every field is read
    // defensively: a DesktopEntry that lacks one gives undefined, not an error.
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

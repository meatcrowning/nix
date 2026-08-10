import QtQuick
import Quickshell

// The task manager: the machine's load at a glance, and the processes causing
// it, with the means to end them.
//
// Three sections, top to bottom: a 4x2 block of square chart cards (cpu, gpu,
// mem, net, load, vram, swap, fan — see `noGpu` for the psi/io/batt set book
// puts in the gpu/vram/fan slots instead), the book-only top-mirror drawer, and
// the process table taking everything that is left. A row's [x] ends it
// politely; right-clicking anywhere in a row opens ProcMenu.qml, which is where
// everything else a process can be asked to do lives. The table is the point of
// the widget, so it gets the slack — the cards are SQUARE, i.e. their height
// follows the panel width, and a taller tile turns into more visible processes
// rather than letterboxed charts.
//
// The card block lives in MetricCardGrid.qml so the top-mirror drawer can draw
// the SAME grid sourced from `top` (see TopProcDrawer / TopStats).
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    property int pad: 8
    readonly property real inner: Math.max(160, width - pad * 2)

    // book has no gpu, vram or fan to draw: Asahi's DRM driver publishes no
    // utilization counter, its GPU memory IS system memory, and the machine is
    // fanless. Those three slots go to psi, io and batt there instead — see
    // sysinfo.sh. Keyed on the build-time Host singleton rather than on the
    // readings being -1, so the card set is fixed before the first poll and the
    // grid can't relabel itself two seconds after it opens.
    readonly property bool noGpu: Host.name === "air"

    implicitWidth: 300
    implicitHeight: 360

    // Handing the keyboard back is not optional: the dock closing (or this
    // widget being torn down by a reload) while the filter box still held focus
    // would leave the bar's layer holding a keyboard grab with nothing on screen
    // to type into.
    onActiveChanged: {
        Procs.watch(root, active);
        if (!active) {
            // The menu is a separate popup surface: nothing unmaps it when the
            // dock closes, so it would be left floating over the wallpaper
            // pointing at a table that is no longer on screen.
            procMenu.close();
            filterInput.focus = false;
            Procs.filterFocus = false;
            Procs.filterGrab = false;
            Procs.filterLatch = false;
        }
    }
    Component.onCompleted: Procs.watch(root, active)
    Component.onDestruction: {
        procMenu.close();
        Procs.watch(root, false);
        Procs.filterFocus = false;
        Procs.filterGrab = false;
        Procs.filterLatch = false;
    }

    // ---- the local machine's own load: the square-card block --------------
    MetricCardGrid {
        id: cards
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: implicitHeight
        active: root.active
        src: SysInfo
        noGpu: root.noGpu
        // The fan card scrolls screen brightness on the real tile; the mirror
        // below leaves this null so top's fan card cannot drive book's backlight.
        wheelTarget: SysInfo
    }

    // ---- book-only: watching top from book -------------------------------
    // The top-mirror disclosure — an 18px "top v" button that rolls out a copy
    // of top's OWN card grid (TopStats/TopProcDrawer), directly UNDERNEATH the
    // local graphs above. On top there is no drawer: `mirror` is false, the
    // height collapses to 0 and the process list runs straight up to the graphs.
    readonly property bool mirror: Host.name === "air"
    TopProcDrawer {
        id: topDrawer
        visible: root.mirror
        active: root.active
        // Explicit height so the non-book tile does not lose the button's 18px:
        // an invisible Item still occupies its implicitHeight for the anchor
        // below, so collapse it to 0 off book. On book it follows its own
        // gliding implicitHeight (disc + clipped grid), so the list below reflows.
        height: root.mirror ? implicitHeight : 0
        width: root.inner
        anchors {
            top: cards.bottom; topMargin: root.mirror ? 4 : 0
            horizontalCenter: parent.horizontalCenter
        }
    }

    // ---- filter box ------------------------------------------------------
    // Substring match on name or pid, live as you type. The panel's layer
    // surface takes the keyboard ONLY while this box holds it (Procs.filterFocus,
    // read in shell.qml): a bar that were always focusable would swallow the
    // keystroke you meant for the window you were working in. Escape clears and
    // hands it straight back.
    Rectangle {
        id: filterBox
        anchors { top: topDrawer.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 19
        color: Theme.bgAlt
        radius: Theme.windowRounding
        border.width: Theme.ctrlBorder
        border.color: filterInput.activeFocus ? Theme.accent : Theme.border

        PixelText {
            id: filterIcon
            anchors { left: parent.left; leftMargin: 5; verticalCenter: parent.verticalCenter }
            text: "/"
            color: filterInput.activeFocus ? Theme.accent : Theme.textDim
        }
        TextInput {
            id: filterInput
            anchors {
                left: filterIcon.right; leftMargin: 5
                right: filterClear.left; rightMargin: 5
                verticalCenter: parent.verticalCenter
            }
            // A TextInput is not a Text, so it inherits none of PixelText's
            // settings and would rasterise the pixel font through the
            // distance-field path — blurry, next to a panel of crisp text.
            font.family: Theme.font
            font.pixelSize: Theme.fontSize
            font.hintingPreference: Font.PreferFullHinting
            renderType: Text.NativeRendering
            color: Theme.text
            selectionColor: Theme.accent
            selectedTextColor: Theme.bg
            clip: true
            text: Procs.filter
            onTextEdited: Procs.setFilter(text)
            // Focus is owned by the box MouseArea below (which must grab the
            // keyboard before this can ever be active), so a press here must
            // not separately try to focus — the window is not active yet.
            activeFocusOnPress: false
            // The window is only ACTIVE while this layer surface holds the
            // wl_keyboard, so losing activeFocus is how the box hears that the
            // user clicked into a window or onto the desktop — the compositor
            // moved the keyboard and never told the panel anything else. Drop
            // the item's own focus with it, or the caret silently comes back
            // the next time the pointer crosses the box.
            onActiveFocusChanged: {
                Procs.filterFocus = activeFocus;
                if (activeFocus)
                    Procs.filterGrab = false;   // the press's Exclusive grab landed; settle to OnDemand
                if (!activeFocus) filterInput.focus = false;
            }
            Keys.onEscapePressed: {
                Procs.setFilter("");
                filterInput.focus = false;
            }
            PixelText {
                anchors.fill: parent
                visible: filterInput.text === "" && !filterInput.activeFocus
                text: "filter"
                color: Theme.textDim
            }
        }
        // How much of the machine the filter is hiding, and the click target
        // that clears it. Only while filtering — with an empty box the table is
        // the whole list and the count would be noise.
        PixelText {
            id: filterClear
            anchors { right: parent.right; rightMargin: 5; verticalCenter: parent.verticalCenter }
            // Above the box MouseArea so its "x" stays clickable.
            z: 3
            visible: Procs.filter !== ""
            text: Procs.sorted.length + "/" + Procs.total + " x"
            color: clearMa.containsMouse ? Theme.crit : Theme.textDim
            MouseArea {
                id: clearMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { Procs.setFilter(""); filterInput.focus = false; }
            }
        }
        // Click anywhere in the box to type. Covers the whole box — including
        // the TextInput — because the window is not active when you press, so
        // the TextInput's own click-focus would be a silent no-op. HOVER
        // changes nothing about focus; only a press does: it grabs the keyboard
        // through Procs.filterGrab (an on-demand layer surface gets the keyboard
        // on pointer MOTION, never on a click, so the click has to request the
        // grab itself) and latches the surface until the pointer has left the
        // bar, so the later hand-back is never done while the pointer is still
        // over it.
        MouseArea {
            anchors.fill: parent
            z: 2
            hoverEnabled: true
            cursorShape: Qt.IBeamCursor
            onPressed: {
                if (!Procs.filterFocus) {
                    Procs.filterGrab = true;
                    Procs.filterLatch = true;
                }
            }
            onClicked: filterInput.forceActiveFocus()
        }
    }

    // "Give the keyboard back" from anywhere else in the panel (shell.qml's
    // catcher). A counter rather than a call, because this widget is behind an
    // asynchronous Loader and there is nothing stable to reach into.
    Connections {
        target: Procs
        function onBlurSeqChanged() { filterInput.focus = false; }
    }

    // ---- process table ---------------------------------------------------
    Rectangle {
        id: rule
        anchors { top: filterBox.bottom; topMargin: 5; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 1
        color: Theme.border
    }

    // Column geometry, shared by the header and every row so they line up.
    // The pid column is dropped on a narrow panel rather than squeezed: at 14%
    // of the screen the process NAME is already down to a few characters, and
    // that is the column you actually read.
    readonly property bool showPid: inner >= 300
    // 58, not 44: this kernel hands out six-digit pids routinely (pid_max is
    // 4194304), and at 44 they ran straight into the process name.
    readonly property real colPid: showPid ? 58 : 0
    readonly property real colKill: 14
    readonly property real colCpu: 44
    readonly property real colMem: 44
    readonly property real colRss: 42
    readonly property real colName:
        Math.max(40, inner - colPid - colCpu - colMem - colRss - colKill)

    // A clickable column heading. Inline components have to be members of the
    // file's root object, so it is declared here rather than inside the Row.
    component Head: PixelText {
        id: head
        property string key: ""
        color: Procs.sortKey === head.key ? Theme.accent : Theme.textDim
        MouseArea {
            anchors { fill: parent; topMargin: -3; bottomMargin: -3 }
            cursorShape: Qt.PointingHandCursor
            onClicked: Procs.setSort(head.key)
        }
    }

    // Clicking a heading sorts by it. The sort lives in Procs so it survives a
    // reload along with the rows.
    Row {
        id: header
        anchors { top: rule.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 0

        // process name first, then pid: the name is what you scan for, and the
        // pid is a detail about the row you already found. The numeric columns
        // stay grouped on the right, so pid sits between them and the name.
        Head { width: root.colName; key: "name"; text: "process" }
        Head {
            width: root.colPid
            visible: root.showPid
            key: "pid"
            text: "pid"
            horizontalAlignment: Text.AlignRight
            // keeps the number off cpu%'s left edge, which is right-aligned too
            rightPadding: 6
        }
        Head { width: root.colCpu;  key: "cpu";  text: "cpu%"; horizontalAlignment: Text.AlignRight }
        Head { width: root.colMem;  key: "mem";  text: "mem%"; horizontalAlignment: Text.AlignRight }
        Head { width: root.colRss;  key: "mem";  text: "res";  horizontalAlignment: Text.AlignRight }
        Item { width: root.colKill; height: 1 }
    }

    KineticListView {
        id: list
        anchors {
            top: header.bottom; topMargin: 3
            // The process table takes everything left below the header, down to
            // the tile's bottom edge — the top-mirror drawer now sits ABOVE it
            // (under the graphs), so opening the drawer reflows the list down
            // rather than eating its bottom.
            bottom: parent.bottom; bottomMargin: root.pad
            horizontalCenter: parent.horizontalCenter
        }
        width: root.inner
        clip: true
        // The rows re-sort under the pointer every 2s; without this a flick
        // would be fighting the refresh.
        boundsBehavior: Flickable.StopAtBounds
        model: Procs.sorted
        // Reuse the delegates: the model is replaced wholesale on every poll and
        // rebuilding 60 rows twice a second is real work for no change on screen.
        reuseItems: true

        delegate: Item {
            id: row
            required property var modelData
            width: list.width
            height: 17

            Rectangle {
                anchors.fill: parent
                color: rowMa.containsMouse ? Theme.highlight : "transparent"
            }
            // Hover highlight, and the row's context menu. Only the RIGHT
            // button is accepted: a left press must still fall through to
            // whatever is under it (the [x] cell sits above this in the
            // stacking order and keeps its own clicks either way).
            MouseArea {
                id: rowMa
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.RightButton
                onClicked: procMenu.openFor(row, row.modelData)
            }

            Row {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                spacing: 0

                PixelText {
                    width: root.colName
                    text: row.modelData.name
                    color: Theme.text
                    elide: Text.ElideRight
                }
                PixelText {
                    width: root.colPid
                    visible: root.showPid
                    horizontalAlignment: Text.AlignRight
                    rightPadding: 6
                    text: row.modelData.pid
                    color: Theme.textDim
                }
                PixelText {
                    width: root.colCpu
                    horizontalAlignment: Text.AlignRight
                    // Solaris mode: a share of the WHOLE machine, 0-100, on the
                    // same denominator as the cpu card above (proc-list.py).
                    // One decimal, and it cannot take a second: the column is
                    // 44px = 5.5 cells, so "100.0" fits and "100.00" clips at
                    // full load. 0.1 point here is 1.6% of one core on this box.
                    text: row.modelData.cpu.toFixed(1)
                    // Retuned with the denominator, NOT carried over: 50/10 were
                    // half and a tenth of ONE core, i.e. 3.1 and 0.6 here, which
                    // would paint an idle desktop amber. These are machine
                    // shares — a pegged single-threaded process is 100/NCPU
                    // (6.2% on 16 threads, 12.5% on book) and must still colour,
                    // so warn sits below that and crit at a few cores' worth.
                    color: row.modelData.cpu >= 25 ? Theme.crit
                         : row.modelData.cpu >= 5 ? Theme.warn : Theme.textDim
                }
                PixelText {
                    width: root.colMem
                    horizontalAlignment: Text.AlignRight
                    text: row.modelData.mem.toFixed(1)
                    color: row.modelData.mem >= 10 ? Theme.warn : Theme.textDim
                }
                PixelText {
                    width: root.colRss
                    horizontalAlignment: Text.AlignRight
                    text: Procs.fmtMem(row.modelData.rss)
                    color: Theme.textDim
                }

                // End it. Left click is SIGTERM — the same "click the [x]"
                // courtesy hyprvtb's close button extends, so the process gets to
                // save.
                //
                // SIGKILL used to be the RIGHT button here, so that an
                // unrecoverable action was never one mis-timed left click away
                // on a table that re-sorts under the cursor every 2s. It now
                // lives in the row's context menu, which keeps that guarantee
                // (it is still two deliberate acts) and removes a worse trap:
                // once right-click means "menu" everywhere else in the row, a
                // right-click that landed a few pixels off would have SIGKILLed
                // whatever had just sorted under the pointer. Right-click here
                // opens the same menu as the rest of the row.
                //
                // The panel's OWN row gets no [x] at all — it is in this table
                // like everything else, and ending it takes the bar, the
                // wallpaper and every popup with it. `Procs.signal` refuses it
                // as well; this is the half that keeps it from being offered.
                Item {
                    width: root.colKill
                    height: 15
                    readonly property bool self: String(row.modelData.pid) === Procs.selfPid
                    PixelText {
                        anchors.centerIn: parent
                        visible: !parent.self && (rowMa.containsMouse || killMa.containsMouse)
                        text: "x"
                        color: killMa.containsMouse ? Theme.crit : Theme.textDim
                    }
                    MouseArea {
                        id: killMa
                        anchors { fill: parent; margins: -2 }
                        enabled: !parent.self
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: (mouse) => {
                            if (mouse.button === Qt.RightButton)
                                procMenu.openFor(row, row.modelData);
                            else
                                Procs.kill(row.modelData.pid, false);
                        }
                    }
                }
            }
        }

        PixelText {
            anchors.centerIn: parent
            visible: Procs.rows.length === 0
            text: "reading..."
            color: Theme.textDim
        }
    }

    // ONE menu for the whole table, anchored against this root rather than a
    // row — the list recycles delegates and re-sorts every 2s, so a per-row
    // instance would be destroyed or silently re-pointed while it was open.
    // See ProcMenu.qml.
    ProcMenu {
        id: procMenu
        host: root
    }
}

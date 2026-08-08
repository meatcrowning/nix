import QtQuick
import Quickshell

// Right-click context menu for a row of the task manager's process table.
//
// It is a sibling of TaskMenu.qml (the taskbar cell's menu) and deliberately
// mirrors it: a PopupWindow opening to the LEFT of the pointed-at row, since
// the bar hugs the right screen edge; no compositor focus grab (this config
// never imports Quickshell.Hyprland), so dismissal is hover-driven — a beat
// after the pointer leaves, and a grace timeout if it is opened but never
// entered.
//
// ONE INSTANCE PER TABLE, not one per row, and it captures the row's values on
// open. The list re-sorts every 2s and `reuseItems` recycles delegates, so a
// menu owned by a delegate would be destroyed or silently re-pointed at a
// different process while it was on screen. What it acts on is the pid it was
// opened with, which is the same rule the [x] button follows.
//
// EVERY ACTION IS A FIRE-AND-FORGET execDetached with no exit code (see
// Procs.qml), so an action the kernel would refuse must not be OFFERED: rows
// the sampler reports as somebody else's (`mine` false) get the read-only
// entries only, plus a line saying why. Silently doing nothing is the failure
// mode this menu exists to avoid, not one it may reintroduce.
//
// A POPUP THAT MAPS AT ZERO SIZE KILLS THE WHOLE PANEL — it is not a cosmetic
// bug and there is no QML error to find afterwards. `xdg_positioner.set_size`
// rejects a non-positive width or height with a PROTOCOL error, and a protocol
// error disconnects the client: quickshell exits, the bar and the wallpaper go
// with it, and the only trace anywhere is Hyprland's `error in client
// communication (pid N)` in the journal. There is no coredump and `qs log`
// stops mid-sentence. That is what the first version of this file did on the
// very first right-click (2026-07-27 20:20): `box.implicitWidth` read
// `col.implicitWidth`, a Column that `anchors.fill`ed `box` whose children were
// `width: box.width` — so the width was defined in terms of itself, resolved to
// 0 and stayed there. Reproduced and confirmed in the sandbox against this
// exact file: `error 0: Invalid size` -> `fatal error: Protocol error`, EXIT=255.
//
// Hence the two rules below, which are why the size is measured rather than
// bound: the implicit size must be computed ONLY from things that do not depend
// on the popup's own size, and `implicitWidth`/`implicitHeight` carry a hard
// floor so a future mistake degrades into an ugly menu rather than a dead
// desktop.
PopupWindow {
    id: menu

    // The stable item the popup anchors against — the task manager content
    // root, NOT the row (which may be recycled out from under an open menu).
    property Item host

    // Captured at open. Nothing here binds to the live model.
    property string pid: ""
    property string pname: ""
    property string pstate: "?"
    property int pnice: 0
    property bool mine: true

    readonly property bool stopped: pstate === "T"
    readonly property bool ready: host && host.QsWindow && host.QsWindow.window
    // The panel's own row. Signalling it is what "his whole desktop vanished"
    // looks like from the user's chair, so it is not offered — see Procs.qml,
    // which refuses it a second time at the call site.
    readonly property bool isSelf: pid !== "" && pid === Procs.selfPid

    // Measured in openFor(), never bound. See the header: a binding from these
    // to anything that follows the popup's width is the crash.
    property real contentW: 0
    property real contentH: 0

    visible: false
    color: "transparent"
    // The floor is the last line of defence, not the mechanism — a popup that
    // reaches the compositor with a 0 in it takes the panel down.
    implicitWidth: Math.max(1, Math.ceil(menu.contentW))
    implicitHeight: Math.max(1, Math.ceil(menu.contentH))

    property real anchorX: 0
    property real anchorY: 0

    // Walk the Column's children for the size the popup should map at. Only
    // `implicitWidth`/`implicitHeight` are read, and those come from the label
    // text — nothing here reads a laid-out `width`, so there is no cycle back
    // through the popup's own geometry. Called AFTER the captured values are
    // assigned, so `visible` on each entry is already up to date.
    function measure() {
        let w = 0;
        let h = 0;
        for (let i = 0; i < col.children.length; ++i) {
            const c = col.children[i];
            // `shown`, NOT `visible`: an item's `visible` is its EFFECTIVE
            // visibility, which is false for everything inside an unmapped
            // window — and this popup is unmapped every time it is closed. A
            // measure over `visible` therefore returns 0x0 on the second and
            // every subsequent open, i.e. the menu opens once per panel life
            // and then silently refuses forever. Measured, not reasoned.
            if (!c || c.shown === false)
                continue;
            w = Math.max(w, c.implicitWidth);
            h += c.implicitHeight + (i > 0 ? col.spacing : 0);
        }
        menu.contentW = w;
        menu.contentH = h;
    }

    // `row` is the delegate the click landed in; it is used ONCE, here, to
    // place the popup, and never held.
    function openFor(row, p) {
        if (!ready || !p)
            return;
        menu.pid = String(p.pid);
        menu.pname = p.name || "?";
        menu.pstate = p.state || "?";
        menu.pnice = p.nice || 0;
        menu.mine = p.mine !== false;
        measure();
        // Refuse rather than map something degenerate. console.log is dropped
        // by quickshell, so this has to be a warn to be findable in `qs log`.
        if (menu.contentW < 1 || menu.contentH < 1) {
            console.warn("ProcMenu: refusing to open at "
                         + menu.contentW + "x" + menu.contentH
                         + " — a zero-size popup is a fatal Wayland protocol error");
            return;
        }
        // Scene coordinates, like Tooltip/TaskMenu: mapToItem(null) maps to the
        // scene root, which is what anchor.rect is relative to. Recomputed on
        // every open — a delegate laid out later keeps its birth y in a plain
        // binding.
        const pt = row.mapToItem(null, 0, row.height / 2);
        anchorX = pt.x - 8;
        anchorY = pt.y;
        visible = true;
        graceTimer.restart();
    }
    function close() { visible = false; }

    anchor {
        window: menu.ready ? menu.host.QsWindow.window : null
        rect {
            x: menu.anchorX
            y: menu.anchorY
            width: 1
            height: 1
        }
        edges: Edges.Left
        gravity: Edges.Left
    }

    Timer {
        id: leaveTimer
        interval: 400
        onTriggered: if (!menuHover.hovered) menu.close()
    }
    Timer {
        id: graceTimer
        interval: 2500
        onTriggered: if (!menuHover.hovered) menu.close()
    }

    Rectangle {
        id: box
        anchors.fill: parent
        // NO implicit size here. It is the popup that sizes this, from
        // menu.measure(); reading `col`'s implicit size back would close the
        // loop the header describes.
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: Theme.ctrlBorder
        radius: Math.max(3, Theme.windowRounding)

        HoverHandler {
            id: menuHover
            onHoveredChanged: {
                if (hovered)
                    leaveTimer.stop();
                else
                    leaveTimer.restart();
            }
        }

        // A clickable entry. Invisible rows are skipped by menu.measure(), so
        // the menu is exactly as tall as the actions this particular process
        // actually has. `width: box.width` is the ROW following the menu, which
        // is fine — what must never happen is the menu following the row.
        component MenuRow: Rectangle {
            // See menu.measure(): `visible` is effective visibility and is
            // false while the popup is unmapped, so what an entry is FOR is a
            // property of its own and `visible` merely follows it.
            property bool shown: true
            visible: shown
            property string label: ""
            property color labelColor: Theme.text
            signal activated()
            width: box.width
            implicitWidth: rowText.implicitWidth + 24
            implicitHeight: rowText.implicitHeight
            // Hover LIGHTENS, one step up the brightness ladder (§3.3):
            // `highlight` is the desktop's selection fill, and the row under the
            // pointer is the pending selection. docs/DESIGN.md §7.2.
            color: rowMouse.containsMouse ? Theme.highlight : "transparent"
            PixelText {
                id: rowText
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: parent.label
                textFormat: Text.PlainText
                color: parent.labelColor
            }
            MouseArea {
                id: rowMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: parent.activated()
            }
        }

        // A non-interactive line: the header, and the "not yours" note.
        component MenuNote: Item {
            property bool shown: true
            visible: shown
            property string label: ""
            property color labelColor: Theme.textDim
            width: box.width
            implicitWidth: noteText.implicitWidth + 24
            implicitHeight: noteText.implicitHeight
            PixelText {
                id: noteText
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: parent.label
                textFormat: Text.PlainText
                color: parent.labelColor
                elide: Text.ElideRight
                // Math.max: box.width is 0 until the popup is sized, and a
                // negative width on a Text is a warning per note per open.
                width: Math.min(implicitWidth, Math.max(0, box.width - 20))
            }
        }

        component MenuSep: Item {
            property bool shown: true
            visible: shown
            width: box.width
            implicitWidth: 1
            implicitHeight: 5
            Rectangle {
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                height: 1
                color: Theme.border
            }
        }

        Column {
            id: col
            anchors.fill: parent

            // Which process this is about. The table re-sorts under the
            // pointer, so a menu that did not name its target would be a
            // coin flip about what the next click ends.
            MenuNote {
                label: menu.pname + " (" + menu.pid + ")"
                labelColor: Theme.accent
            }
            MenuSep {}

            // ORDER IS A SAFETY PROPERTY HERE, not a style choice. The pointer
            // opens this menu on a table that re-sorts under it every 2s, so the
            // entries nearest the cursor must be the ones a mis-timed click can
            // be forgiven: the read-only actions first, the recoverable state
            // changes next, and the two signals that end a process LAST, behind
            // a separator (§10.3 — the same reason the [x] stopped being an
            // instant SIGKILL). filer's menu opens with `open` for the same
            // reason.
            MenuRow {
                label: "filter by name"
                onActivated: { Procs.setFilter(menu.pname); menu.close(); }
            }
            MenuRow {
                label: "copy pid"
                onActivated: { Procs.copyText(menu.pid); menu.close(); }
            }

            // Always shown: something always follows it — the state changes and
            // the signals for our own processes, the "refused" note otherwise.
            MenuSep {}

            MenuRow {
                shown: menu.mine && !menu.isSelf && !menu.stopped
                label: "suspend"
                onActivated: { Procs.signal(menu.pid, "STOP"); menu.close(); }
            }
            MenuRow {
                shown: menu.mine && !menu.isSelf && menu.stopped
                label: "resume"
                onActivated: { Procs.signal(menu.pid, "CONT"); menu.close(); }
            }
            // Niceness is one-way without privilege, so this is offered only
            // while there is room to go up, and never as a way back down.
            MenuRow {
                shown: menu.mine && !menu.isSelf && menu.pnice < 19
                label: "lower priority"
                onActivated: { Procs.renice(menu.pid, Math.min(19, menu.pnice + 10)); menu.close(); }
            }

            MenuSep { shown: menu.mine && !menu.isSelf }

            MenuRow {
                shown: menu.mine && !menu.isSelf
                label: "end task"
                onActivated: { Procs.kill(menu.pid, false); menu.close(); }
            }
            MenuRow {
                shown: menu.mine && !menu.isSelf
                label: "force quit"
                labelColor: Theme.crit
                onActivated: { Procs.kill(menu.pid, true); menu.close(); }
            }
            // Why the signalling entries above are missing. They sit where those
            // entries would have been, so the answer is where the question was.
            MenuNote {
                shown: !menu.mine
                label: "not yours - signals refused"
                labelColor: Theme.warn
            }
            // The panel is in its own process table. Ending it takes the bar,
            // the wallpaper and every popup with it, and there is no undo and
            // nothing left on screen to explain what happened.
            MenuNote {
                shown: menu.isSelf
                label: "this is the panel - signals refused"
                labelColor: Theme.warn
            }
        }
    }
}

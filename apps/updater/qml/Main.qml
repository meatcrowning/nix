import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// updater's window: the flake's inputs on the left, a live command log on the
// right, and every global control in the hyprvtb titlebar (docs/DESIGN.md §12).
// The three PINNED inputs are marked and guarded — bumping one is on his
// ask-first list, so it never rides along with "update everything" and a single
// bump of one asks a second time. Applying rewrites the real flake.lock and
// then runs this host's rebuild wrapper; the confirm overlay says so first
// (docs/DESIGN.md §10 — never offer an action that silently costs something).
Window {
    id: win

    // "dim unfocused" off (Settings > Appearance) keeps the window on its
    // focused tones (docs/DESIGN.md §3.1.1's off switch); native dim is off
    // then too, so the body must not grey itself.
    readonly property bool renderActive: win.active
        || (typeof DeskStyle !== "undefined" && !DeskStyle.dimUnfocused)
    readonly property color fgAccent: renderActive ? Theme.accent  : Theme.inactive
    readonly property color fgText:   renderActive ? Theme.text    : Theme.inactive
    readonly property color fgDim:    renderActive ? Theme.textDim : Theme.inactive

    TextMetrics {
        id: metrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real cellW: metrics.width > 0 ? metrics.width / 10
                                                    : Math.round(0.533 * Theme.fontSize)

    Motion { id: motion }

    property string logText: ""
    property string status: ""

    title: "updater"
    width: 1000
    height: 720
    minimumWidth: 520
    minimumHeight: 320
    visible: true
    color: Theme.bg

    // ---- a pending apply, held for the confirm overlay ----
    property var pendingNames: []
    property bool pendingPinned: false

    function askUpdate(names) {
        if (Runner.busy || !names || names.length === 0) return;
        var pinned = false;
        for (var i = 0; i < names.length; i++)
            if (names[i] === "hyprland" || names[i] === "hyprland-air"
                || names[i] === "nixpkgs-quickshell") pinned = true;
        pendingNames = names;
        pendingPinned = pinned;
        confirm.open = true;
    }
    function doPending() {
        confirm.open = false;
        Runner.updateInputs(pendingNames);
    }

    // ---- hyprvtb titlebar: updater's whole chrome ----
    readonly property var tbButtons: [
        { id: "check",  label: "ck", state: 0,
          tip: "check for updates (read-only, no build)" },
        { id: "checkf", label: "c+", state: 0,
          tip: "full check: build closures and diff (slow)" },
        "-",
        { id: "all",    label: "up", state: 0,
          tip: "update every non-pinned input, then rebuild" },
        "-",
        { id: "stop",   label: "x",  state: Runner.busy ? 0 : 2,
          tip: "stop the running job" },
    ]
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    readonly property string footerStr:
        Runner.busy ? ("running: " + status)
                    : (status !== "" ? status : "idle")
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "check":  if (!Runner.busy) Runner.check(false); break;
            case "checkf": if (!Runner.busy) Runner.check(true);  break;
            case "all":    win.askUpdate(Inputs.nonPinnedNames()); break;
            case "stop":   Runner.stop(); break;
            }
        }
    }

    // Per-input package deltas, cached by input name: the parsed
    // `pkg: old -> new` rows a `diff` run produced, plus which rows are open and
    // which one is building right now. Reassign whole (QML does not react to
    // deep mutation of a var map).
    property var pkgsByInput: ({})
    property var expanded: ({})
    property string previewing: ""

    function toggleRow(name) {
        var e = expanded;
        e[name] = !e[name];
        expanded = e;
        // Building the closure is a real download/build (docs/DESIGN.md §10), so
        // it only runs when he opens a row we have not diffed yet, never on load.
        if (expanded[name] && pkgsByInput[name] === undefined && !Runner.busy) {
            previewing = name;
            Runner.previewInput(name);
        }
    }

    Connections {
        target: Runner
        function onOutput(chunk) {
            win.logText += chunk;
            if (win.logText.length > 400000)
                win.logText = win.logText.slice(win.logText.length - 300000);
            logFlick.toBottom();
        }
        function onStarted(label) { win.status = label; }
        function onFinished(label, ok) {
            win.status = label + (ok ? ": done" : ": FAILED");
            if (win.previewing !== "" && !ok) {
                // build failed/stopped: forget it so a later click retries.
                var m = win.pkgsByInput; delete m[win.previewing];
                win.pkgsByInput = m;
                win.previewing = "";
            }
        }
        function onPackagesReady(name, rows) {
            var m = win.pkgsByInput; m[name] = rows; win.pkgsByInput = m;
            var e = win.expanded; e[name] = true; win.expanded = e;
            if (win.previewing === name) win.previewing = "";
        }
    }

    Component.onCompleted: {
        Titlebar.setButtons(tbButtons);
        Titlebar.setFooter(footerStr);
    }

    // A reusable pixel-era button (docs/DESIGN.md §7.1).
    component Btn: Rectangle {
        id: btn
        property string label: ""
        property bool enabled: true
        property bool danger: false
        signal activated()
        implicitWidth: bt.implicitWidth + 5 * cellW
        implicitHeight: Theme.lineHeight + Theme.gap
        radius: Theme.rounding
        color: !btn.enabled ? Theme.bg
             : ma.pressed ? Theme.highlight
             : ma.containsMouse ? Theme.bgAlt : Theme.bg
        border.width: Theme.ctrlBorder
        border.color: !btn.enabled ? Theme.inactive
                    : btn.danger ? Theme.crit
                    : ma.containsMouse ? win.fgAccent : Theme.border
        PixelText {
            id: bt
            anchors.centerIn: parent
            text: btn.label
            color: !btn.enabled ? Theme.inactive
                 : btn.danger ? Theme.crit : win.fgText
        }
        MouseArea {
            id: ma
            anchors.fill: parent
            hoverEnabled: true
            enabled: btn.enabled
            cursorShape: btn.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: btn.activated()
        }
    }

    // ---- layout: inputs | log ----
    Row {
        anchors.fill: parent
        anchors.margins: Theme.gap
        spacing: Theme.gap

        // ---- inputs pane ----
        Rectangle {
            width: Math.round(parent.width * 0.44)
            height: parent.height
            color: Theme.bg
            border.width: Theme.ctrlBorder
            border.color: win.renderActive ? Theme.border : Theme.inactive

            Column {
                anchors.fill: parent
                anchors.margins: Theme.gap
                spacing: Theme.gap

                PixelText {
                    text: "flake inputs"
                    color: win.fgAccent
                }

                KineticListView {
                    id: list
                    width: parent.width
                    height: parent.height - y
                    clip: true
                    model: Inputs.items
                    spacing: 2
                    ScrollBar.vertical: VScroll { id: listScroll }

                    delegate: Rectangle {
                        id: row
                        readonly property bool isOpen: win.expanded[modelData.name] === true
                        readonly property bool building: win.previewing === modelData.name
                        readonly property var pkgs: win.pkgsByInput[modelData.name]
                        width: list.width - listScroll.barW
                        height: rowBody.implicitHeight + Theme.gap
                        color: rma.containsMouse ? Theme.bgAlt : "transparent"
                        radius: Theme.rounding

                        MouseArea {
                            id: rma
                            anchors.fill: parent
                            hoverEnabled: true
                        }

                        Column {
                            id: rowBody
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: Theme.gap
                            anchors.rightMargin: Theme.gap
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.gap

                            Row {
                                width: parent.width
                                spacing: Theme.gap

                                Column {
                                    id: rowCol
                                    width: parent.width - diffBtn.width - upBtn.width
                                           - 2 * parent.spacing
                                    anchors.verticalCenter: parent.verticalCenter
                                    Row {
                                        spacing: cellW
                                        PixelText {
                                            text: (row.isOpen ? "- " : "+ ") + modelData.name
                                            color: win.fgText
                                        }
                                        PixelText {
                                            visible: modelData.pinned
                                            text: "[pinned]"
                                            color: Theme.warn
                                        }
                                        PixelText {
                                            visible: modelData.follows !== ""
                                            text: "follows " + modelData.follows
                                            color: Theme.textDim
                                        }
                                    }
                                    PixelText {
                                        visible: modelData.rev !== ""
                                        text: modelData.rev + "  " + modelData.date
                                              + (modelData.age >= 0 ? "  " + modelData.age + "d old" : "")
                                        color: win.fgDim
                                    }
                                }

                                Btn {
                                    id: diffBtn
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: modelData.updatable
                                    label: row.building ? "…" : "diff"
                                    enabled: !Runner.busy || row.isOpen
                                    onActivated: win.toggleRow(modelData.name)
                                }

                                Btn {
                                    id: upBtn
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: modelData.updatable
                                    label: "update"
                                    danger: modelData.pinned
                                    enabled: !Runner.busy
                                    onActivated: win.askUpdate([modelData.name])
                                }
                            }

                            // Expanded per-package delta (docs/DESIGN.md §10: the
                            // build cost is stated, and it only runs on demand).
                            Column {
                                visible: row.isOpen
                                width: parent.width
                                spacing: 2
                                leftPadding: 3 * cellW

                                PixelText {
                                    visible: row.building
                                    text: "building the updated closure to diff — slow"
                                    color: Theme.warn
                                }
                                PixelText {
                                    visible: !row.building && row.pkgs !== undefined
                                             && row.pkgs.length === 0
                                    text: "no package version changes"
                                    color: win.fgDim
                                }
                                Repeater {
                                    model: (!row.building && row.pkgs !== undefined)
                                           ? row.pkgs : []
                                    delegate: PixelText {
                                        width: row.width - 4 * cellW - listScroll.barW
                                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                                        text: modelData.name + ": " + modelData.old
                                              + " -> " + modelData.new
                                        color: win.fgText
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---- log pane ----
        Rectangle {
            width: parent.width - Math.round(parent.width * 0.44) - parent.spacing
            height: parent.height
            color: Theme.bg
            border.width: Theme.ctrlBorder
            border.color: win.renderActive ? Theme.border : Theme.inactive

            KineticFlickable {
                id: logFlick
                anchors.fill: parent
                anchors.margins: Theme.gap
                clip: true
                contentWidth: width
                contentHeight: logLabel.implicitHeight
                ScrollBar.vertical: VScroll { id: logScroll }

                function toBottom() {
                    // Stay pinned to the tail while output streams in.
                    contentY = Math.max(0, contentHeight - height);
                }

                PixelText {
                    id: logLabel
                    width: logFlick.width - logScroll.barW
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                    text: win.logText !== "" ? win.logText
                        : "Press  ck  to check for updates (read-only).\n\n"
                          + "up  updates every non-pinned input and rebuilds via\n"
                          + Host.rebuild + ".\n\n"
                          + "hyprland, hyprland-air and nixpkgs-quickshell are pinned\n"
                          + "on purpose and are never touched by  up  — bump one from\n"
                          + "its own row, deliberately."
                    color: win.logText !== "" ? win.fgText : win.fgDim
                }
            }
        }
    }

    // ---- confirm overlay for any apply ----
    Item {
        id: confirm
        anchors.fill: parent
        property bool open: false
        visible: open

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.55)
            MouseArea { anchors.fill: parent; onClicked: confirm.open = false }
        }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 8 * Theme.gap, 64 * cellW)
            height: box.implicitHeight + 3 * Theme.gap
            color: Theme.bg
            border.width: Math.max(1, Theme.windowBorderWidth)
            border.color: win.pendingPinned ? Theme.crit : Theme.windowBorder
            radius: Theme.rounding

            Column {
                id: box
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Theme.gap
                spacing: Theme.gap

                PixelText {
                    text: win.pendingPinned ? "bump a PINNED input?" : "update and rebuild?"
                    color: win.pendingPinned ? Theme.crit : Theme.accent
                }
                PixelText {
                    width: parent.width
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                    color: Theme.text
                    text: "nix flake update " + win.pendingNames.join(" ")
                          + "\n" + Host.rebuild
                          + "\n\nThis rewrites flake.lock; review and commit it yourself"
                          + " when you are happy."
                }
                PixelText {
                    visible: win.pendingPinned
                    width: parent.width
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                    color: Theme.warn
                    text: "These three are pinned on purpose (flake.nix) and a bump is"
                          + " on your ask-first list. On book a hyprland/quickshell move"
                          + " is a from-source build, and a compositor pin bump means no"
                          + " live plugin hot-swap until next login."
                }

                Row {
                    spacing: Theme.gap
                    Btn {
                        label: "cancel"
                        onActivated: confirm.open = false
                    }
                    Btn {
                        label: win.pendingPinned ? "bump anyway" : "update"
                        danger: win.pendingPinned
                        onActivated: win.doPending()
                    }
                }
            }
        }
    }
}

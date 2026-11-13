import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Dialogs
import "../../qmlcommon"

// Coder's content: the session list on the left, the current session's
// transcript in the middle, the composer underneath.
//
// AN ITEM, NOT A WINDOW: under Hyprland Main.qml wraps it and the compositor
// draws the titlebar; under Plasma main.py puts it in a kdeshell QMainWindow
// whose menubar, toolbar and status bar are built from `actions` and the
// status* properties below (apps/AGENTS.md, Plasma chrome and shell).
Item {
    id: root
    NativeContentContext {}

    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

    Rectangle { anchors.fill: parent; color: Theme.windowFill; z: -2 }
    StyledBackground { anchors.fill: parent; z: -1 }

    readonly property color fg: plasma ? Theme.windowText : Theme.text
    readonly property color fgDim: plasma ? Theme.disabledText : Theme.textDim
    readonly property color rule: Theme.border
    readonly property font monoFont: (typeof DeskStyle !== "undefined" && DeskStyle
                                      && typeof DeskStyle.editorFontForScale === "function")
                                     ? DeskStyle.editorFontForScale(Screen.devicePixelRatio)
                                     : Theme.editorFontForScale(Screen.devicePixelRatio)

    // ---- state ------------------------------------------------------------
    property bool sidebarShown: App.pref("sidebar", true) !== false
    property int sidebarW: Math.max(200, Number(App.pref("sidebarWidth", 280)) || 280)
    property var attachments: []

    readonly property string windowTitle: Session.active ? Session.title + " - Coder" : "Coder"

    readonly property string statusLine: {
        if (!Session.active) return "";
        var s = Session.state;
        if (Session.pending > 0) return "waiting for approval";
        if (s === "running") return Session.backend + " working";
        if (s === "starting") return "starting " + Session.backend;
        if (s === "failed") return Session.error !== "" ? Session.error : Session.backend + " failed";
        if (s === "exited") return Session.backend + " exited";
        return "";
    }
    readonly property real statusProgress: -1
    readonly property string statusRight: {
        var parts = [];
        if (Session.usageText !== "") parts.push(Session.usageText);
        if (App.limitsText !== "") parts.push(App.limitsText);
        if (App.runningCount > 1) parts.push(App.runningCount + " running");
        return parts.join("   ");
    }

    // ---- actions: one table for the menubar, toolbar and titlebar --------------
    readonly property var actions: [
        { id: "new-claude", menu: "file", menuText: "New Claude Session", icon: "document-new",
          tip: "new claude session in " + App.project, shortcut: "Ctrl+N",
          bar: true, barText: "Claude" },
        { id: "new-codex", menu: "file", menuText: "New Codex Session", icon: "document-new",
          tip: "new codex session in " + App.project, shortcut: "Ctrl+Shift+N",
          bar: true, barText: "Codex" },
        { id: "open-project", menu: "file", menuText: "Open Project...", icon: "document-open-folder",
          tip: "choose the folder new sessions start in", shortcut: "Ctrl+O", bar: true },
        "-",
        { id: "close-session", menu: "file", menuText: "Close Session", icon: "window-close",
          shortcut: "Ctrl+W", state: Session.active ? 0 : 2 },
        { id: "send", menu: "session", menuText: "Send", icon: "document-send",
          shortcut: "Ctrl+Return", state: canSend ? 0 : 2 },
        { id: "stop", menu: "session", menuText: "Stop", icon: "process-stop", tip: "interrupt the turn",
          shortcut: "Ctrl+.", bar: true, state: Session.busy ? 0 : 2 },
        "-",
        { id: "fork", menu: "session", menuText: "Fork Session", icon: "split",
          tip: "continue this conversation in a new session", bar: true,
          state: Session.canFork ? 0 : 2 },
        { id: "rename", menu: "session", menuText: "Rename Session...", icon: "edit-rename",
          shortcut: "F2", state: Session.active ? 0 : 2 },
        { id: "attach", menu: "session", menuText: "Attach Image...", icon: "mail-attachment",
          state: Session.active ? 0 : 2 },
        { id: "sidebar", menu: "view", menuText: "Show Sessions", checkable: true,
          shortcut: "F9", state: sidebarShown ? 1 : 0 },
        { id: "expand", menu: "view", menuText: "Expand Tool Details", checkable: true,
          state: App.expandTools ? 1 : 0 },
        { id: "refresh", menu: "view", menuText: "Refresh Sessions", icon: "view-refresh",
          shortcut: "F5" },
        { id: "notify", menu: "settings", menuText: "Notify When a Turn Ends", checkable: true,
          state: notifyOn ? 1 : 0 }
    ]
    readonly property var menuOrder: ["session"]
    property bool notifyOn: App.pref("notify", true) !== false

    readonly property var tbButtons: [
        { id: "new-claude", label: "cl", state: 0, tip: "new claude session" },
        { id: "new-codex", label: "cx", state: 0, tip: "new codex session" },
        { id: "open-project", label: "pr", state: 0, tip: "open project" },
        { id: "stop", label: "st", state: Session.busy ? 0 : 2, tip: "stop" },
        { id: "fork", label: "fk", state: Session.canFork ? 0 : 2, tip: "fork session" },
        { id: "sidebar", label: "ls", state: sidebarShown ? 1 : 0, tip: "show sessions" }
    ]
    onTbButtonsChanged: if (!plasma) Titlebar.setButtons(tbButtons)
    Component.onCompleted: if (!plasma) Titlebar.setButtons(tbButtons)

    readonly property bool canSend: Session.active && !Session.busy
                                    && (composer.text.trim() !== "" || attachments.length > 0)

    function tbAction(id) {
        switch (id) {
        case "new-claude": App.newSession("claude"); composer.forceActiveFocus(); break;
        case "new-codex": App.newSession("codex"); composer.forceActiveFocus(); break;
        case "open-project": folderDialog.open(); break;
        case "close-session": App.closeCurrent(); break;
        case "send": send(); break;
        case "stop": Session.interrupt(); break;
        case "fork": App.fork(); break;
        case "rename": renameField.text = Session.title; renameBox.open = true;
                       renameField.forceActiveFocus(); renameField.selectAll(); break;
        case "attach": imageDialog.open(); break;
        case "sidebar": sidebarShown = !sidebarShown; App.setPref("sidebar", sidebarShown); break;
        case "expand": App.setExpandTools(!App.expandTools); break;
        case "refresh": App.refresh(); break;
        case "notify": notifyOn = !notifyOn; App.setPref("notify", notifyOn); break;
        }
    }

    function send() {
        if (!canSend) return;
        Session.send(composer.text, attachments);
        composer.text = "";
        attachments = [];
        transcriptView.follow = true;
    }

    FolderDialog {
        id: folderDialog
        title: "Open Project"
        currentFolder: "file://" + App.project
        onAccepted: App.setProject(String(selectedFolder))
    }
    FileDialog {
        id: imageDialog
        title: "Attach Image"
        nameFilters: ["Images (*.png *.jpg *.jpeg *.gif *.webp)"]
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            var a = attachments.slice();
            for (var i = 0; i < selectedFiles.length; i++) a.push(String(selectedFiles[i]));
            attachments = a;
        }
    }

    // ---- layout -------------------------------------------------------------
    Item {
        id: sidebar
        visible: sidebarShown
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        width: visible ? Math.min(sidebarW, Math.max(200, root.width * 0.45)) : 0

        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: projectLabel.implicitHeight + 10
            color: "transparent"
            PixelText {
                id: projectLabel
                anchors { left: parent.left; leftMargin: 8; right: parent.right; rightMargin: 8
                          verticalCenter: parent.verticalCenter }
                text: "project  " + App.project
                elide: Text.ElideMiddle
                color: root.fgDim
            }
            MouseArea {
                anchors.fill: parent
                onClicked: folderDialog.open()
                cursorShape: Qt.PointingHandCursor
            }
        }

        KineticListView {
            id: sessionView
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                      top: parent.top; topMargin: projectLabel.implicitHeight + 10 }
            clip: true
            model: Sessions
            ScrollBar.vertical: VScroll { id: sessionBar }
            section.property: "project"
            section.criteria: ViewSection.FullString
            section.delegate: Item {
                required property string section
                width: sessionView.width
                height: secLabel.implicitHeight + 8
                PixelText {
                    id: secLabel
                    anchors { left: parent.left; leftMargin: 8; bottom: parent.bottom; bottomMargin: 2 }
                    text: section
                    font.bold: Theme.plasmaPalette
                    color: root.fgDim
                }
            }
            delegate: Rectangle {
                id: srow
                required property int index
                required property string key
                required property string backend
                required property string title
                required property string state
                required property bool live
                required property string when
                required property int pending
                required property bool unread
                readonly property bool current: App.currentKey === key
                width: sessionView.width - sessionBar.barW
                height: rowCol.implicitHeight + 8
                color: current ? palette.highlight : (srowMouse.containsMouse ? Qt.rgba(palette.highlight.r, palette.highlight.g, palette.highlight.b, 0.35) : "transparent")
                Column {
                    id: rowCol
                    anchors { left: parent.left; leftMargin: 8; right: parent.right; rightMargin: 6
                              verticalCenter: parent.verticalCenter }
                    spacing: 1
                    PixelText {
                        width: parent.width
                        text: srow.title
                        elide: Text.ElideRight
                        font.bold: srow.unread
                        color: srow.current ? palette.highlightedText : root.fg
                    }
                    PixelText {
                        width: parent.width
                        text: srow.backend + "  " + srow.when
                              + (srow.pending > 0 ? "  needs approval"
                                 : srow.state === "running" ? "  working"
                                 : srow.live ? "  open" : "")
                        elide: Text.ElideRight
                        color: srow.pending > 0 ? Theme.warn
                               : (srow.current ? palette.highlightedText : root.fgDim)
                    }
                }
                MouseArea {
                    id: srowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: App.open(srow.key)
                }
            }
            PixelText {
                anchors.centerIn: parent
                visible: sessionView.count === 0
                text: "no sessions yet"
                color: root.fgDim
            }
        }

        Rectangle {    // the drag handle and the rule between the panes
            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
            width: Theme.ctrlBorder > 0 ? Theme.ctrlBorder : 1
            color: root.rule
            MouseArea {
                anchors { fill: parent; leftMargin: -3; rightMargin: -3 }
                cursorShape: Qt.SplitHCursor
                property real startX: 0
                property int startW: 0
                onPressed: (m) => { startX = mapToItem(root, m.x, 0).x; startW = sidebar.width }
                onPositionChanged: (m) => {
                    if (!pressed) return;
                    root.sidebarW = Math.max(200, Math.min(root.width * 0.6,
                                    startW + mapToItem(root, m.x, 0).x - startX));
                }
                onReleased: App.setPref("sidebarWidth", root.sidebarW)
            }
        }
    }

    Item {
        id: main
        anchors { left: sidebar.right; right: parent.right; top: parent.top; bottom: parent.bottom }

        // Header: what this session is and where it runs.
        Item {
            id: header
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: Session.active ? headerCol.implicitHeight + 10 : 0
            visible: Session.active
            Column {
                id: headerCol
                anchors { left: parent.left; leftMargin: 10; right: parent.right; rightMargin: 10
                          verticalCenter: parent.verticalCenter }
                PixelText {
                    width: parent.width
                    text: Session.title
                    elide: Text.ElideRight
                    font.bold: Theme.plasmaPalette
                    color: root.fg
                }
                PixelText {
                    width: parent.width
                    text: Session.backend + "  " + Session.cwd
                    elide: Text.ElideMiddle
                    color: root.fgDim
                }
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1
                color: root.rule
            }
        }

        // Rename, as an inline field under the header (no modal).
        Item {
            id: renameBox
            property bool open: false
            anchors { left: parent.left; right: parent.right; top: header.bottom }
            height: open ? renameField.implicitHeight + 8 : 0
            visible: open
            TextField {
                id: renameField
                anchors { left: parent.left; right: parent.right; margins: 6
                          verticalCenter: parent.verticalCenter }
                placeholderText: "session name"
                onAccepted: { Session.rename(text); renameBox.open = false }
                Keys.onEscapePressed: renameBox.open = false
            }
        }

        KineticListView {
            id: transcriptView
            property bool follow: true
            anchors { left: parent.left; right: parent.right; top: renameBox.bottom
                      bottom: composerBox.top }
            clip: true
            model: Session.transcript
            spacing: 6
            topMargin: 8
            bottomMargin: 8
            ScrollBar.vertical: VScroll { id: transcriptBar }
            onContentYChanged: follow = atYEnd || (contentHeight - contentY - height) < 24
            onCountChanged: if (follow) Qt.callLater(positionViewAtEnd)
            onContentHeightChanged: if (follow) Qt.callLater(positionViewAtEnd)
            onModelChanged: { follow = true; Qt.callLater(positionViewAtEnd) }
            delegate: TranscriptRow {
                width: transcriptView.width - transcriptBar.barW
                host: root
            }

            Column {
                anchors.centerIn: parent
                visible: !Session.active
                spacing: 10
                PixelText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "no session open"
                    color: root.fgDim
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8
                    Button { text: "New Claude Session"; onClicked: root.tbAction("new-claude") }
                    Button { text: "New Codex Session"; onClicked: root.tbAction("new-codex") }
                }
            }
        }

        // ---- composer -----------------------------------------------------------
        Item {
            id: composerBox
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: Session.active ? composerCol.implicitHeight + 12 : 0
            visible: Session.active
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1
                color: root.rule
            }
            Column {
                id: composerCol
                anchors { left: parent.left; right: parent.right; top: parent.top
                          margins: 6; topMargin: 7 }
                spacing: 5

                PixelText {
                    visible: attachments.length > 0
                    width: parent.width
                    text: attachments.length + " image" + (attachments.length === 1 ? "" : "s")
                          + " attached: " + attachments.map(function (a) {
                              return String(a).split("/").pop(); }).join(", ")
                    elide: Text.ElideRight
                    color: root.fgDim
                    MouseArea { anchors.fill: parent; onClicked: attachments = [] }
                }

                KineticFlickable {
                    id: composerFlick
                    width: parent.width
                    height: Math.min(Math.max(composer.implicitHeight, 40), 200)
                    contentWidth: width
                    contentHeight: composer.implicitHeight
                    clip: true
                    TextArea.flickable: TextArea {
                        id: composer
                        wrapMode: TextArea.Wrap
                        placeholderText: Session.busy ? "the agent is working"
                                         : "message " + Session.backend
                        persistentSelection: true
                        selectByMouse: true
                        font: root.monoFont
                        Keys.onPressed: (e) => {
                            if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                                    && !(e.modifiers & Qt.ShiftModifier)) {
                                root.send();
                                e.accepted = true;
                            } else if (e.key === Qt.Key_Escape && Session.busy) {
                                Session.interrupt();
                                e.accepted = true;
                            }
                        }
                        SpellMarks {
                            anchors.fill: parent
                            target: composer
                            viewport: composerFlick
                            textLeft: composer.leftPadding
                            replaceFn: (start, end, word) => Session.correctSpelling(composer, start, end, word)
                        }
                    }
                }

                Row {
                    id: pickers
                    width: parent.width
                    spacing: 6
                    readonly property int pickerW: Math.max(110, Math.min(200, (width - sendBtn.width - 24) / 3))
                    ComboBox {
                        id: modelBox
                        width: pickers.pickerW
                        model: Session.models
                        textRole: "label"
                        valueRole: "id"
                        currentIndex: indexOfValue(Session.model)
                        onActivated: Session.setModel(currentValue)
                        ToolTip.visible: hovered
                        ToolTip.text: "model"
                    }
                    ComboBox {
                        id: effortBox
                        width: pickers.pickerW
                        model: Session.efforts
                        textRole: "label"
                        valueRole: "id"
                        currentIndex: Math.max(0, indexOfValue(Session.effort))
                        onActivated: Session.setEffort(currentValue)
                        ToolTip.visible: hovered
                        ToolTip.text: "reasoning effort"
                    }
                    ComboBox {
                        id: modeBox
                        width: pickers.pickerW
                        model: Session.modes
                        textRole: "label"
                        valueRole: "id"
                        currentIndex: Math.max(0, indexOfValue(Session.mode))
                        onActivated: {
                            if (currentValue === "bypassPermissions" || currentValue === "full access") {
                                confirmMode.mode = currentValue;
                                currentIndex = Qt.binding(function () {
                                    return Math.max(0, indexOfValue(Session.mode)); });
                                confirmMode.open = true;
                            } else {
                                Session.setMode(currentValue);
                            }
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: "permissions"
                    }
                    Button {
                        id: sendBtn
                        text: Session.busy ? "Stop" : "Send"
                        enabled: Session.busy || root.canSend
                        onClicked: Session.busy ? Session.interrupt() : root.send()
                    }
                }

                Row {
                    id: confirmMode
                    property bool open: false
                    property string mode: ""
                    visible: open
                    spacing: 6
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "run every tool without asking?"
                        color: Theme.warn
                    }
                    Button { text: "Allow All"; onClicked: { Session.setMode(confirmMode.mode); confirmMode.open = false } }
                    Button { text: "Cancel"; onClicked: confirmMode.open = false }
                }
            }
        }
    }
}

/*
    org.kde.lam.menubar — the always-there half of a macOS menu bar.

    Plasma's own `org.kde.plasma.appmenu` reports HiddenStatus whenever the
    focused window exports no DBus menu, and a panel drops a hidden applet
    entirely. So the bar goes blank under Vivaldi (Chromium exports no menu at
    all and never will), under every GTK app that does not, and any time focus
    is on nothing. macOS has no such state: the bar always names an owner and
    always has menus under it.

    This applet supplies the part Plasma has no source for, and nothing else.
    It sits immediately LEFT of the stock appmenu applet:

        [kickoff]  [AppName]  [ File Edit View … ]      <- app exports a menu
        [kickoff]  [Vivaldi]  [ Window ]                <- it does not
        [kickoff]  [Desktop]                            <- nothing is focused

    so when the real menus exist they are still the stock applet's, drawn by
    the stock DBusMenu importer, and we only add the bold app-name button macOS
    puts to their left. The Window menu appears only when there are no real
    menus to disagree with it.

    Labels are Title Case, against docs/DESIGN.md §7.2's lowercase rule: these
    buttons sit inches from Dolphin's own "File Edit View", drawn by the KDE
    style in a KDE session (§"In a PLASMA session none of this applies"), and a
    lowercase "window" beside them would read as a bug, not as a house style.

    Every entry does something real — no placeholder that silently fails
    (§10.3). That is why there is no About, no Preferences and no wallpaper
    item: nothing on this machine can be asked for those generically.
*/

import QtQml
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami
import org.kde.taskmanager as TaskManager

PlasmoidItem {
    id: root

    readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical

    // The whole point: never hidden, whatever is or is not focused.
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    preferredRepresentation: fullRepresentation

    // ---- what the bar is currently describing --------------------------

    // The delegate of the window we are naming, or null for the desktop.
    property QtObject shown: null

    readonly property bool onDesktop: shown === null
    readonly property string appLabel: onDesktop ? "Desktop" : shown.appName
    // Non-empty means the stock applet is about to draw this window's real
    // menus to our right, so we must not draw a Window menu beside them.
    readonly property bool appExportsMenu: !onDesktop && shown.menuService.length > 0

    // Opening one of our menus takes keyboard focus off his window, which
    // makes KWin drop the active task — without this the bar would flip to
    // "Desktop" the moment you clicked it. Upstream guards the same way on
    // the containment's own input status; ours has to cover the popup too.
    readonly property bool panelHasFocus: popup.visible
        || Plasmoid.containment.status === PlasmaCore.Types.AcceptingInputStatus

    onPanelHasFocusChanged: if (!panelHasFocus) retrack()

    function retrack() {
        if (root.panelHasFocus) {
            return;
        }
        for (let i = 0; i < taskWatcher.count; ++i) {
            const t = taskWatcher.objectAt(i);
            if (t && t.isActive && t.isWindow) {
                root.shown = t;
                return;
            }
        }
        root.shown = null;
    }

    TaskManager.TasksModel {
        id: tasksModel
        groupMode: TaskManager.TasksModel.GroupDisabled
    }

    // TasksModel roles are only readable from a delegate, so keep one cheap
    // QtObject per task and read the active one out of it.
    Instantiator {
        id: taskWatcher
        model: tasksModel

        delegate: QtObject {
            readonly property int row: index
            readonly property bool isActive: model.IsActive === true
            readonly property bool isWindow: model.IsWindow === true
            readonly property string appName: model.AppName || model.display || "Window"
            readonly property string appId: model.AppId || ""
            readonly property string menuService: model.ApplicationMenuServiceName || ""
            readonly property bool minimized: model.IsMinimized === true
            readonly property bool maximized: model.IsMaximized === true
            readonly property bool fullScreen: model.IsFullScreen === true
            readonly property bool keptAbove: model.IsKeepAbove === true
            readonly property bool closable: model.IsClosable === true
            readonly property bool minimizable: model.IsMinimizable === true
            readonly property bool maximizable: model.IsMaximizable === true
            readonly property bool fullScreenable: model.IsFullScreenable === true

            onIsActiveChanged: root.retrack()
        }

        onObjectAdded: root.retrack()
        onObjectRemoved: (index, object) => {
            if (root.shown === object) {
                root.shown = null;
            }
            root.retrack();
        }
    }

    // ---- doing things ---------------------------------------------------

    P5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []
        onNewData: source => disconnectSource(source)
        function run(cmd) {
            disconnectSource(cmd);
            connectSource(cmd);
        }
    }

    function shortcut(name) {
        runner.run('qdbus org.kde.kglobalaccel /component/kwin '
                   + 'org.kde.kglobalaccel.Component.invokeShortcut "' + name + '"');
    }

    function activeIndex() {
        return tasksModel.makeModelIndex(root.shown.row);
    }

    // Every window of the shown app, as indices that survive the list moving
    // under us while we close them one at a time.
    function siblingIndices() {
        const out = [];
        if (root.onDesktop) {
            return out;
        }
        const id = root.shown.appId;
        const name = root.shown.appName;
        for (let i = 0; i < taskWatcher.count; ++i) {
            const t = taskWatcher.objectAt(i);
            if (!t || !t.isWindow) {
                continue;
            }
            if (id.length > 0 ? t.appId === id : t.appName === name) {
                out.push(tasksModel.makePersistentModelIndex(t.row));
            }
        }
        return out;
    }

    // ---- the menus ------------------------------------------------------
    // Entry shape is docs/DESIGN.md §7.2's: {label, enabled?, separator?,
    // checked?, trigger?}. Destructive last, behind a separator.

    function appEntries() {
        if (root.onDesktop) {
            return [
                { label: "Show Desktop", trigger: () => root.shortcut("Show Desktop") },
                { label: "Overview", trigger: () => root.shortcut("Overview") },
                { separator: true },
                { label: "Display Settings…", trigger: () => runner.run("kcmshell6 kcm_kscreen") },
                { label: "System Settings…", trigger: () => runner.run("systemsettings") },
            ];
        }
        const name = root.shown.appName;
        return [
            {
                label: "Hide " + name,
                enabled: root.shown.minimizable,
                trigger: () => {
                    for (const i of root.siblingIndices()) {
                        tasksModel.requestToggleMinimized(i);
                    }
                },
            },
            { separator: true },
            {
                label: "Quit " + name,
                enabled: root.shown.closable,
                trigger: () => {
                    for (const i of root.siblingIndices()) {
                        tasksModel.requestClose(i);
                    }
                },
            },
        ];
    }

    function windowEntries() {
        if (root.onDesktop) {
            return [];
        }
        return [
            {
                label: root.shown.minimized ? "Restore" : "Minimize",
                enabled: root.shown.minimizable,
                trigger: () => tasksModel.requestToggleMinimized(root.activeIndex()),
            },
            {
                label: "Zoom",
                enabled: root.shown.maximizable,
                trigger: () => tasksModel.requestToggleMaximized(root.activeIndex()),
            },
            {
                label: root.shown.fullScreen ? "Exit Full Screen" : "Enter Full Screen",
                enabled: root.shown.fullScreenable,
                trigger: () => tasksModel.requestToggleFullScreen(root.activeIndex()),
            },
            {
                label: "Keep Above",
                checked: root.shown.keptAbove,
                trigger: () => tasksModel.requestToggleKeepAbove(root.activeIndex()),
            },
            { separator: true },
            {
                label: "Close Window",
                enabled: root.shown.closable,
                trigger: () => tasksModel.requestClose(root.activeIndex()),
            },
        ];
    }

    // ---- the bar --------------------------------------------------------

    component BarButton: PlasmaComponents3.ToolButton {
        property var entries: []

        readonly property bool isOpen: popup.visible && popup.owner === this

        Layout.fillWidth: root.vertical
        Layout.fillHeight: !root.vertical
        down: isOpen
        onClicked: {
            if (isOpen || popup.justClosed()) {
                popup.close();
            } else {
                popup.openFor(this, entries);
            }
        }
        // macOS slides from menu to menu once one is open; so do we.
        onHoveredChanged: if (hovered && popup.visible && !isOpen) popup.openFor(this, entries)
    }

    fullRepresentation: GridLayout {
        id: bar

        LayoutMirroring.enabled: Application.layoutDirection === Qt.RightToLeft
        flow: root.vertical ? GridLayout.TopToBottom : GridLayout.LeftToRight
        rowSpacing: 0
        columnSpacing: 0

        BarButton {
            text: root.appLabel
            font.bold: true
            entries: root.appEntries()
        }

        BarButton {
            text: "Window"
            visible: !root.onDesktop && !root.appExportsMenu
            entries: root.windowEntries()
        }
    }

    // ---- the popup ------------------------------------------------------
    // A PlasmaCore.Dialog rather than a QtQuick Menu: this is a panel applet,
    // and only a real popup window is guaranteed not to be clipped to the
    // panel it drops out of.

    PlasmaCore.Dialog {
        id: popup

        property Item owner: null
        property var entries: []
        // hideOnWindowDeactivate closes us BEFORE the press that caused it
        // reaches the button, so clicking an open menu's own button would
        // close and instantly reopen it. Anything inside this shadow is that.
        property double closedAt: 0
        function justClosed() {
            return !visible && Date.now() - closedAt < 200;
        }

        onVisibleChanged: if (!visible) closedAt = Date.now()

        type: PlasmaCore.Dialog.PopupMenu
        flags: Qt.Popup | Qt.FramelessWindowHint
        hideOnWindowDeactivate: true
        location: Plasmoid.location
        visible: false

        function openFor(button, list) {
            owner = button;
            entries = list;
            visualParent = button;
            visible = true;
        }

        function close() {
            visible = false;
            owner = null;
        }

        mainItem: ColumnLayout {
            spacing: 0

            Repeater {
                model: popup.entries

                delegate: Item {
                    id: row

                    readonly property var entry: modelData
                    readonly property bool isSeparator: entry.separator === true

                    Layout.fillWidth: true
                    Layout.minimumWidth: Kirigami.Units.gridUnit * 8
                    implicitWidth: isSeparator ? 0 : item.implicitWidth
                    implicitHeight: isSeparator ? sep.implicitHeight : item.implicitHeight

                    PlasmaComponents3.MenuSeparator {
                        id: sep
                        visible: row.isSeparator
                        anchors {
                            left: parent.left
                            right: parent.right
                            verticalCenter: parent.verticalCenter
                        }
                    }

                    PlasmaComponents3.ItemDelegate {
                        id: item
                        visible: !row.isSeparator
                        anchors.fill: parent
                        text: row.entry.label || ""
                        enabled: row.entry.enabled !== false
                        icon.name: row.entry.checked === true ? "checkmark" : ""
                        onClicked: {
                            popup.close();
                            if (row.entry.trigger) {
                                row.entry.trigger();
                            }
                        }
                    }
                }
            }
        }
    }
}

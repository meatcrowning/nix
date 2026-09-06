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

        [kickoff] [AppName] [ File Edit View … ]      app exports a menu
        [kickoff] [Vivaldi] [ Window ]                it does not
        [kickoff] [Desktop] [ File Edit Go Window Help ]   nothing focused

    so when the real menus exist they are still the stock applet's, drawn by
    the stock DBusMenu importer, and we only add the bold app-name button macOS
    puts to their left.

    The desktop state follows Finder's own bar — Finder, File, Edit, View, Go,
    Window, Help — [his, 2026-09-05] *"desktop one should have the same entires
    and options as the mac os one"*. Two departures, both forced:

      - VIEW is absent. Every item in Finder's View menu addresses a Finder
        window's chrome or a desktop icon arrangement, and the Plasma desktop
        containment exposes neither on D-Bus — its sort order, icon size and
        toolbox live in the containment's own config, reachable only from its
        right-click menu. A View menu here would be items that do nothing.
      - Items that are macOS services with no counterpart on this machine
        (AirDrop, iCloud Drive, Recents, Dictation, Services) are dropped
        rather than shown greyed for ever.

    Every remaining entry does something real — no placeholder that silently
    fails (docs/DESIGN.md §10.3).

    Labels are Title Case, against §7.2's lowercase rule: these buttons sit
    inches from Dolphin's own "File Edit View", drawn by the KDE style in a KDE
    session (§"In a PLASMA session none of this applies"), and a lowercase
    "window" beside them would read as a bug, not as a house style.
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
    // Non-empty means the stock applet is about to draw this window's real
    // menus to our right, so we must not draw menus of our own beside them.
    readonly property bool appExportsMenu: !onDesktop && shown.menuService.length > 0

    // Opening one of our menus takes keyboard focus off his window, which
    // makes KWin drop the active task — without this the bar would flip to
    // "Desktop" the moment you clicked it. Upstream guards the same way on the
    // containment's own input status; ours has to cover the popup too.
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
            readonly property string title: model.display || model.AppName || "Window"
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

    function shellQuote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'";
    }

    // xdg-open for real paths, so it obeys whatever this session's default
    // file manager is (in Plasma that is Dolphin — home/prog/mime-defaults.nix).
    function openPath(path) {
        runner.run("xdg-open " + shellQuote(path));
    }

    // KIO-only addresses (applications:/, remote:/) are not something xdg-open
    // can hand to a non-KDE handler, so they go straight to Dolphin.
    function openKio(url) {
        runner.run("dolphin " + shellQuote(url));
    }

    function shortcut(name) {
        runner.run("qdbus org.kde.kglobalaccel /component/kwin "
                   + "org.kde.kglobalaccel.Component.invokeShortcut " + shellQuote(name));
    }

    function activeIndex() {
        return tasksModel.makeModelIndex(root.shown.row);
    }

    // Every window of the shown app, as indices that survive the list moving
    // under us while we act on them one at a time.
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

    // The window list Finder's Window menu ends with. `sameAppOnly` narrows it
    // to the app we are naming, which is what macOS shows.
    function windowEntries(sameAppOnly) {
        const out = [];
        const id = root.onDesktop ? "" : root.shown.appId;
        const name = root.onDesktop ? "" : root.shown.appName;
        for (let i = 0; i < taskWatcher.count; ++i) {
            const t = taskWatcher.objectAt(i);
            if (!t || !t.isWindow) {
                continue;
            }
            if (sameAppOnly && !(id.length > 0 ? t.appId === id : t.appName === name)) {
                continue;
            }
            const idx = tasksModel.makePersistentModelIndex(t.row);
            out.push({
                label: t.title,
                checked: t.isActive,
                trigger: () => tasksModel.requestActivate(idx),
            });
        }
        return out;
    }

    // ---- the menus ------------------------------------------------------
    // Entry shape is docs/DESIGN.md §7.2's: {label, enabled?, separator?,
    // checked?, trigger?}. Destructive last, behind a separator. Menus are
    // built at open time, so a menu can never show stale window state.

    function desktopMenus() {
        const menus = [
            {
                title: "Desktop",
                bold: true,
                build: () => [
                    { label: "About This System", trigger: () => runner.run("kinfocenter") },
                    { separator: true },
                    { label: "Settings…", trigger: () => runner.run("systemsettings") },
                    { label: "Display Settings…", trigger: () => runner.run("kcmshell6 kcm_kscreen") },
                    { separator: true },
                    { label: "Hide Others", trigger: () => root.shortcut("Show Desktop") },
                    { label: "Show All", trigger: () => root.shortcut("Overview") },
                    { separator: true },
                    {
                        label: "Empty Trash…",
                        trigger: () => runner.run(
                            "kdialog --warningcontinuecancel "
                            + "'Are you sure you want to permanently erase the items in the Trash?' "
                            + "--continue-label 'Empty Trash' && ktrash6 --empty"),
                    },
                ],
            },
            {
                title: "File",
                build: () => [
                    { label: "New Window", trigger: () => root.openPath("~/") },
                    { label: "Open Trash", trigger: () => root.openKio("trash:/") },
                    { separator: true },
                    { label: "Find…", trigger: () => runner.run("krunner") },
                ],
            },
            {
                title: "Edit",
                build: () => [
                    {
                        label: "Show Clipboard",
                        trigger: () => runner.run("qdbus org.kde.klipper /klipper "
                                                  + "org.kde.klipper.klipper.showKlipperPopupMenu"),
                    },
                ],
            },
            {
                title: "Go",
                build: () => [
                    { label: "Documents", trigger: () => root.openPath("~/Documents") },
                    { label: "Desktop", trigger: () => root.openPath("~/Desktop") },
                    { label: "Downloads", trigger: () => root.openPath("~/Downloads") },
                    { label: "Home", trigger: () => root.openPath("~/") },
                    { label: "Computer", trigger: () => root.openPath("/") },
                    { label: "Network", trigger: () => root.openKio("remote:/") },
                    { label: "Applications", trigger: () => root.openKio("applications:/") },
                    { separator: true },
                    {
                        label: "Go to Folder…",
                        trigger: () => runner.run(
                            "d=$(kdialog --getexistingdirectory \"$HOME\") && xdg-open \"$d\""),
                    },
                    { label: "Connect to Server…", trigger: () => root.openKio("remote:/") },
                ],
            },
        ];

        const windows = root.windowEntries(false);
        if (windows.length > 0) {
            menus.push({ title: "Window", build: () => root.windowEntries(false) });
        }
        menus.push({
            title: "Help",
            build: () => [{ label: "KDE Help", trigger: () => runner.run("khelpcenter") }],
        });
        return menus;
    }

    function appMenus() {
        // KDE applications retain only the stock DBusMenu applet to our
        // right.  The application-name button is deliberately absent: it was
        // a second, non-native title in the panel rather than a useful menu.
        if (root.appExportsMenu) {
            return [];
        }

        // Apps without a DBus menu (notably Vivaldi) still need an honest
        // window menu.  There is no app-name/title button before it.
        return [{
            title: "Window",
            build: () => {
                const out = [
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
                ];
                const windows = root.windowEntries(true);
                if (windows.length > 1) {
                    out.push({ separator: true });
                    for (const w of windows) {
                        out.push(w);
                    }
                }
                out.push({ separator: true });
                out.push({
                    label: "Close Window",
                    enabled: root.shown.closable,
                    trigger: () => tasksModel.requestClose(root.activeIndex()),
                });
                return out;
            },
        }];
    }

    readonly property var barMenus: onDesktop ? desktopMenus() : appMenus()

    // ---- the bar --------------------------------------------------------

    component BarButton: PlasmaComponents3.ToolButton {
        property var menu: null

        readonly property bool isOpen: popup.visible && popup.owner === this

        Layout.fillWidth: root.vertical
        Layout.fillHeight: !root.vertical
        text: menu ? menu.title : ""
        font.bold: menu ? menu.bold === true : false
        down: isOpen

        function openMine() {
            popup.openFor(this, menu.build());
        }

        onClicked: {
            if (isOpen || popup.justClosed()) {
                popup.close();
            } else {
                openMine();
            }
        }
        // macOS slides from menu to menu once one is open; so do we.
        onHoveredChanged: if (hovered && popup.visible && !isOpen) openMine()
    }

    fullRepresentation: GridLayout {
        id: bar

        LayoutMirroring.enabled: Application.layoutDirection === Qt.RightToLeft
        flow: root.vertical ? GridLayout.TopToBottom : GridLayout.LeftToRight
        rowSpacing: 0
        columnSpacing: 0

        Repeater {
            model: root.barMenus
            delegate: BarButton { menu: modelData }
        }
    }

    // ---- the popup ------------------------------------------------------
    // A PlasmaCore.Dialog rather than a QtQuick Menu: this is a panel applet,
    // and only a real popup window is guaranteed not to be clipped to the
    // panel it drops out of. Do NOT set `flags` on it — Qt.Popup turns this
    // into an xdg_popup parented to the panel's layer surface, which is what
    // made the first version's menus never appear at all (2026-09-05). The
    // `type` alone is what tells KWin what this window is.

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

        // Dialog sizes itself from mainItem's implicit dimensions.  A
        // ColumnLayout with fill-width rows has neither until its parent has a
        // width, which made this dialog 0x0 and produced Plasma's "trying to
        // show an empty dialog" warning.  This Column is measured from its
        // delegates alone, before the dialog maps.
        mainItem: Item {
            implicitWidth: Math.max(1, menuColumn.implicitWidth)
            implicitHeight: Math.max(1, menuColumn.implicitHeight)
            width: implicitWidth
            height: implicitHeight

            Column {
                id: menuColumn
                spacing: 0

                Repeater {
                    model: popup.entries

                    delegate: Item {
                        id: row

                        readonly property var entry: modelData
                        readonly property bool isSeparator: entry.separator === true

                        implicitWidth: isSeparator ? 0
                                                   : Math.max(Kirigami.Units.gridUnit * 8,
                                                              item.implicitWidth)
                        width: isSeparator ? menuColumn.width : implicitWidth
                        height: isSeparator ? Kirigami.Units.smallSpacing * 3
                                            : item.implicitHeight

                        Rectangle {
                            visible: row.isSeparator
                            height: 1
                            color: Kirigami.Theme.textColor
                            opacity: 0.2
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
}

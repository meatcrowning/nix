/*
    One shared panel area for native app menus, browser/desktop fallbacks,
    and the maximized window title. The native menus remain Plasma's stock
    applet, embedded by our interface so its importer and keyboard handling
    stay intact on both NixOS and Fedora.
*/

import QtQml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami
import org.kde.ksvg as KSvg
import org.kde.taskmanager as TaskManager

PlasmoidItem {
    id: root

    readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical

    // Keep one representation alive across task changes. Recreating its
    // delegates while TasksModel removes rows can crash QQmlDelegateModel.
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    preferredRepresentation: fullRepresentation

    // ---- what the bar is currently describing --------------------------

    // The delegate of the window we are naming, or null for the desktop.
    property QtObject shown: null
    // A click on the desktop must not resurrect the previously focused app
    // when our menu closes.  Only an actual task activation clears this.
    property bool desktopPinned: false

    readonly property bool folded: shown !== null && shown.maximized
        && !shown.fullScreen && !shown.minimized && !vertical

    readonly property bool onDesktop: shown === null
    // Native menus are embedded in the shared area; suppress fallback menus.
    readonly property bool appExportsMenu: !onDesktop && shown.menuService.length > 0

    // Keep the desktop delegates alive.  Returning from a DBus menu then only
    // changes their visibility, instead of destroying and recreating a
    // Repeater between frames.
    readonly property bool showDesktopMenus: onDesktop

    // Opening one of our menus takes keyboard focus off his window, which
    // makes KWin drop the active task — without this the bar would flip to
    // "Desktop" the moment you clicked it. Upstream guards the same way on the
    // containment's own input status; ours has to cover the popup too.
    readonly property bool panelHasFocus: popup.visible || popup.switching || Plasmoid.nativeMenuOpen
        || Plasmoid.containment.status === PlasmaCore.Types.AcceptingInputStatus

    onPanelHasFocusChanged: if (!panelHasFocus) retrack()

    function retrack() {
        if (root.panelHasFocus || root.desktopPinned) {
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
        root.desktopPinned = true;
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

            onIsActiveChanged: {
                if (isActive && isWindow) {
                    root.desktopPinned = false;
                }
                root.retrack();
            }
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
                title: "File",
                build: () => [
                    { label: "New Window", trigger: () => root.openPath("~/") },
                    { label: "Open Trash", trigger: () => root.openKio("trash:/") },
                    { separator: true },
                    { label: "Find…", trigger: () => runner.run("krunner") },
                    { separator: true },
                    { label: "Settings…", trigger: () => runner.run("systemsettings") },
                    { label: "Display Settings…", trigger: () => runner.run("kcmshell6 kcm_kscreen") },
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

        menus.push({
            title: "Window",
            build: () => {
                const out = [
                    { label: "Hide Others", trigger: () => root.shortcut("Show Desktop") },
                    { label: "Show All", trigger: () => root.shortcut("Overview") },
                ];
                const windows = root.windowEntries(false);
                if (windows.length > 0) {
                    out.push({ separator: true });
                    for (const window of windows) {
                        out.push(window);
                    }
                }
                return out;
            },
        });
        menus.push({
            title: "Help",
            build: () => [
                { label: "About This System", trigger: () => runner.run("kinfocenter") },
                { separator: true },
                { label: "KDE Help", trigger: () => runner.run("khelpcenter") },
            ],
        });
        return menus;
    }

    readonly property string browserCategoryNames: JSON.stringify(Plasmoid.browserMenus.map(m => m.label))

    function appMenus() {
        // KDE applications retain only the stock DBusMenu applet to our
        // right.  The application-name button is deliberately absent: it was
        // a second, non-native title in the panel rather than a useful menu.
        if (root.appExportsMenu) {
            return [];
        }

        // The bridge tracks the active browser window and validates its ID
        // when dispatching actions. Titles arrive independently from KWin and
        // Vivaldi during navigation, so they cannot gate menu availability.
        if (root.shown && root.shown.appId.toLowerCase().includes("vivaldi")
                && root.browserCategoryNames !== "[]") {
            return JSON.parse(root.browserCategoryNames).map((label, index) => ({
                title: label,
                build: () => Plasmoid.browserMenus[index]?.children || [],
            }));
        }

        // Apps without a connected menu source still need an honest
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

    // Build the desktop delegates once. Visibility, not destruction and
    // recreation, handles the desktop/native handoff above.
    readonly property var desktopBarMenus: desktopMenus()
    readonly property var appBarMenus: onDesktop ? [] : appMenus()

    // ---- the bar --------------------------------------------------------

    // Match Plasma's stock app-menu delegate exactly: its menubar frame owns
    // the text inset, hover treatment and font rather than a generic button.
    component BarButton: AbstractButton {
        id: button

        property var menu: null

        readonly property bool isOpen: popup.visible && popup.owner === this

        Layout.fillWidth: root.vertical
        Layout.fillHeight: !root.vertical
        text: menu ? menu.title : ""
        font.bold: menu ? menu.bold === true : false
        hoverEnabled: true
        down: isOpen

        topPadding: rest.margins.top
        leftPadding: rest.margins.left
        rightPadding: rest.margins.right
        bottomPadding: rest.margins.bottom

        background: KSvg.FrameSvgItem {
            id: rest
            imagePath: "widgets/menubaritem"
            prefix: button.down ? "pressed" : (button.hovered ? "hover" : "normal")
        }

        contentItem: PlasmaComponents3.Label {
            text: button.text
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            color: button.down || button.hovered
                ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
        }

        function openMine() {
            popup.openFor(this, menu.build());
        }

        onPressed: {
            if (isOpen || popup.justClosed()) {
                popup.dismiss();
            } else {
                openMine();
            }
        }
        // macOS slides from menu to menu once one is open; so do we.
        onHoveredChanged: if (hovered && popup.visible && !isOpen) openMine()
    }

    fullRepresentation: Item {
        id: bar
        readonly property bool revealed: !root.folded || hover.hovered
            || root.panelHasFocus || menuGrid.activeFocus
        readonly property var nativeItem: nativeHost.menuItem
        readonly property var nativeRepresentation: nativeItem ? nativeItem.fullRepresentationItem : null
        implicitWidth: Math.max(menuGrid.implicitWidth,
            root.folded ? Math.min(titleLabel.implicitWidth + 12, 320) : 0)
        implicitHeight: Math.max(menuGrid.implicitHeight, 22)
        Layout.minimumWidth: implicitWidth
        Layout.minimumHeight: implicitHeight
        LayoutMirroring.enabled: Application.layoutDirection === Qt.RightToLeft

        HoverHandler { id: hover }

        PlasmaComponents3.Label {
            id: titleLabel
            anchors.fill: parent
            anchors.leftMargin: 4
            anchors.rightMargin: 8
            text: root.folded ? root.shown.title : ""
            textFormat: Text.PlainText
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            opacity: bar.revealed ? 0 : 1
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Kirigami.Units.longDuration; easing.type: Easing.InOutQuad } }
        }

        GridLayout {
            id: menuGrid
            anchors.fill: parent
            flow: root.vertical ? GridLayout.TopToBottom : GridLayout.LeftToRight
            rowSpacing: 0
            columnSpacing: 0
            opacity: bar.revealed ? 1 : 0
            enabled: bar.revealed
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Kirigami.Units.longDuration; easing.type: Easing.InOutQuad } }

            Item {
                id: nativeHost
                property var menuItem: null
                visible: root.appExportsMenu
                implicitWidth: bar.nativeRepresentation ? bar.nativeRepresentation.implicitWidth : 0
                implicitHeight: bar.nativeRepresentation ? bar.nativeRepresentation.implicitHeight : 22
                Layout.preferredWidth: implicitWidth
                Layout.fillHeight: true
                Component.onCompleted: menuItem = Plasmoid.createNativeMenu(this)
                // Plasma defers its representation until it has a nonzero size.
                onWidthChanged: if (menuItem) menuItem.width = Math.max(1, width)
                onHeightChanged: if (menuItem) menuItem.height = Math.max(1, height)
                onMenuItemChanged: if (menuItem) {
                    menuItem.width = Math.max(1, width);
                    menuItem.height = Math.max(1, height);
                }
            }
            Repeater {
                model: root.desktopBarMenus
                delegate: BarButton {
                    visible: root.showDesktopMenus
                    menu: modelData
                }
            }

            Repeater {
                model: root.showDesktopMenus ? [] : root.appBarMenus
                delegate: BarButton { menu: modelData }
            }

            Item { Layout.fillWidth: true; visible: root.folded }
            RowLayout {
                visible: root.folded
                spacing: 0
                Layout.fillHeight: true

                PlasmaComponents3.ToolButton {
                    icon.name: "window-close"
                    Accessible.name: qsTr("Close Window")
                    enabled: root.folded && root.shown.closable
                    implicitHeight: 22
                    implicitWidth: 22
                    padding: 2
                    icon.width: 14
                    icon.height: 14
                    focusPolicy: Qt.NoFocus
                    Layout.preferredWidth: 22
                    Layout.fillHeight: true
                    onClicked: if (root.folded) tasksModel.requestClose(root.activeIndex())
                    PlasmaComponents3.ToolTip.text: Accessible.name
                }
                PlasmaComponents3.ToolButton {
                    icon.name: "window-minimize"
                    Accessible.name: qsTr("Minimize")
                    enabled: root.folded && root.shown.minimizable
                    implicitHeight: 22
                    implicitWidth: 22
                    padding: 2
                    icon.width: 14
                    icon.height: 14
                    focusPolicy: Qt.NoFocus
                    Layout.preferredWidth: 22
                    Layout.fillHeight: true
                    onClicked: if (root.folded) tasksModel.requestToggleMinimized(root.activeIndex())
                    PlasmaComponents3.ToolTip.text: Accessible.name
                }
                PlasmaComponents3.ToolButton {
                    icon.name: "window-restore"
                    Accessible.name: qsTr("Restore")
                    enabled: root.folded && root.shown.maximizable
                    implicitHeight: 22
                    implicitWidth: 22
                    padding: 2
                    icon.width: 14
                    icon.height: 14
                    focusPolicy: Qt.NoFocus
                    Layout.preferredWidth: 22
                    Layout.fillHeight: true
                    onClicked: if (root.folded) tasksModel.requestToggleMaximized(root.activeIndex())
                    PlasmaComponents3.ToolTip.text: Accessible.name
                }
            }
        }
    }

    // ---- the popup ------------------------------------------------------
    // The native interface opens a real QMenu, matching the stock appmenu's
    // separate Oxygen-themed surface and its below-the-panel placement.
    property var nativeEntries: []

    Connections {
        target: Plasmoid
        function onMenuTriggered(index) {
            const entry = root.nativeEntries[index];
            root.nativeEntries = [];
            if (entry && entry.trigger) {
                entry.trigger();
            }
        }
        function onMenuClosed() {
            const serial = ++popup.serial;
            // QMenu hides before QAction::triggered. Keep its entries and
            // focused task until the action has run; a new menu cancels this.
            Qt.callLater(() => {
                if (popup.serial !== serial) return;
                root.nativeEntries = [];
                popup.owner = null;
                popup.closedAt = Date.now();
                popup.visible = false;
            });
        }
    }

    QtObject {
        id: popup
        property bool visible: false
        property bool switching: false
        property int serial: 0
        property Item owner: null
        property double closedAt: 0

        function justClosed() {
            return !visible && Date.now() - closedAt < 200;
        }

        function openFor(button, list) {
            switching = true;
            Plasmoid.closeMenu();
            ++serial;
            root.nativeEntries = list;
            owner = button;
            visible = true;
            function nativeEntry(entry) {
                const result = {
                    label: entry.label || "",
                    enabled: entry.enabled !== false,
                    checked: entry.checked === true,
                    separator: entry.separator === true,
                    checkable: entry.checkable === true,
                    shortcut: entry.shortcut || "",
                    id: entry.id || "",
                    browser: entry.id !== undefined || entry.children !== undefined,
                };
                if (entry.children !== undefined) result.children = entry.children.map(nativeEntry);
                return result;
            }
            const nativeList = list.map(nativeEntry);
            Plasmoid.openMenu(button, nativeList);
            switching = false;
        }

        function dismiss() {
            Plasmoid.closeMenu();
        }
    }
}

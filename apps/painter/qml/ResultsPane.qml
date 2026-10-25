import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

// Shared results scene: Plasma places history beside the preview.
Item {
    id: root

    property Item app
    readonly property bool plasma: app ? app.plasma : false
    readonly property bool sideBySide: plasma && preview.open
    readonly property int inset: root.width < 320 ? 4 : 10
    property real historyWidth: Prefs.get("plasma.historyWidth") > 0
                                ? Prefs.get("plasma.historyWidth") : 300
    readonly property real historySize: Math.min(Math.max(120, historyWidth),
                                                 Math.max(0, (width - 2 * inset) * 0.65))

    readonly property color fgAccent: app ? app.fgAccent : Theme.accent
    readonly property bool winActive: app ? app.winActive : true
    readonly property bool showPreview: app ? app.showPreview : false
    // The gallery's inject rows switch to the parameters view after injecting,
    // so this one travels in both directions. Guarded on both sides: an echo
    // assigning the value already held would fight the other end for a frame.
    property int view: 0
    onViewChanged: if (app && app.view !== root.view) app.view = root.view
    Connections {
        target: root.app
        function onViewChanged() { root.view = root.app.view }
    }

    function injectAll(p) { if (app) app.injectAll(p) }
    function injectPrompt(p) { if (app) app.injectPrompt(p) }
    function injectParams(p) { if (app) app.injectParams(p) }

    // The scene-level menu, the app's when there is one — see ParamsPane.
    property Item ctxMenu: app ? app.ctxMenu : localMenuLoader.item

    // Created ONLY when this pane is a scene of its own. Instantiated
    // unconditionally they were two more CtxMenu objects in the Hyprland
    // window, which is one scene — and the first one a lookup found.
    Loader {
        id: localMenuLoader
        active: !root.app
        anchors.fill: parent
        sourceComponent: CtxMenu { }
    }

    // The gallery item, so the app can read what is selected, and the output
    // view, so the app's zoom rows have something to call.
    property alias gallery: galleryView
    property alias output: outputView
    property alias preview: preview

    // Browse or View — Gwenview's two states, decided by the app because the
    // menus, the shortcuts and Escape all reach it there.
    readonly property bool inView: app ? app.inView : false
    readonly property string viewPath: app ? app.selOne : ""
    readonly property bool viewIsVideo: app ? app.selIsVideo : false

    // NO BACKGROUND OF ITS OWN. This pane used to paint `QPalette.Base` — the
    // colour Dolphin fills its file list with — on the reasoning that a view is
    // not a window. On a LIGHT scheme that is a white slab over most of the
    // window, and the titlebar and toolbar above it are drawn from the style's
    // gradient, so the window stops reading as one object [2026-09-05]. The
    // gradient `StyledBackground` draws at the back of Root.qml shows through
    // instead, and the viewer and the history grid are transparent over it
    // (`Theme.paneFill`); only the tiles and controls keep an inset colour.

    PreviewPane {
        id: preview
        compare: root.app ? root.app.showCompare : true
        winActive: root.winActive
        still: root.app ? root.app.gen.still === true : false
        // WHAT IS SELECTED, which is what this pane now shows. One output: a
        // set has no single thing to draw, and neither has none.
        selPath: galleryView.selection.length === 1 ? galleryView.selection[0] : ""
        anchors.left: parent.left
        anchors.right: root.sideBySide ? historyDivider.left : parent.right
        anchors.top: parent.top
        anchors.bottom: root.sideBySide ? parent.bottom : undefined
        resizable: !root.sideBySide
        anchors.margins: root.width < 320 ? 4 : 10
        anchors.bottomMargin: 0
        // The live viewport is a browsing affordance: in View the whole pane is
        // already one output, and a second smaller copy of a different one
        // above it is noise.
        open: root.showPreview && !root.inView
        // Double-click a finished result to open it properly.
        onOpenRequested: (path) => { if (root.app) root.app.enterView(path) }
        onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
    }

    // Margins shrink with the pane: 10px either side of a 220px column is
    // 9% of it spent on nothing (docs/DESIGN.md §5.2).
    OutputView {
        id: outputView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: preview.visible ? preview.bottom : parent.top
        anchors.bottom: parent.bottom
        anchors.margins: root.width < 320 ? 4 : 10
        anchors.topMargin: preview.visible ? 8 : 0
        visible: root.inView
        source: root.inView ? root.viewPath : ""
        isVideo: root.viewIsVideo
        compare: root.app ? root.app.showCompare : true
        onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
    }

    MouseArea {
        id: historyDivider
        objectName: "historySplitHandle"
        visible: root.sideBySide
        anchors.right: parent.right
        anchors.rightMargin: root.inset + root.historySize
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 8
        cursorShape: Qt.SizeHorCursor
        preventStealing: true
        property real startX: 0
        property real startWidth: 0
        onPressed: function(m) {
            startX = mapToItem(root, m.x, m.y).x
            startWidth = root.historySize
        }
        onPositionChanged: function(m) {
            if (pressed)
                root.historyWidth = Math.max(120, Math.min((root.width - 2 * root.inset) * 0.65,
                    startWidth - (mapToItem(root, m.x, m.y).x - startX)))
        }
        onReleased: Prefs.set("plasma.historyWidth", root.historyWidth)
        Rectangle {
            anchors.centerIn: parent
            width: 1
            height: parent.height
            color: Theme.dim
        }
    }

    Row {
        id: historyControls
        visible: root.plasma && !root.inView
        anchors.left: galleryView.left
        anchors.right: galleryView.right
        anchors.top: parent.top
        spacing: 6
        height: visible ? columnPicker.implicitHeight : 0
        Label {
            id: columnsLabel
            text: "Columns:"
            anchors.verticalCenter: parent.verticalCenter
        }
        ComboBox {
            id: columnPicker
            objectName: "historyColumns"
            width: Math.max(0, parent.width - columnsLabel.width - parent.spacing)
            model: ["Automatic", "1", "2", "3", "4", "5", "6"]
            currentIndex: root.app ? root.app.gridColumns : 0
            onActivated: function(index) { if (root.app) root.app.gridColumns = index }
        }
    }

    GalleryView {
        id: galleryView
        visible: !root.inView
        // 0 = automatic, the width-driven default; see Root's `gridColumns`.
        columns: root.app ? root.app.gridColumns : 0
        anchors.left: root.sideBySide ? historyDivider.right : parent.left
        anchors.right: parent.right
        anchors.top: root.plasma ? historyControls.bottom : (preview.visible ? preview.bottom : parent.top)
        anchors.bottom: parent.bottom
        anchors.margins: root.inset
        anchors.leftMargin: root.sideBySide ? 0 : root.inset
        // FLUSH WITH THE CHROME when there is no preview above it: the grid's
        // own top gap read as a band of nothing between the toolbar and the
        // outputs, and there is nothing for it to separate.
        anchors.topMargin: root.plasma || preview.visible ? 8 : 0
        // ...and flush with the status bar at the other end. The hint line sits
        // at the bottom of this view (GalleryView), so a margin under it is a
        // band of view background with nothing in it.
        anchors.bottomMargin: 0
        onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
        onOpenRequested: (path, isVideo) => { if (root.app) root.app.enterView(path) }
    }
}

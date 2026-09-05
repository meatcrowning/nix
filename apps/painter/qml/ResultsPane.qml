import QtQuick
import "../../qmlcommon"

// The results side: the live preview viewport above the history grid.
//
// Split out of `Root.qml` for the same reason `ParamsPane.qml` was — under
// Plasma this is the QMainWindow's central widget while the parameters sit in
// a dock beside it, which makes them two scenes. Read that file's header for
// why each pane declares `id: root` and forwards to `app` rather than relying
// on QML resolving ids up the creation-context chain.
Item {
    id: root

    property Item app

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
        // WHAT IS SELECTED, which is what this pane now shows. One output: a
        // set has no single thing to draw, and neither has none.
        selPath: galleryView.selection.length === 1 ? galleryView.selection[0] : ""
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
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

    GalleryView {
        id: galleryView
        visible: !root.inView
        // 0 = automatic, the width-driven default; see Root's `gridColumns`.
        columns: root.app ? root.app.gridColumns : 0
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: preview.visible ? preview.bottom : parent.top
        anchors.bottom: parent.bottom
        anchors.margins: root.width < 320 ? 4 : 10
        // FLUSH WITH THE CHROME when there is no preview above it: the grid's
        // own top gap read as a band of nothing between the toolbar and the
        // outputs, and there is nothing for it to separate.
        anchors.topMargin: preview.visible ? 8 : 0
        // ...and flush with the status bar at the other end. The hint line sits
        // at the bottom of this view (GalleryView), so a margin under it is a
        // band of view background with nothing in it.
        anchors.bottomMargin: 0
        onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
        onOpenRequested: (path, isVideo) => { if (root.app) root.app.enterView(path) }
    }
}

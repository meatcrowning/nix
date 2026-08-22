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

    // The gallery item, so the app can read what is selected.
    property alias gallery: galleryView

    PreviewPane {
        id: preview
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: root.width < 320 ? 4 : 10
        anchors.bottomMargin: 0
        open: root.showPreview
    }

    // Margins shrink with the pane: 10px either side of a 220px column is
    // 9% of it spent on nothing (docs/DESIGN.md §5.2).
    GalleryView {
        id: galleryView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: preview.visible ? preview.bottom : parent.top
        anchors.bottom: parent.bottom
        anchors.margins: root.width < 320 ? 4 : 10
        anchors.topMargin: preview.visible ? 8 : (root.width < 320 ? 4 : 10)
        onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
    }
}

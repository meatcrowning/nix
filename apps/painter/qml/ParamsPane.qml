import QtQuick
import "../../qmlcommon"

// The parameter column, as a pane that can stand on its own.
//
// It was inline in `Root.qml` until the Plasma face grew a real `QDockWidget`
// around it (pylib/kdeshell.py): a dock is a second `QQuickWidget`, so this has
// to be loadable as the ROOT of its own scene, with no Root.qml above it.
//
// WHY THE FORWARDING BLOCK BELOW EXISTS. Every panel in here reaches the app
// through the id `root` — `root.gen`, `root.set(...)`, `root.fgAccent` — which
// works because QML resolves an id up the chain of creation contexts, so a file
// instantiated by Root.qml sees Root.qml's ids. Loaded standalone there is no
// such chain and every one of those names is undefined. So this pane declares
// `id: root` itself and presents the SAME surface, forwarding to `app` when it
// has one. One path in both sessions, deliberately: a forwarding layer that
// only runs under Plasma is a forwarding layer nothing tests.
Item {
    id: root

    // The app (Root.qml). Null when this pane is a scene of its own — which is
    // exactly what the dock does — and then the pane is inert rather than
    // broken: `gen` is an empty object, not a crash.
    property Item app

    // ------------------------------------------------------- the app surface
    readonly property var gen: app ? app.gen : ({})
    readonly property color fgAccent: app ? app.fgAccent : Theme.accent
    readonly property bool winActive: app ? app.winActive : true

    // Written from the inside (the drop wells' hover), read by the app's
    // Ctrl+V target picker — so it travels up rather than down.
    property string hoveredWell: ""
    onHoveredWellChanged: if (app) app.hoveredWell = root.hoveredWell

    function set(key, value) { if (app) app.set(key, value) }
    function setMs(key, value) { if (app) app.setMs(key, value) }
    function recomputeDims() { if (app) app.recomputeDims() }
    function releaseFocus() { if (app) app.releaseFocus() }

    // The two scene-level overlays a `Picker` and a right-click need. The app's
    // own are used when there is one — they are anchored to the whole window
    // there, and a dropdown clamped into this 300px column instead would be the
    // clipping those overlays exist to avoid. The local pair is for the
    // standalone case; under Plasma the `+plasma` variants are native popups
    // that use neither.
    property Item pickerOverlay: app ? app.pickerOverlay : localPickerLoader.item
    property Item ctxMenu: app ? app.ctxMenu : localMenuLoader.item
    //: ...and the completer's list, for the same reason: a 130px prompt box
    //: cannot hold one.
    property Item tagPopup: app ? app.tagPopup : localTagLoader.item


    // Created ONLY when this pane is a scene of its own. Instantiated
    // unconditionally they were two more PickerOverlay objects in the Hyprland
    // window, which is one scene — and the first one a lookup found.
    Loader {
        id: localPickerLoader
        active: !root.app
        anchors.fill: parent
        sourceComponent: PickerOverlay { }
    }

    // Created ONLY when this pane is a scene of its own. Instantiated
    // unconditionally they were two more CtxMenu objects in the Hyprland
    // window, which is one scene — and the first one a lookup found.
    Loader {
        id: localMenuLoader
        active: !root.app
        anchors.fill: parent
        sourceComponent: CtxMenu { }
    }

    Loader {
        id: localTagLoader
        active: !root.app
        anchors.fill: parent
        sourceComponent: TagPopup { }
    }

    // True when this pane is the root of its own scene — the Plasma dock. The
    // styled background is a crop of the WINDOW aligned to the VIEW's origin
    // (qmlcommon/StyledBackground.qml), so it lines up only for the item that
    // fills its view; drawn inside a pane offset within a bigger scene it would
    // be the right gradient in the wrong place. Embedded, Root.qml's own copy
    // is already behind this.
    property bool standalone: false
    StyledBackground { anchors.fill: parent; visible: root.standalone }

    // ------------------------------------------------------------- sections
    //
    // ONE ORDER, NOT ONE PER MODE. The panels used to be declared in a fixed
    // order and gated on the mode each belongs to; the order below is that same
    // declaration order, and the same gating still hides what a mode does not
    // have — so an edit preset still leads with its wells and a video preset
    // with its frames, out of ONE list. He can drag any header to move a
    // section, and where he leaves it is remembered
    // (docs/painter-kde-layout.md phase 7).
    readonly property var builtinOrder: [
        "model", "edit", "video", "resolution", "editscale",
        "prompt", "lora", "sampling", "patches", "editseed"
    ]

    // WHICH SECTIONS THIS MODE HAS, in one table rather than a `visible:` on each
    // panel — because the Loader that holds a panel cannot ask the panel. An
    // item's `visible` property reads back the EFFECTIVE visibility, so
    // `Loader.visible: item.visible` latches false the moment it is false once
    // (the loader hides the item, the item then reports hidden) and the whole
    // column stays empty. Measured exactly that way.
    function sectionVisible(key) {
        return key === "edit" || key === "editscale" || key === "editseed" ? App.isEdit
             : key === "video" ? (App.isVideo && !App.isEdit)
             : key === "resolution" || key === "sampling" ? !App.isEdit
             : key === "patches" ? (!App.isVideo && !App.isEdit)
             : true
    }

    function componentFor(key) {
        return key === "model" ? cModel
             : key === "edit" ? cEdit
             : key === "video" ? cVideo
             : key === "resolution" ? cResolution
             : key === "editscale" ? cEditScale
             : key === "prompt" ? cPrompt
             : key === "lora" ? cLora
             : key === "sampling" ? cSampling
             : key === "patches" ? cPatches
             : key === "editseed" ? cEditSeed
             : null
    }

    // A ListModel rather than a JS array, because `move()` MOVES a delegate
    // where a reassigned array rebuilds every one of them — which would destroy
    // the header being dragged, mid-drag.
    ListModel { id: sectionModel }

    // A saved order that has lost a key, or never heard of a new one, must not
    // lose the section: anything the saved list does not name is put back at
    // its BUILT-IN position, after whichever of its built-in predecessors is
    // present. Appending instead would quietly bury a new panel at the bottom.
    function buildSections() {
        var saved = []
        try { saved = JSON.parse(Prefs.get("sections") || "[]") } catch (e) { saved = [] }
        var out = []
        for (var i = 0; i < saved.length; i++)
            if (root.builtinOrder.indexOf(saved[i]) >= 0 && out.indexOf(saved[i]) < 0)
                out.push(saved[i])
        for (var b = 0; b < root.builtinOrder.length; b++) {
            var k = root.builtinOrder[b]
            if (out.indexOf(k) >= 0) continue
            var at = 0
            for (var j = b - 1; j >= 0; j--) {
                var pj = out.indexOf(root.builtinOrder[j])
                if (pj >= 0) { at = pj + 1; break }
            }
            out.splice(at, 0, k)
        }
        sectionModel.clear()
        for (var n = 0; n < out.length; n++) sectionModel.append({ key: out[n] })
    }

    Component.onCompleted: { console.warn('PANE COMPLETED'); root.buildSections() }

    function indexOfSection(key) {
        for (var i = 0; i < sectionModel.count; i++)
            if (sectionModel.get(i).key === key) return i
        return -1
    }

    // Live reordering: the dragged section takes the place of whichever visible
    // section the pointer has passed the MIDDLE of. Midpoints, not edges, so a
    // section never flips back and forth while the pointer sits on a boundary.
    function dragSection(key, sceneY) {
        var from = root.indexOfSection(key)
        if (from < 0) return
        var target = from
        for (var i = 0; i < sectionRep.count; i++) {
            var ld = sectionRep.itemAt(i)
            if (!ld || !ld.visible || i === from) continue
            var mid = ld.mapToItem(null, 0, ld.height / 2).y
            if (i < from && sceneY < mid) { target = i; break }
            if (i > from && sceneY > mid) target = i
        }
        if (target !== from) sectionModel.move(from, target, 1)
    }

    // Written on release, not on every pixel of the drag — one decision, not
    // sixty file writes (the rule Root.qml's splitter set).
    function dropSection() {
        var out = []
        for (var i = 0; i < sectionModel.count; i++) out.push(sectionModel.get(i).key)
        Prefs.set("sections", JSON.stringify(out))
    }

    function resetOrder() {
        Prefs.set("sections", "[]")
        root.buildSections()
    }

    Motion { id: motion }

    // The sections themselves. Each keeps the `visible` gate it had as a
    // declared child, because that gate is what makes one order serve all three
    // modes.
    Component { id: cModel; ModelPicker { width: parent.width; persistKey: "panel.model" } }
    Component {
        id: cEdit
        // EDIT MODE IS AN IMAGE AND A PROMPT, and nothing else: the graph reads
        // the size out of the picture, has no negative to encode and carries the
        // family's own steps/cfg/shift, so the sampler/resolution/patch controls
        // are hidden rather than shown doing nothing (docs/DESIGN.md §10).
        EditPanel { width: parent.width; persistKey: "panel.edit" }
    }
    Component {
        id: cVideo
        // A video family's first/last frame wells are its input images, so they
        // sit in the same place edit's do. No negative prompt, no CFG, no batch,
        // and no aspect while a frame is deciding it — the panels below follow
        // that from the inside.
        VideoPanel {
            width: parent.width
            persistKey: "panel.video"
        }
    }
    Component {
        id: cResolution
        // In image-to-video the size comes out of the dropped image, and MP is
        // the only part of it left to choose — handled inside the panel, which
        // keeps its MP box.
        ResolutionPanel {
            width: parent.width
            persistKey: "panel.resolution"
        }
    }
    Component {
        id: cEditScale
        // Edit's resolution is the output size relative to the dropped image
        // (there is no aspect to type), so its own panel takes the resolution
        // slot in that preset.
        EditScalePanel {
            width: parent.width
            persistKey: "panel.editscale"
        }
    }
    Component {
        id: cPrompt
        PromptEditor {
            width: parent.width
            persistKey: "panel.prompt"
            onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
        }
    }
    Component {
        id: cLora
        // Available in EVERY mode, edit included: an edit model takes a LoRA the
        // same way an image one does — `_build_edit` chains the LoraLoader onto
        // the loader→ModelSampling seam exactly as the image path does, and
        // `_start_jobs` sends `loras.active()` for all three pipelines.
        LoraStack { width: parent.width; persistKey: "panel.lora" }
    }
    Component {
        id: cSampling
        ParamsPanel {
            width: parent.width
            persistKey: "panel.sampling"
        }
    }
    Component {
        id: cPatches
        TogglePanel {
            width: parent.width
            persistKey: "panel.patches"
        }
    }
    Component {
        id: cEditSeed
        // The seed IS read by the edit graph, so the edit preset gets its own
        // seed control — the sampling panel that normally holds it is hidden
        // here. Same SeedField, so it behaves identically.
        SeedPanel { width: parent.width; persistKey: "panel.editseed" }
    }

    // How much room the column gives up at the bottom to a status strip drawn
    // over it. The Hyprland roof has one (QueueBar); a dock does not.
    property int bottomInset: 0

    Rectangle {
        anchors.fill: parent
        color: Theme.windowFill

        KineticFlickable {
            id: controlsFlick
            anchors.fill: parent
            anchors.margins: 10
            // Flush with the chrome, like the results side — the first panel's
            // own frame is the separation.
            anchors.topMargin: 0
            anchors.bottomMargin: root.bottomInset
            contentHeight: controlsCol.implicitHeight
            clip: true
            // NO BAR ON THIS SIDE. The parameter column is a stack of panels
            // that collapse — its length is something he sets, not something he
            // has to navigate — and the gutter cost every control 11-16px of a
            // 300px column. The scrollbar that §9.2 asks for is on the results
            // side, where the content really is unbounded. The wheel and the
            // compositor's kinetic scroll are untouched.

            Column {
                id: controlsCol
                width: controlsFlick.width
                spacing: 10
                // Sections slide out of each other's way while one is being
                // dragged, rather than teleporting — the desktop's one slide
                // duration, never a literal (docs/DESIGN.md §6.2).
                move: Transition {
                    NumberAnimation {
                        properties: "y"
                        duration: motion.ms(motion.slideMs)
                        easing.type: motion.slideEasing
                    }
                }

                Repeater {
                    id: sectionRep
                    model: sectionModel
                    delegate: Loader {
                        width: controlsCol.width
                        sourceComponent: root.componentFor(model.key)
                        // A section its mode does not have contributes nothing:
                        // the Column skips an invisible child, so the modes that
                        // hide a section leave no gap (that is how one order
                        // serves all three — see `builtinOrder`).
                        visible: root.sectionVisible(model.key)
                        onLoaded: {
                            item.sectionKey = model.key
                            if (item.persistKey === "") item.persistKey = "panel." + model.key
                        }
                    }
                }
            }
        }
    }
}

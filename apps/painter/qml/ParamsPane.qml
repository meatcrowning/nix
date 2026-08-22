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

                // ONE SECTION ORDER FOR EVERY PRESET AND MODEL. Whatever the
                // selected model can do, the sections stack in the same order
                // top-to-bottom: input images, resolution, prompt boxes, LoRAs,
                // then the sampler settings. The panels are declared in that
                // order and each is gated on the mode it belongs to; a Column
                // skips invisible children, so the modes that hide a section
                // leave no gap and never reshuffle the ones that remain (image
                // mode has no input images, edit has no aspect, and so on).
                ModelPicker { width: parent.width; persistKey: "panel.model" }

                // --- input images ---
                // EDIT MODE IS AN IMAGE AND A PROMPT, and nothing else: the
                // graph reads the size out of the picture, has no negative to
                // encode and carries the family's own steps/cfg/shift, so the
                // sampler/resolution/patch controls are hidden rather than shown
                // doing nothing (docs/DESIGN.md §10). Its drop wells lead.
                EditPanel {
                    width: parent.width
                    persistKey: "panel.edit"
                    visible: App.isEdit
                }
                // A video family's first/last frame wells are its input images,
                // so they sit in the same place edit's do. No negative prompt,
                // no CFG, no batch, and no aspect while a frame is deciding it —
                // the panels below follow that from the inside.
                VideoPanel {
                    width: parent.width
                    persistKey: "panel.video"
                    visible: App.isVideo && !App.isEdit
                }

                // --- resolution ---
                ResolutionPanel {
                    width: parent.width
                    persistKey: "panel.resolution"
                    visible: !App.isEdit
                    // In image-to-video the size comes out of the dropped image,
                    // and MP is the only part of it left to choose — that is
                    // handled inside the panel, which keeps its MP box.
                }
                // Edit's resolution is the output size relative to the dropped
                // image (there is no aspect to type), so its own panel takes the
                // resolution slot in that preset.
                EditScalePanel {
                    width: parent.width
                    persistKey: "panel.editscale"
                    visible: App.isEdit
                }

                // --- prompt boxes ---
                PromptEditor {
                    width: parent.width
                    persistKey: "panel.prompt"
                    onMenuRequested: (sx, sy, items) => root.ctxMenu.open(sx, sy, items)
                }

                // --- LoRAs ---
                // Available in EVERY mode, edit included: an edit model takes a
                // LoRA the same way an image one does — `_build_edit` chains the
                // LoraLoader onto the loader→ModelSampling seam exactly as the
                // image path does, and `_start_jobs` sends `loras.active()` for
                // all three pipelines. The picker's choices come from the same
                // `compatible_loras` match, so the edit family shows its own
                // (e.g. a Klein LoRA on Flux 2 Klein) and nothing else.
                LoraStack {
                    width: parent.width
                    persistKey: "panel.lora"
                }

                // --- sampler settings ---
                ParamsPanel {
                    width: parent.width
                    persistKey: "panel.sampling"
                    visible: !App.isEdit
                }
                TogglePanel {
                    width: parent.width
                    persistKey: "panel.patches"
                    visible: !App.isVideo && !App.isEdit
                }
                // The seed IS read by the edit graph, so the edit preset gets
                // its own seed control — the sampling panel that normally holds
                // it is hidden here. Same SeedField, so it behaves identically,
                // and it takes the sampler slot in the edit preset.
                SeedPanel {
                    width: parent.width
                    persistKey: "panel.editseed"
                    visible: App.isEdit
                }
                Item { width: 1; height: 6 }
            }
        }
    }
}

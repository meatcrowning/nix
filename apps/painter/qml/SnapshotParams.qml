import QtQuick
import "../../qmlcommon"

Item {
    id: snapshot
    objectName: "snapshotParams"
    property var gen: App.generation
    property color fgAccent: Theme.accent
    property bool winActive: true
    property string hoveredWell: ""
    property alias pickerOverlay: picker
    property alias ctxMenu: menu
    property alias tagPopup: tags
    function set(key, value) {
        var next = Object.assign({}, gen)
        next[key] = value
        gen = next
    }
    function setMs(key, value) {
        var next = Object.assign({}, gen.ms)
        next[key] = value
        set("ms", next)
    }
    function recomputeDims() {
        var dims = App.dims(gen.aspectW + ":" + gen.aspectH, gen.megapixels, gen.multiple)
        set("width", dims.width)
        set("height", dims.height)
    }
    function releaseFocus() { forceActiveFocus() }
    function importImage() {}
    Connections {
        target: App
        function onLayoutEdited(model, doc) { snapshot.set("moss_layout", doc) }
    }
    ParamsPane { anchors.fill: parent; app: snapshot; comparisonMode: true }
    PickerOverlay { id: picker; anchors.fill: parent; z: 100 }
    CtxMenu { id: menu; anchors.fill: parent; z: 101 }
    TagPopup { id: tags; anchors.fill: parent; z: 102 }
}

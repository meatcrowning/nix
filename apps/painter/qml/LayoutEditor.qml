import QtQuick
import QtQuick.Dialogs
import QtQuick.Controls

Control {
    id: editor
    background: null
    implicitHeight: tree.implicitHeight + 12
    readonly property bool nativeStyle: typeof DeskStyle !== "undefined" && DeskStyle.plasma
    Binding { target: editor; property: "palette.window"; value: Theme.bg; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.base"; value: Theme.bg; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.button"; value: Theme.bgAlt; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.light"; value: Theme.bgAlt; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.midlight"; value: Theme.highlight; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.mid"; value: Theme.border; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.dark"; value: Theme.bg; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.alternateBase"; value: Theme.bgAlt; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.text"; value: Theme.text; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.windowText"; value: Theme.text; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.buttonText"; value: Theme.text; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.highlight"; value: Theme.highlight; when: !editor.nativeStyle }
    Binding { target: editor; property: "palette.highlightedText"; value: Theme.accent; when: !editor.nativeStyle }
    Binding { target: editor; property: "font.family"; value: Theme.font; when: !editor.nativeStyle }
    Binding { target: editor; property: "font.pixelSize"; value: Theme.fontSize; when: !editor.nativeStyle }
    required property var generation
    readonly property var bridge: App.layoutEditor
    function sync() {
        if (App.layoutSupport && generation.width > 0 && generation.height > 0)
            bridge.load(App.selectedName, generation.moss_layout || {}, generation.width, generation.height, generation.positive || "")
    }
    onGenerationChanged: sync()
    Component.onCompleted: sync()
    Connections { target: App; function onModelChanged() { editor.sync() } }
    TokenProbe {
        id: regionTokens
        objectName: "regionTokenProbe"
        text: editor.bridge.regionPrompt
        active: App.layoutSupport && editor.bridge.regionIdentity !== ""
    }
    LayoutNode { id: tree; anchors.fill: parent; anchors.margins: 6; spec: editor.bridge.root; bridge: editor.bridge; tokenProbe: regionTokens }
    Connections { target: editor.bridge.toolkitObject; function onReferenceRequested() { reference.open() } }
    FileDialog {
        id: reference
        title: "Reference underlay"
        nameFilters: ["Images (*.png *.jpg *.jpeg *.webp *.bmp)"]
        onAccepted: editor.bridge.reference(selectedFile.toString())
    }
}

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import PainterLayout 1.0
import "../../qmlcommon"

Item {
    id: node
    required property QtObject spec
    required property QtObject bridge
    visible: spec.shown
    enabled: spec.enabled
    implicitWidth: content.item ? content.item.implicitWidth : 0
    implicitHeight: visible && content.item ? content.item.implicitHeight : 0
    Loader {
        id: content
        anchors.fill: parent
        sourceComponent: {
            switch (node.spec.kind) {
            case "row": return rowComponent
            case "column": case "page": case "inspector": return columnComponent
            case "button": return buttonComponent
            case "label": return labelComponent
            case "menu": return menuComponent
            case "tabs": return tabsComponent
            case "list": return listComponent
            case "canvas": return canvasComponent
            default: return fieldComponent
            }
        }
    }
    Component {
        id: rowComponent
        RowLayout {
            spacing: 6
            Repeater {
                model: node.spec.nodes
                Loader {
                    required property QtObject modelData
                    Layout.preferredHeight: item ? item.implicitHeight : 0
                    visible: modelData.shown
                    Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge})
                    Layout.fillWidth: modelData.expand
                    Layout.fillHeight: modelData.expand || modelData.kind === "inspector"
                    Layout.preferredWidth: modelData.kind === "inspector" ? 300 : (item ? item.implicitWidth : 0)
                    Layout.minimumWidth: modelData.kind === "canvas" ? 140 : 0
                }
            }
        }
    }
    Component {
        id: columnComponent
        ColumnLayout {
            spacing: 6
            Repeater {
                model: node.spec.nodes
                Loader {
                    required property QtObject modelData
                    Layout.preferredHeight: item ? item.implicitHeight : 0
                    visible: modelData.shown
                    Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge})
                    Layout.fillWidth: true
                    Layout.fillHeight: modelData.expand
                }
            }
        }
    }
    Component { id: buttonComponent; Button { objectName: node.spec.title === "Add" ? "layoutAdd" : ""; text: node.spec.title; onClicked: node.spec.activate() } }
    Component { id: labelComponent; Label { text: node.spec.title; wrapMode: Text.Wrap; visible: text.length > 0 } }
    Component {
        id: menuComponent
        Button {
            text: node.spec.title
            onClicked: editMenu.open()
            Menu {
                id: editMenu
                y: parent.height
                Instantiator {
                    model: node.spec.nodes
                    delegate: MenuItem {
                        required property QtObject modelData
                        text: modelData.title
                        enabled: modelData.enabled
                        onTriggered: modelData.activate()
                    }
                    onObjectAdded: (index, object) => editMenu.insertItem(index, object)
                    onObjectRemoved: (index, object) => editMenu.removeItem(object)
                }
            }
        }
    }
    Component {
        id: tabsComponent
        ColumnLayout {
            implicitHeight: 400
            TabBar {
                id: tabs
                Layout.fillWidth: true
                Repeater {
                    model: node.spec.nodes
                    TabButton { required property QtObject modelData; text: modelData.title }
                }
            }
            StackLayout {
                currentIndex: tabs.currentIndex
                Layout.fillWidth: true
                Layout.fillHeight: true
                Repeater {
                    model: node.spec.nodes
                    KineticFlickable {
                        id: scroller
                        required property QtObject modelData
                        contentWidth: width
                        contentHeight: page.height
                        clip: true
                        ScrollBar.vertical: VScroll { }
                        Loader {
                            id: page
                            width: scroller.width - 12
                            height: item ? item.implicitHeight : 0
                            Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: scroller.modelData, bridge: node.bridge})
                        }
                    }
                }
            }
        }
    }
    Component {
        id: listComponent
        KineticListView {
            implicitHeight: 100
            clip: true
            model: node.spec.rows
            ScrollBar.vertical: VScroll { }
            delegate: ItemDelegate {
                required property var modelData
                width: ListView.view.width
                text: modelData.title
                highlighted: node.spec.selected.indexOf(modelData.identity) >= 0
                MouseArea {
                    anchors.fill: parent
                    onClicked: mouse => node.spec.pick(parent.modelData.identity, !!(mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)))
                }
            }
        }
    }
    Component {
        id: canvasComponent
        LayoutCanvas {
            objectName: "mossLayoutCanvas"
            implicitWidth: 240
            implicitHeight: 240
            bridge: node.bridge
            HoverHandler { cursorShape: node.bridge.toolkitObject.drawing ? Qt.CrossCursor : Qt.ArrowCursor }
        }
    }
    Component {
        id: fieldComponent
        ColumnLayout {
            implicitWidth: node.spec.kind === "combo" ? 140 : 200
            Label { text: node.spec.title; visible: node.spec.kind !== "check"; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Loader {
                Layout.fillWidth: true
                sourceComponent: {
                    switch (node.spec.kind) {
                    case "combo": return comboField
                    case "check": return checkField
                    case "number": return numberField
                    case "text": return textField
                    default: return entryField
                    }
                }
            }
            Row {
                visible: node.spec.kind === "palette"
                spacing: 4
                Repeater {
                    model: node.spec.swatches
                    Button {
                        required property string modelData
                        width: 28; height: 26
                        contentItem: Rectangle { color: modelData; border.color: "#777777" }
                        onClicked: { colourPicker.replace = modelData; colourPicker.selectedColor = modelData; colourPicker.open() }
                    }
                }
            }
            Button {
                visible: node.spec.kind === "palette"
                text: "Choose colour…"
                onClicked: { colourPicker.replace = ""; colourPicker.open() }
            }
            ColorDialog {
                id: colourPicker
                property string replace: ""
                onAccepted: node.spec.colour(selectedColor.toString(), replace)
            }
        }
    }
    Component {
        id: comboField
        ComboBox {
            model: node.spec.options
            currentIndex: node.spec.options.indexOf(node.spec.value)
            displayText: currentText || "Unspecified"
            onActivated: index => node.spec.edit(node.spec.options[index])
        }
    }
    Component { id: checkField; CheckBox { text: node.spec.title; checked: node.spec.value === true; onToggled: node.spec.edit(checked) } }
    Component {
        id: numberField
        SpinBox {
            property int factor: node.spec.options[2] < 1 ? 100 : 1
            from: node.spec.options[0] * factor
            to: node.spec.options[1] * factor
            stepSize: node.spec.options[2] * factor
            value: Math.round(Number(node.spec.value || 0) * factor)
            editable: true
            textFromValue: (v, locale) => Number(v / factor).toLocaleString(locale, 'f', factor === 100 ? 2 : 0)
            valueFromText: (text, locale) => Math.round(Number.fromLocaleString(locale, text) * factor)
            validator: DoubleValidator { bottom: parent.from / parent.factor; top: parent.to / parent.factor }
            onValueModified: node.spec.edit(value / factor)
        }
    }
    Component {
        id: textField
        KineticFlickable {
            id: textViewport
            implicitHeight: 95
            contentWidth: width
            contentHeight: textEdit.implicitHeight
            clip: true
            ScrollBar.vertical: VScroll { }
            TextArea {
                id: textEdit
                objectName: "layoutField_" + node.spec.title
                width: parent.width
                text: node.spec.value || ""
                wrapMode: TextEdit.Wrap
                persistentSelection: true
                onTextChanged: if (text !== node.spec.value) node.spec.edit(text)
            }
            Spelling { target: textEdit; viewport: textViewport }
        }
    }
    Component {
        id: entryField
        Item {
            implicitHeight: entry.implicitHeight
            TextField {
                id: entry
                objectName: "layoutField_" + node.spec.title
                anchors.fill: parent
                text: node.spec.value || ""
                persistentSelection: true
                onTextChanged: if (text !== node.spec.value) node.spec.edit(text)
            }
            Spelling {
                target: entry
                enabled: node.spec.title !== "Vertical guides (%; comma-separated)" && node.spec.title !== "Horizontal guides (%; comma-separated)"
                visible: enabled
            }
        }
    }
}

import QtQuick
import "PromptWeight.js" as PromptWeight
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
    implicitHeight: !visible ? 0 : content.item ? content.item.implicitHeight : 0
    Loader {
        id: content
        anchors.fill: parent
        sourceComponent: {
            switch (node.spec.kind) {
            case "row": case "toolbar": return rowComponent
            case "compact": return compactComponent
            case "spacer": return spacerComponent
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
    Component { id: spacerComponent; Item { implicitWidth: 0; implicitHeight: 0 } }
    Component {
        id: compactComponent
        Item {
            objectName: "layoutCoordinates"
            implicitWidth: fields.implicitWidth
            implicitHeight: fields.implicitHeight
            RowLayout {
                id: fields
                objectName: "layoutCoordinateFields"
                anchors.centerIn: parent
                spacing: 2
                visible: parent.width >= implicitWidth
                Repeater {
                    model: node.spec.nodes
                    Loader {
                        required property QtObject modelData
                        Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge})
                        Layout.preferredWidth: item ? item.implicitWidth : 0
                        Layout.preferredHeight: item ? item.implicitHeight : 0
                        Layout.fillHeight: true
                    }
                }
            }
        }
    }
    Component {
        id: rowComponent
        RowLayout {
            spacing: node.spec.kind === "toolbar" ? 2 : 6
            Repeater {
                model: node.spec.nodes
                Loader {
                    required property QtObject modelData
                    Layout.preferredHeight: item ? item.implicitHeight : 0
                    visible: modelData.shown
                    Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge})
                    Layout.fillWidth: modelData.expand
                    Layout.fillHeight: node.spec.kind === "toolbar" || modelData.expand || modelData.kind === "inspector"
                    Layout.preferredWidth: modelData.kind === "inspector" ? 300 : (item ? item.implicitWidth : 0)
                    Layout.minimumWidth: modelData.kind === "canvas" ? 140
                        : node.spec.kind === "toolbar" && modelData.kind !== "compact" && modelData.kind !== "spacer"
                          ? (item ? item.implicitWidth : 0) : 0
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
    Component {
        id: buttonComponent
        Button {
            readonly property bool adding: node.spec.title === "Add"
            readonly property string actionIcon: ({Add: "list-add", Undo: "edit-undo", Redo: "edit-redo",
                Hide: "view-hidden", Lock: "object-locked", Delete: "list-remove", Duplicate: "edit-copy"})[node.spec.title] || ""
            objectName: adding ? "layoutAdd" : ""
            text: node.spec.title
            implicitWidth: actionIcon ? implicitHeight : Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
            icon.name: actionIcon
            checkable: node.spec.title === "Lock" || node.spec.title === "Hide"
            checked: checkable && node.spec.value === true
            display: actionIcon ? AbstractButton.IconOnly : AbstractButton.TextOnly
            Accessible.name: adding ? "Add region" : text
            ToolTip.visible: hovered && (actionIcon !== "" || text === "Auto" || text === "Write")
            ToolTip.text: text === "Write" ? "Write or polish the region prompt" : text === "Auto" ? "Generate tags from the region prompt" : adding ? "Add region" : node.spec.title === "Lock" ? "Lock / unlock selected regions" : node.spec.title === "Hide" ? "Hide / show selected regions in generation" : text
            onClicked: node.spec.activate()
        }
    }
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
        TabBar {
            currentIndex: Number(node.spec.value)
            onCurrentIndexChanged: if (currentIndex !== Number(node.spec.value)) node.spec.edit(currentIndex)
            Repeater {
                model: node.spec.nodes
                TabButton { required property QtObject modelData; text: modelData.title }
            }
        }
    }

    Component {
        id: listComponent
        Item {
            id: listBox
            property int listHeight: Prefs.get("layout.regionListHeight") || 0
            implicitHeight: regionList.height + 10
            KineticListView {
                id: regionList
                width: parent.width
                height: listBox.listHeight > 0 ? listBox.listHeight : Math.min(140, contentHeight)
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
            Rectangle {
                y: regionList.height
                width: parent.width
                height: 10
                color: listGrip.pressed || listGrip.containsMouse ? Theme.accent : "transparent"
                Row {
                    anchors.centerIn: parent
                    spacing: 3
                    Repeater { model: 3; Rectangle { width: 3; height: 1; color: Theme.dim } }
                }
                MouseArea {
                    id: listGrip
                    objectName: "regionListResizeHandle"
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.SizeVerCursor
                    preventStealing: true
                    property real startY: 0
                    property real startHeight: 0
                    onPressed: mouse => { startY = mapToItem(null, mouse.x, mouse.y).y; startHeight = regionList.height }
                    onPositionChanged: mouse => {
                        if (pressed) listBox.listHeight = Math.max(28, Math.min(600, Math.round(startHeight + mapToItem(null, mouse.x, mouse.y).y - startY)))
                    }
                    onReleased: Prefs.set("layout.regionListHeight", listBox.listHeight)
                }
            }
        }
    }

    Component {
        id: canvasComponent
        Item {
            id: canvasBox
            property int canvasHeight: Math.max(140, Math.min(1200, Prefs.get("layout.canvasHeight") || 300))
            implicitWidth: 240
            implicitHeight: canvasHeight + 12
            Rectangle { width: parent.width; height: canvasBox.canvasHeight; color: Theme.bg }
            LayoutCanvas {
                objectName: "mossLayoutCanvas"
                width: parent.width
                height: canvasBox.canvasHeight
                bridge: node.bridge
                inactiveColor: Theme.dim
                previewFont: (typeof DeskStyle !== "undefined" && DeskStyle
                              && typeof DeskStyle.editorFontForScale === "function")
                             ? DeskStyle.editorFontForScale(Screen.devicePixelRatio)
                             : Theme.editorFontForScale(Screen.devicePixelRatio)
                HoverHandler { cursorShape: node.bridge.toolkitObject.drawing ? Qt.CrossCursor : Qt.ArrowCursor }
            }
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 10
                color: resizeGrip.pressed || resizeGrip.containsMouse ? Theme.accent : "transparent"
                Row {
                    anchors.centerIn: parent
                    spacing: 3
                    Repeater {
                        model: 3
                        Rectangle { width: 3; height: 1; color: resizeGrip.pressed || resizeGrip.containsMouse ? Theme.bg : Theme.dim }
                    }
                }
                MouseArea {
                    id: resizeGrip
                    objectName: "layoutResizeHandle"
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.SizeVerCursor
                    preventStealing: true
                    property real startY: 0
                    property int startHeight: 0
                    onPressed: mouse => {
                        startY = mapToItem(null, mouse.x, mouse.y).y
                        startHeight = canvasBox.canvasHeight
                    }
                    onReleased: Prefs.set("layout.canvasHeight", canvasBox.canvasHeight)
                    onPositionChanged: mouse => {
                        if (pressed)
                            canvasBox.canvasHeight = Math.max(140, Math.min(1200,
                                Math.round(startHeight + mapToItem(null, mouse.x, mouse.y).y - startY)))
                    }
                }
            }
        }
    }
    Component {
        id: fieldComponent
        ColumnLayout {
            implicitWidth: node.spec.kind === "tokens" ? 80 : node.spec.kind === "count" ? 64 : node.spec.kind === "iconcheck" ? 32 : node.spec.kind.startsWith("inline_") ? 140 : node.spec.kind === "pair" ? 78 : node.spec.kind === "combo" ? (node.spec.title ? 140 : 90) : 200
            Label { text: node.spec.title; visible: node.spec.kind !== "prompt" && node.spec.kind !== "iconcheck" && !node.spec.kind.startsWith("inline_") && node.spec.kind !== "check" && node.spec.kind !== "pair" && node.spec.title !== ""; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Loader {
                Layout.fillWidth: true
                sourceComponent: {
                    switch (node.spec.kind) {
                    case "combo": return comboField
                    case "check": return checkField
                    case "iconcheck": return iconCheckField
                    case "number": case "count": case "tokens": return numberField
                    case "text": case "prompt": return textField
                    case "pair": return pairField
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
            ColorDialog {
                id: colourPicker
                property string replace: ""
                onAccepted: node.spec.colour(selectedColor.toString(), replace)
            }
        }
    }
    Component {
        id: pairField
        TextField {
            text: node.spec.value || ""
            Accessible.name: node.spec.title
            ToolTip.visible: hovered
            ToolTip.text: node.spec.title + "; comma-separated"
            onEditingFinished: node.spec.edit(text)
        }
    }
    Component {
        id: comboField
        ComboBox {
            model: node.spec.options
            currentIndex: node.spec.options.indexOf(node.spec.value)
            displayText: currentText || (node.spec.title === "" ? "Mixed" : "Unspecified")
            onActivated: index => node.spec.edit(node.spec.options[index])
        }
    }
    Component {
        id: iconCheckField
        Button {
            checkable: true
            checked: node.spec.value === true
            icon.name: "edit-select-all"
            display: AbstractButton.IconOnly
            Accessible.name: node.spec.title
            ToolTip.visible: hovered
            ToolTip.text: node.spec.title
            onToggled: node.spec.edit(checked)
        }
    }
    Component { id: checkField; CheckBox { text: node.spec.title; checked: node.spec.value === true; onToggled: node.spec.edit(checked) } }
    Component {
        id: numberField
        SpinBox {
            Accessible.name: node.spec.kind === "tokens" ? "Token limit" : node.spec.kind === "count" ? "Tag count" : node.spec.title
            ToolTip.visible: hovered && (node.spec.kind === "count" || node.spec.kind === "tokens")
            ToolTip.text: node.spec.kind === "tokens" ? "Maximum output tokens" : "Number of tags to generate"
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
        Item {
            id: textBox
            readonly property bool resizablePrompt: node.spec.title === "Prompt" || node.spec.title === "Exact wording"
            readonly property string heightKey: node.spec.title === "Exact wording" ? "layout.wordingHeight" : "layout.regionPromptHeight"
            property int promptHeight: resizablePrompt ? Math.max(40, Math.min(600, Prefs.get(heightKey) || 95)) : 95
            implicitHeight: promptHeight + (resizablePrompt ? 10 : 0)
            KineticFlickable {
                id: textViewport
                width: parent.width
                height: textBox.promptHeight
                contentWidth: node.spec.title === "Exact wording" ? Math.max(width, textEdit.contentWidth + textEdit.leftPadding + textEdit.rightPadding) : width
                contentHeight: textEdit.implicitHeight
                clip: true
                ScrollBar.vertical: VScroll { }
                ScrollBar.horizontal: ScrollBar { policy: node.spec.title === "Exact wording" ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
                TextArea {
                    id: textEdit
                    objectName: "layoutField_" + node.spec.title
                    width: parent.width
                    text: node.spec.value || ""
                    wrapMode: node.spec.title === "Exact wording" ? TextEdit.NoWrap : TextEdit.Wrap
                    persistentSelection: true
                    Keys.onPressed: function(event) {
                        if (node.spec.kind === "prompt" && (event.modifiers & Qt.ControlModifier)
                                && (event.key === Qt.Key_Up || event.key === Qt.Key_Down))
                            event.accepted = PromptWeight.adjust(textEdit, event.key === Qt.Key_Up ? 0.1 : -0.1)
                    }
                    onTextChanged: if (text !== node.spec.value) node.spec.edit(text)
                }
                Spelling { target: textEdit; viewport: textViewport }
            }
            Rectangle {
                visible: textBox.resizablePrompt
                y: textBox.promptHeight
                width: parent.width
                height: 10
                color: promptGrip.pressed || promptGrip.containsMouse ? Theme.accent : "transparent"
                Row { anchors.centerIn: parent; spacing: 3; Repeater { model: 3; Rectangle { width: 3; height: 1; color: Theme.dim } } }
                MouseArea {
                    id: promptGrip
                    objectName: node.spec.title === "Exact wording" ? "wordingResizeHandle" : "regionPromptResizeHandle"
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.SizeVerCursor
                    preventStealing: true
                    property real startY: 0
                    property real startHeight: 0
                    onPressed: mouse => { startY = mapToItem(null, mouse.x, mouse.y).y; startHeight = textBox.promptHeight }
                    onPositionChanged: mouse => {
                        if (pressed) textBox.promptHeight = Math.max(40, Math.min(600, Math.round(startHeight + mapToItem(null, mouse.x, mouse.y).y - startY)))
                    }
                    onReleased: Prefs.set(textBox.heightKey, textBox.promptHeight)
                }
            }
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
                placeholderText: node.spec.kind.startsWith("inline_") ? node.spec.title : ""
                Accessible.name: node.spec.title
                ToolTip.visible: hovered && node.spec.kind.startsWith("inline_")
                ToolTip.text: node.spec.title + "; comma-separated"
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

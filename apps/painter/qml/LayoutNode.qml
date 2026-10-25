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
    property var tokenProbe: null
    visible: spec.shown
    enabled: spec.enabled
    implicitWidth: content.item ? content.item.implicitWidth : 0
    implicitHeight: !visible ? 0 : content.item ? content.item.implicitHeight : 0
    Loader {
        id: content
        anchors.fill: parent
        sourceComponent: {
            switch (node.spec.kind) {
            case "row": return rowComponent
            case "toolbar": return toolbarComponent
            case "compact": return compactComponent
            case "spacer": return spacerComponent
            case "column": case "page": case "inspector": return columnComponent
            case "button": return buttonComponent
            case "label": return labelComponent
            case "tokencount": return tokenCountComponent
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
        id: tokenCountComponent
        Label {
            objectName: "regionTokenCount"
            visible: node.tokenProbe && node.tokenProbe.active
            text: node.tokenProbe && node.tokenProbe.count >= 0 ? node.tokenProbe.count + " tok" : "— tok"
            ToolTip.visible: countHover.containsMouse
            ToolTip.text: node.tokenProbe ? node.tokenProbe.tip : ""
            MouseArea { id: countHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
        }
    }
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
                        Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge, tokenProbe: node.tokenProbe})
                        Layout.preferredWidth: item ? item.implicitWidth : 0
                        Layout.preferredHeight: item ? item.implicitHeight : 0
                        Layout.fillHeight: true
                    }
                }
            }
        }
    }
    Component {
        id: toolbarComponent
        Flow {
            id: toolbar
            objectName: "layoutToolbar"
            spacing: 2
            // Coordinates are optional; actions wrap instead of forcing the
            // sidebar wider than the space the user has given it.
            readonly property real requestedWidth: {
                var total = 0, count = 0
                for (var i = 0; i < toolbarItems.count; ++i) {
                    var child = toolbarItems.itemAt(i)
                    if (!child || !child.modelData.shown || child.modelData.kind === "spacer") continue
                    total += child.item ? child.item.implicitWidth : 0
                    count++
                }
                return total + Math.max(0, count - 1) * spacing
            }
            Repeater {
                id: toolbarItems
                model: node.spec.nodes
                Loader {
                    required property QtObject modelData
                    visible: modelData.shown && modelData.kind !== "spacer"
                        && (modelData.kind !== "compact" || toolbar.width >= toolbar.requestedWidth)
                    width: Math.min(toolbar.width, item ? item.implicitWidth : 0)
                    height: item ? item.implicitHeight : 0
                    Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge, tokenProbe: node.tokenProbe})
                }
            }
        }
    }
    Component {
        id: rowComponent
        RowLayout {
            id: rowLayout
            spacing: node.spec.kind === "toolbar" ? 2 : 6
            // Measure all requested controls, including a currently hidden
            // coordinate group, so widening can restore it without a latch.
            readonly property real requestedWidth: {
                var total = 0, count = 0
                for (var i = 0; i < rowItems.count; ++i) {
                    var child = rowItems.itemAt(i)
                    if (!child || !child.modelData.shown) continue
                    total += child.item ? child.item.implicitWidth : 0
                    count++
                }
                return total + Math.max(0, count - 1) * spacing
            }
            readonly property bool coordinatesFit: width >= requestedWidth
            readonly property bool hasStretch: {
                for (var i = 0; i < node.spec.nodes.length; ++i)
                    if (node.spec.nodes[i].expand) return true
                return false
            }
            Repeater {
                id: rowItems
                model: node.spec.nodes
                Loader {
                    required property QtObject modelData
                    Layout.preferredHeight: item ? item.implicitHeight : 0
                    visible: modelData.shown && (modelData.kind !== "compact" || rowLayout.coordinatesFit)
                    Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge, tokenProbe: node.tokenProbe})
                    Layout.fillWidth: modelData.expand
                    Layout.fillHeight: node.spec.kind === "toolbar" || modelData.expand || modelData.kind === "inspector"
                    Layout.preferredWidth: modelData.kind === "inspector" ? 300 : (item ? item.implicitWidth : 0)
                    Layout.minimumWidth: modelData.kind === "canvas" ? 140
                        : node.spec.kind === "toolbar" && modelData.kind !== "compact" && modelData.kind !== "spacer"
                          ? (item ? item.implicitWidth : 0) : 0
                }
            }
            Item {
                visible: node.spec.kind !== "toolbar" && !rowLayout.hasStretch
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 0
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
                    Component.onCompleted: setSource(Qt.resolvedUrl("LayoutNode.qml"), {spec: modelData, bridge: node.bridge, tokenProbe: node.tokenProbe})
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
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
            NativeContentContext {}
            property int listHeight: Prefs.get("layout.regionListHeight") || 0
            implicitHeight: regionList.height + 10
            Rectangle {
                objectName: "regionListBackground"
                width: parent.width
                height: regionList.height
                color: Theme.bg
                border.color: Theme.border
            }
            KineticListView {
                id: regionList
                objectName: "regionList"
                width: parent.width
                height: listBox.listHeight > 0 ? listBox.listHeight : Math.min(140, contentHeight)
                clip: true
                model: node.spec.rows
                ScrollBar.vertical: VScroll { id: listBar }
                spacing: 0
                property int dropIndex: -1
                delegate: ItemDelegate {
                    id: regionRow
                    objectName: "regionRow_" + modelData.identity
                    required property var modelData
                    width: ListView.view.width - listBar.barW
                    height: Math.max(implicitContentHeight, icon.height) + 2
                    topPadding: 1
                    bottomPadding: 1
                    topInset: 0
                    bottomInset: 0
                    text: modelData.title
                    icon.name: modelData.icon
                    icon.width: 16
                    icon.height: 16
                    highlighted: node.spec.selected.indexOf(modelData.identity) >= 0
                    Rectangle {
                        width: parent.width
                        height: 2
                        color: Theme.focusColor
                        visible: regionList.dropIndex >= 0 && regionList.indexAt(0, regionRow.y) === regionList.dropIndex
                    }
                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        property real startY: 0
                        property bool moving: false
                        function updateDrop() {
                            const point = mapToItem(regionList.contentItem, 0, mouseY)
                            regionList.dropIndex = regionList.indexAt(1, Math.max(0, Math.min(regionList.contentHeight - 1, point.y)))
                        }
                        onPressed: mouse => { startY = mouse.y; moving = false }
                        onPositionChanged: mouse => {
                            if (!pressed || regionRow.modelData.locked) return
                            if (Math.abs(mouse.y - startY) >= Qt.styleHints.startDragDistance) moving = true
                            if (moving) updateDrop()
                        }
                        onReleased: mouse => {
                            const target = regionList.dropIndex
                            regionList.dropIndex = -1
                            if (moving) node.spec.reorder(regionRow.modelData.identity, target)
                            else node.spec.pick(regionRow.modelData.identity, !!(mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)))
                        }
                        onCanceled: { moving = false; regionList.dropIndex = -1 }
                        Timer {
                            interval: 50
                            repeat: true
                            running: rowMouse.pressed && rowMouse.moving
                            onTriggered: {
                                const y = rowMouse.mapToItem(regionList, 0, rowMouse.mouseY).y
                                const step = y < 20 ? -12 : y > regionList.height - 20 ? 12 : 0
                                regionList.contentY = Math.max(0, Math.min(Math.max(0, regionList.contentHeight - regionList.height), regionList.contentY + step))
                                rowMouse.updateDrop()
                            }
                        }
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
                selectedColor: Theme.focusColor
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
                visible: node.spec.kind === "palette" && node.spec.swatches.length > 0
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
            icon.name: node.spec.options.length === 2 ? node.spec.options[checked ? 0 : 1] : "edit-select-all"
            display: AbstractButton.IconOnly
            Accessible.name: node.spec.title
            ToolTip.visible: hovered
            ToolTip.text: node.spec.title + (checked ? " — On" : " — Off")
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
                contentWidth: node.spec.title === "Exact wording" ? Math.max(width - textBar.barW, textEdit.contentWidth + textEdit.leftPadding + textEdit.rightPadding) : width - textBar.barW
                contentHeight: textEdit.height
                clip: true
                ScrollBar.vertical: VScroll { id: textBar }
                ScrollBar.horizontal: ScrollBar { id: textHBar; policy: node.spec.title === "Exact wording" ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
                TextArea {
                    id: textEdit
                    readonly property bool tokenReady: node.spec.kind === "prompt" && node.tokenProbe && node.tokenProbe.count >= 0
                    readonly property var tokenStyle: App.inspection.tokenStyle(color.toString(), palette.base.toString(), selectionColor.toString())
                    objectName: "layoutField_" + node.spec.title
                    width: textViewport.width - textBar.barW
                    height: Math.max(implicitHeight, textViewport.height - (textHBar.visible ? textHBar.height : 0))
                    text: node.spec.value || ""
                    wrapMode: node.spec.title === "Exact wording" ? TextEdit.NoWrap : TextEdit.Wrap
                    persistentSelection: true
                    Keys.onPressed: function(event) {
                        if (node.spec.kind === "prompt" && (event.modifiers & Qt.ControlModifier)
                                && (event.key === Qt.Key_Up || event.key === Qt.Key_Down))
                            event.accepted = PromptWeight.adjust(textEdit, event.key === Qt.Key_Up ? 0.1 : -0.1)
                    }
                    onTextChanged: if (text !== node.spec.value) node.spec.edit(text)
                    TokenBands {
                        editor: textEdit
                        viewport: textViewport
                        boundaries: node.tokenProbe ? node.tokenProbe.boundaries : []
                        colours: textEdit.tokenStyle.bands
                        marked: textEdit.tokenReady
                        highlighted: {
                            App.inspection.nearby
                            return node.spec.kind === "prompt" ? App.inspection.highlightedRanges(textEdit.text, node.bridge.regionIdentity) : []
                        }
                        z: -0.5
                    }
                    Repeater {
                        model: textEdit.tokenReady ? node.tokenProbe.boundaries : []
                        Rectangle {
                            required property int modelData
                            readonly property rect mark: {
                                textEdit.text; textEdit.width; textEdit.font
                                return textEdit.positionToRectangle(modelData)
                            }
                            x: mark.x - 1; y: mark.y + 2
                            width: 1; height: Math.max(1, mark.height - 4)
                            color: textEdit.tokenStyle.separator
                        }
                    }
                    TapHandler {
                        enabled: node.spec.kind === "prompt" && App.inspection.picking
                        acceptedButtons: Qt.LeftButton
                        onTapped: App.inspection.pickToken(textEdit.text, textEdit.positionAt(point.position.x, point.position.y), node.bridge.regionIdentity)
                    }
                    HoverHandler {
                        enabled: node.spec.kind === "prompt"
                        onHoveredChanged: {
                            if (hovered)
                                App.inspection.hoverRegion(textEdit.text, textEdit.positionAt(point.position.x, point.position.y), node.bridge.regionIdentity)
                            else App.inspection.endHover("region:" + node.bridge.regionIdentity)
                        }
                        onPointChanged: if (hovered)
                            App.inspection.hoverRegion(textEdit.text, textEdit.positionAt(point.position.x, point.position.y), node.bridge.regionIdentity)
                    }
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

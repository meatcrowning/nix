import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../qmlcommon"

Rectangle {
    id: panel
    property var params: null
    property string path: ""
    readonly property var fields: App.comparisonFields(params)
    color: Theme.bg
    border.color: Theme.border
    clip: true
    objectName: "parameterCompare"
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onWheel: wheel => wheel.accepted = true
    }
    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 12
        contentWidth: availableWidth
        Column {
            width: scroll.availableWidth
            spacing: 8
            Label {
                width: parent.width
                text: panel.path.split("/").pop() || "Select a saved output to compare."
                wrapMode: Text.Wrap
            }
            Label {
                width: parent.width
                visible: panel.path !== "" && panel.fields.length === 0
                text: "No generation settings are saved in this output."
                wrapMode: Text.Wrap
            }
            Repeater {
                model: panel.fields
                Column {
                    id: row
                    required property var modelData
                    width: parent.width
                    spacing: 4
                    Label {
                        width: parent.width
                        text: row.modelData.label
                        font.bold: row.modelData.kind === "heading"
                    }
                    Loader {
                        width: parent.width
                        active: row.modelData.kind !== "heading"
                        sourceComponent: row.modelData.kind === "prompt" ? prose
                                         : row.modelData.kind === "number" ? number
                                         : row.modelData.kind === "check" ? check
                                         : row.modelData.kind === "choice" ? choice : entry
                    }
                    Component {
                        id: prose
                        TextArea {
                            text: row.modelData.text
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                        }
                    }
                    Component {
                        id: entry
                        TextField {
                            text: row.modelData.text
                            readOnly: true
                            selectByMouse: true
                        }
                    }
                    Component {
                        id: number
                        SpinBox {
                            from: 0; to: 0; value: 0
                            editable: true
                            textFromValue: function(value, locale) { return row.modelData.text }
                            valueFromText: function(text, locale) { return 0 }
                            Component.onCompleted: {
                                contentItem.readOnly = true
                                contentItem.selectByMouse = true
                            }
                        }
                    }
                    Component {
                        id: choice
                        ComboBox {
                            model: [row.modelData.text]
                            editable: true
                            Component.onCompleted: {
                                contentItem.readOnly = true
                                contentItem.selectByMouse = true
                            }
                        }
                    }
                    Component {
                        id: check
                        CheckBox {
                            checked: row.modelData.value
                            nextCheckState: function() { return row.modelData.value ? Qt.Checked : Qt.Unchecked }
                        }
                    }
                }
            }
        }
    }
    onPathChanged: {
        if (scroll.contentItem) scroll.contentItem.contentY = 0
    }
}

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../qmlcommon"

Column {
    id: writer
    property string scope: "positive"
    property bool busy: false
    property string requestId: ""
    property string snapshot: ""
    property var history: null
    property string status: ""
    objectName: scope + "PromptWriter"
    width: parent.width
    spacing: 2

    function currentSnapshot() {
        return JSON.stringify([App.selectedName, root.gen.positive, root.gen.negative])
    }
    function write() {
        if (busy) return
        snapshot = currentSnapshot()
        requestId = scope + ":" + Date.now()
        busy = true
        status = "Writing prompt…"
        App.writePrompt(requestId, {task: "prompt", scope: scope,
            caption: root.gen[scope], scene: root.gen.positive,
            tokens: limit.value, moss: App.layoutSupport})
    }
    function undo() {
        if (!busy && history && history.model === App.selectedName && root.gen[scope] === history.after) {
            root.set(scope, history.before)
            history = null
            status = ""
        }
    }
    Connections {
        target: App
        function onPromptWritten(identity, result) {
            if (!writer.busy || identity !== writer.requestId) return
            writer.busy = false
            if (writer.currentSnapshot() !== writer.snapshot) {
                writer.status = "Result discarded because the prompt or model changed."
            } else if (result.error) {
                writer.status = result.error
            } else if (result.prompt) {
                writer.history = {model: App.selectedName, before: root.gen[writer.scope], after: result.prompt}
                root.set(writer.scope, result.prompt)
                writer.status = ""
            }
        }
    }
    RowLayout {
        width: parent.width
        spacing: 4
        PixelText { text: writer.scope === "negative" ? "Negative prompt" : "Prompt" }
        SpinBox {
            id: limit
            from: 16; to: 512; stepSize: 16; value: 128
            editable: true
            Accessible.name: "Maximum output tokens"
            ToolTip.visible: hovered
            ToolTip.text: "Maximum output tokens"
        }
        Button {
            text: "Write"
            enabled: !writer.busy
            onClicked: writer.write()
        }
        Button {
            text: "Undo"
            enabled: !writer.busy && writer.history !== null
                     && writer.history.model === App.selectedName
                     && root.gen[writer.scope] === writer.history.after
            onClicked: writer.undo()
        }
        Item { Layout.fillWidth: true }
    }
    PixelText {
        width: parent.width
        visible: text.length > 0
        text: writer.status
        wrapMode: Text.Wrap
    }
}

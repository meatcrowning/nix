import QtQuick

// The LoRA chain.  Only LoRAs whose tensors actually target the selected model
// are offered by default; the rest are one toggle away, each with the reason it
// was rejected.  Chain order matters, so rows can be moved.
Panel {
    id: panel
    title: "LoRA"
    badge: Loras.count > 0 ? (Loras.count + " active") : ""
    property bool picking: false

    Column {
        width: parent.width
        spacing: 3

        Repeater {
            model: Loras
            delegate: LoraRow {
                width: panel.width - 16
                rowIndex: index
                loraName: name
                strength: model.strength
                on: model.enabled
            }
        }

        PixelText {
            visible: Loras.count === 0
            text: "None"
            color: Theme.dim
        }

        Row {
            spacing: 6
            TextButton {
                label: panel.picking ? "[ Close ]" : "[ Add LoRA ]"
                lit: panel.picking
                winActive: root.winActive
                onClicked: panel.picking = !panel.picking
            }
            TextButton {
                visible: Loras.count > 0
                label: "[ Clear ]"
                tone: Theme.dim
                winActive: root.winActive
                onClicked: Loras.clear()
            }
        }

        LoraPicker {
            visible: panel.picking
            width: parent.width
            onChose: panel.picking = false
        }
    }
}

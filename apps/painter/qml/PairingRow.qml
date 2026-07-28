import QtQuick

// The derived encoder/VAE, shown so the automatic choice is never a mystery,
// and overridable when the guess is wrong.
Column {
    id: rowBox
    spacing: 4
    property bool expanded: false

    Row {
        spacing: 6
        width: parent.width

        PixelText {
            text: rowBox.expanded ? "-" : "+"
            color: Theme.dim
            MouseArea { anchors.fill: parent; onClicked: rowBox.expanded = !rowBox.expanded }
        }
        PixelText {
            text: App.encoderName === "" ? "bundled encoder and VAE" : "auto-paired"
            color: Theme.textDim
        }
        PixelText {
            text: rowBox.expanded ? "" : "(override)"
            color: Theme.dim
            MouseArea { anchors.fill: parent; onClicked: rowBox.expanded = true }
        }
    }

    Field {
        visible: rowBox.expanded && App.encoderName !== ""
        label: "encoder"
        hint: "Picked by matching this model's own dimensions against each encoder's hidden size."
        Picker {
            width: 250
            options: App.encoderNames()
            value: App.encoderName
            onPicked: function (v) { App.overrideEncoder(App.selectedIndex, v) }
        }
    }

    Field {
        visible: rowBox.expanded && App.vaeName !== ""
        label: "vae"
        hint: "Some VAEs are structurally identical, so this falls back to a hash and then to your choice."
        Picker {
            width: 250
            options: App.vaeNames()
            value: App.vaeName
            onPicked: function (v) { App.overrideVae(App.selectedIndex, v) }
        }
    }
}

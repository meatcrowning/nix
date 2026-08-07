import QtQuick

// THE FOUR THINGS HE ACTUALLY MAKES, above the list of everything he could.
// [his] "there should be a switcher for anime ... real ... edition ... video"
// — one button each, and the one that is on greys the model list out, because
// while a mode is chosen the list is not what decides (ModelPicker).
//
// A mode is a SHORTCUT to a model, not a fifth kind of model: the table of
// which file each one means lives in `registry.MODES`, painter answers it
// through `App.modes()`, and this row only draws the answer. `edit` is the one
// that also changes the pipeline — it builds the Flux 2 Klein edit graph and
// the left column drops to an image well and a prompt (Main.qml).
//
// A mode whose model is not on this machine stays in the row, DISABLED, with
// one dim line saying so underneath: four buttons that are always the same
// four beat a row that silently loses one (docs/DESIGN.md §10). No tooltip on
// the buttons themselves — a ToolTipArea over a TextButton takes the hover
// that draws its own tint, and the tint is the affordance (LoraPicker's
// comment records the same ordering rule from the other side).
Column {
    id: sw
    spacing: 4

    // Rebuilt when the model list is: availability is a fact about what is on
    // disk, and a scan that lands late (book's sshfs mount) must reach this.
    property var items: []
    readonly property bool anyMissing: {
        for (var i = 0; i < items.length; i++)
            if (!items[i].available) return true
        return false
    }
    function refresh() { sw.items = App.modes() }
    Component.onCompleted: refresh()
    Connections {
        target: App
        function onModelChanged() { sw.refresh() }
    }

    Row {
        spacing: 4

        Repeater {
            model: sw.items

            TextButton {
                required property var modelData
                label: "[ " + modelData.label + " ]"
                tone: Theme.textDim
                lit: App.mode === modelData.id
                enabled: modelData.available
                winActive: root.winActive
                // Clicking the lit one turns it OFF and hands the list back —
                // the same press that chose it, undoing it.
                onClicked: App.setMode(App.mode === modelData.id ? "" : modelData.id)
            }
        }
    }

    PixelText {
        visible: sw.anyMissing
        width: sw.width
        wrapMode: Text.Wrap
        text: "a greyed mode has no model on this machine"
        color: Theme.dim
    }
}
